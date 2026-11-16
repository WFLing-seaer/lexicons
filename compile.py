#!/usr/bin/env python3
"""把仓库根目录下的 csv/tsv 源词库编译为 parquet(.pq)。

编译模块（pqcompile / colproto / headparser / typing_utils）**不随本仓库分发**，
以实时引用方式取自 tianzi 的 lexloader/（唯一权威副本）：

1. 本目录作为 tianzi 子模块挂载时（tianzi/lexloader/lexicons/），直接引用
   父目录 lexloader/ 下的文件 —— 编辑 lexloader 立即生效，无副本可过期；
2. CI 通过 LEX_COMPILER_DIR 指向拉取到的 tianzi lexloader/；
3. 也可用 --compiler-dir 显式指定。

产物里带着编它所用源文件的元数据（文件名、大小、修改时间、sha256，见 pqmeta.py），
所以编译前先读产物自述，决定这个源文件还要不要重编：

- 大小与修改时间都与产物里记的一致 → 直接跳过（连源文件都不用读）；
- 有一个不一致 → 算源文件的 sha256：
  - 与产物里记的一致 → 内容其实没变（只是时间戳变了）→ 跳过；
  - 不一致 → 重编；
- 产物里没有元数据（加这个功能之前编出来的老产物）→ 重编一次，顺手把元数据补上；
- 产物里记的管线指纹（awkward/pyarrow 版本、编译模块的内容 hash、拼音库版本）与当前
  不一致 → 全部重编（改了 lexloader/ 里的编译器，跑一遍就会全量重编，不会留下旧产物）；
- --force 完全忽略元数据；--dry-run 只报结论不写文件；--no-metadata 不写元数据
  （等于放弃跳过能力，每次都编）。

跑完后还会做一次减量检测：目录里的 .pq 若本次运行没有被任何一个源文件判定过
（重编、跳过、出错都算判定过），就当作孤儿剪切到 ./deleted/（不存在则创建；
重名加 .1/.2 后缀）。--dry-run 下只报告不剪切。
注意：带源文件参数时，未列出的源文件对应的 .pq 同样会被判为孤儿并剪切。

用法:
    python compile.py [--compiler-dir <路径>] [--force] [--dry-run] [--no-metadata] [源文件 ...]
    （不带源文件参数 = 编译目录下全部 .tsv/.csv；带参数 = 只编译列出的文件）
"""

from __future__ import annotations

import argparse
import importlib.metadata
import io
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent


def resolve_compiler_dir(explicit: str | None) -> pathlib.Path:
    if explicit:
        return pathlib.Path(explicit).resolve()
    if env := os.environ.get("LEX_COMPILER_DIR"):
        return pathlib.Path(env).resolve()
    # 子模块上下文：父目录即 tianzi/lexloader/，编译模块就在那里
    parent = HERE.parent
    if (parent / "pqcompile.py").is_file():
        return parent
    raise SystemExit(
        "找不到编译模块：请在 tianzi 子模块上下文（lexloader/lexicons/）中运行，"
        "或设置 LEX_COMPILER_DIR / 传 --compiler-dir 指向含 pqcompile.py 的目录"
    )


def dist_version(dist: str) -> str:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def compiler_fingerprint(pqmeta, compiler_dir: pathlib.Path) -> dict[str, str]:
    """编译模块与拼音库的指纹：它们一变，产物内容就可能跟着变，旧产物全部算过期。

    编译模块是本仓库的**实时引用**（lexloader/ 的 .py 直接生效），所以按「本次真正 import 进来
    的那几个 .py」的内容 hash 认（改了编译器再跑 compile.py 就会全量重编），而不是靠 mtime。
    拼音库的版本直接决定拼音列编出来的枚举值（见 requirements.txt 的注释），按版本号认。
    """
    parts: dict[str, str] = {}
    for name, module in sorted(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if not file:
            continue
        path = pathlib.Path(file).resolve()
        if path.suffix == ".py" and path.parent == compiler_dir:
            parts[f"mod:{name}"] = pqmeta.sha256_file(path)[:16]
    for dist in ("pinyinparser", "pypinyin", "pypinyin-dict"):
        parts[f"dist:{dist}"] = dist_version(dist)
    return parts


def quarantine_orphans(handled: set[pathlib.Path], dry_run: bool) -> tuple[int, int]:
    """减量检测：把本次运行没判定过的 .pq 当作孤儿剪切到 ./deleted/。

    handled 里是本次运行判定过的产物路径（重编、跳过、出错都算判定过）。
    返回 (孤儿数, 剪切失败数)。--dry-run 下只报告，不建目录、不剪切。
    """
    orphans = [p for p in sorted(HERE.glob("*.pq")) if p.resolve() not in handled]
    if not orphans:
        print("减量检测：无孤儿 .pq", flush=True)
        return 0, 0

    if dry_run:
        for p in orphans:
            print(f"孤儿（--dry-run，不剪切）: {p.name}", flush=True)
        return len(orphans), 0

    dest_dir = HERE / "deleted"
    dest_dir.mkdir(exist_ok=True)
    failed = 0
    for p in orphans:
        target = dest_dir / p.name
        n = 1
        while target.exists():
            target = dest_dir / f"{p.stem}.{n}{p.suffix}"
            n += 1
        try:
            shutil.move(str(p), str(target))
        except OSError as e:
            print(f"剪切孤儿失败: {p.name} ({e})", file=sys.stderr)
            failed += 1
            continue
        print(f"孤儿剪切: {p.name} -> deleted/{target.name}", flush=True)
    return len(orphans), failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--compiler-dir", help="含 pqcompile.py 等编译模块的目录（默认：父目录或 LEX_COMPILER_DIR）")
    ap.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="忽略产物里记的源文件元数据，指定的源文件全部重编",
    )
    ap.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="只打印每个源文件是「该编」还是「能跳过」，不写任何产物、不剪切孤儿",
    )
    ap.add_argument(
        "--no-metadata",
        action="store_true",
        help="不在产物里写 lexicon.* 元数据（也就无法判断新旧，等于每次都重编）",
    )
    ap.add_argument(
        "sources",
        nargs="*",
        help="只编译这些源文件（相对本目录的 .tsv/.csv 文件名）；不传则编译全部",
    )
    args = ap.parse_args()

    compiler_dir = resolve_compiler_dir(args.compiler_dir)

    # pqmeta 与本文件同目录；先把它导进来，再让编译器目录排到 sys.path 最前面，
    # 免得编译器目录里的同名文件把 pqmeta 抢走（反过来 pqmeta 也不会挡编译器的导入）
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import pqmeta

    sys.path.insert(0, str(compiler_dir))

    import logging

    # 编译器的 JIT 预热进度条是 tqdm 显式传 disable=logger.level > logging.INFO 的，
    # 显式传参优先于 TQDM_DISABLE 环境变量，所以只能把编译器的 logger 级别提上去关掉
    # （只在这里改级别，不修改 lexloader/ 里的编译器本体）
    for _name in ("colproto", "tianzi.lexloader.colproto"):
        logging.getLogger(_name).setLevel(logging.WARNING)

    from pqcompile import compile_dsv

    if args.sources:
        sources: list[pathlib.Path] = []
        for name in args.sources:
            src = HERE / name
            if not src.is_file() or src.suffix not in (".tsv", ".csv"):
                print(f"不是有效的源文件: {name}", file=sys.stderr)
                return 1
            sources.append(src)
    else:
        sources = sorted(HERE.glob("*.tsv")) + sorted(HERE.glob("*.csv"))
    if not sources:
        print(f"未在 {HERE} 找到 .tsv/.csv 源文件", file=sys.stderr)
        return 1

    pipeline = pqmeta.pipeline_fingerprint(extra=compiler_fingerprint(pqmeta, compiler_dir))
    use_metadata = not args.no_metadata
    check_metadata = use_metadata and not args.force

    delim = {".tsv": "\t", ".csv": ","}
    compiled = skip_stamp = skip_hash = error = 0
    # 本次运行判定过的产物（重编 / 跳过 / 出错都算判定过），供收尾的减量检测用
    handled: set[pathlib.Path] = set()

    for src in sources:
        out = src.with_suffix(".pq")
        handled.add(out.resolve())
        st = src.stat()

        meta = pqmeta.read_metadata(out, pipeline=pipeline) if check_metadata else None
        data: bytes | None = None
        src_sha: str | None = None

        if meta is not None and meta["source_name"] == src.name:
            if meta["source_size"] == str(st.st_size) and meta["source_mtime_ns"] == str(st.st_mtime_ns):
                print(f"跳过 {src.name}: 大小与修改时间都没变", flush=True)
                skip_stamp += 1
                continue
            data = src.read_bytes()
            src_sha = pqmeta.sha256_bytes(data)
            if src_sha == meta["source_sha256"]:
                print(f"跳过 {src.name}: sha256 没变（只是修改时间变了）", flush=True)
                skip_hash += 1
                continue

        if args.dry_run:
            print(f"该编 {src.name} -> {out.name}", flush=True)
            compiled += 1
            continue

        if data is None:
            data = src.read_bytes()
            src_sha = pqmeta.sha256_bytes(data)

        print(f"编译 {src.name} -> {out.name}  (compiler: {compiler_dir})", flush=True)
        # 一次读完再解：算 hash 的字节和真正编译的字节严格是同一份
        try:
            arr = compile_dsv(io.StringIO(data.decode("utf-8")), delim[src.suffix])
        except Exception as e:
            print(f"编译失败: {src.name} -> {out.name} ({e})", file=sys.stderr)
            error += 1
            continue
        metadata = (
            None
            if not use_metadata
            else pqmeta.build_metadata(
                source_name=src.name,
                source_size=len(data),
                source_mtime_ns=st.st_mtime_ns,
                source_sha256=src_sha,
                rows=len(arr),
                pipeline=pipeline,
            )
        )
        pqmeta.write_parquet(arr, out, metadata)
        tail = "" if metadata else "（未写元数据）"
        print(f"  完成: {len(arr)} 行{tail}", flush=True)
        compiled += 1

    # 减量检测：本目录里没被本次运行判定过的 .pq 一律视为孤儿，剪切到 ./deleted/
    orphan_count, orphan_failed = quarantine_orphans(handled, args.dry_run)

    skipped = skip_stamp + skip_hash
    head = f"共 {len(sources)} 个源文件："
    tail = f"跳过 {skipped}（修改时间未变 {skip_stamp}，sha256 未变 {skip_hash}），错误 {error}"
    if args.dry_run:
        print(
            f"{head}该编 {compiled}，{tail}；孤儿 {orphan_count}（--dry-run：没有写任何产物）",
            flush=True,
        )
    else:
        print(f"{head}编译 {compiled}，{tail}；孤儿 {orphan_count}（剪切失败 {orphan_failed}）", flush=True)
    return 1 if orphan_failed else 0


if __name__ == "__main__":
    sys.exit(main())
