#!/usr/bin/env python3
"""把 GitHub 仓库 parquets 分支的 .pq 同步到目标目录。

这是“先当子模块、再当独立仓库”的兼容层：tianzi 把本仓库挂载到
lexloader/lexicons/ 后，运行此脚本即可把编译产物（.pq）拉进工作区，
供 lexloader 运行时加载（运行时只读 .pq，其余文件会被忽略）。

用法:
    python tools/sync-parquets.py <仓库URL> [目标目录]

目标目录默认是当前工作目录；无第三方依赖，需要 git 与网络。
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo_url", help="lexicons 仓库地址，如 https://github.com/<owner>/lexicons.git")
    ap.add_argument("target", nargs="?", default=".", help="目标目录（默认当前目录）")
    args = ap.parse_args()

    target = pathlib.Path(args.target).resolve()
    target.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lex-parquets-") as tmp:
        print(f"拉取 parquets 分支: {args.repo_url}")
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", "parquets", args.repo_url, tmp],
            check=True,
        )
        pqs = sorted(pathlib.Path(tmp).glob("*.pq"))
        if not pqs:
            print("parquets 分支上没有 .pq，仓库可能还没跑过编译。", file=sys.stderr)
            return 1
        for pq in pqs:
            shutil.copy2(pq, target / pq.name)
        print(f"已同步 {len(pqs)} 个 .pq 到 {target}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
