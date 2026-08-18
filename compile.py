#!/usr/bin/env python3
"""把仓库根目录下的 csv/tsv 源词库编译为 parquet(.pq)。

用法:
    python compile.py

输出写到源文件同目录（<源名>.pq，即仓库根目录），与 pqcompile.py 的 CLI 行为一致。
CI 与本地共用此脚本；生成的 .pq 由 CI 发布到 parquets 分支。
本目录同时是 tianzi 的 lexloader/lexicons 子模块挂载点：运行时只加载 .pq，
其余文件（源、编译器、脚本）都会被忽略，不影响加载。
"""
from __future__ import annotations

import pathlib
import sys

# compiler/ 下的编译模块是扁平模块（无包结构），把目录加进 sys.path 即可 import
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "compiler"))

import awkward as ak  # noqa: E402
from pqcompile import compile_dsv  # noqa: E402

SRC_DIR = pathlib.Path(__file__).resolve().parent
DELIM = {".tsv": "\t", ".csv": ","}


def main() -> int:
    sources = sorted(SRC_DIR.glob("*.tsv")) + sorted(SRC_DIR.glob("*.csv"))
    if not sources:
        print(f"未在 {SRC_DIR} 找到 .tsv/.csv 源文件", file=sys.stderr)
        return 1

    for src in sources:
        out = src.with_suffix(".pq")
        print(f"编译 {src.name} -> {out.name}", flush=True)
        with src.open("r", encoding="utf-8") as f:
            arr = compile_dsv(f, DELIM[src.suffix])
        ak.to_parquet(arr, out)
        print(f"  完成: {len(arr)} 行", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
