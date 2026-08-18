#!/usr/bin/env python3
"""把仓库根目录下的 csv/tsv 源词库编译为 parquet(.pq)。

编译模块（pqcompile / colproto / headparser / typing_utils）**不随本仓库分发**，
以实时引用方式取自 tianzi 的 lexloader/（唯一权威副本）：

1. 本目录作为 tianzi 子模块挂载时（tianzi/lexloader/lexicons/），直接引用
   父目录 lexloader/ 下的文件 —— 编辑 lexloader 立即生效，无副本可过期；
2. CI 通过 LEX_COMPILER_DIR 指向拉取到的 tianzi lexloader/；
3. 也可用 --compiler-dir 显式指定。

用法:
    python compile.py [--compiler-dir <路径>]
"""
from __future__ import annotations

import argparse
import os
import pathlib
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--compiler-dir", help="含 pqcompile.py 等编译模块的目录（默认：父目录或 LEX_COMPILER_DIR）")
    args = ap.parse_args()

    compiler_dir = resolve_compiler_dir(args.compiler_dir)
    sys.path.insert(0, str(compiler_dir))

    import awkward as ak  # noqa: PLC0415
    from pqcompile import compile_dsv  # noqa: PLC0415

    sources = sorted(HERE.glob("*.tsv")) + sorted(HERE.glob("*.csv"))
    if not sources:
        print(f"未在 {HERE} 找到 .tsv/.csv 源文件", file=sys.stderr)
        return 1

    delim = {".tsv": "\t", ".csv": ","}
    for src in sources:
        out = src.with_suffix(".pq")
        print(f"编译 {src.name} -> {out.name}  (compiler: {compiler_dir})", flush=True)
        with src.open("r", encoding="utf-8") as f:
            arr = compile_dsv(f, delim[src.suffix])
        ak.to_parquet(arr, out)
        print(f"  完成: {len(arr)} 行", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
