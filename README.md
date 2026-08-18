# lexicons

填字（Tianzi）引擎的词库仓库。存放 csv/tsv 格式的词库源文件与编译器，
编译产物（parquet, `.pq`）由 GitHub Actions 生成并发布到 `parquets` 分支。

本仓库**首先是 tianzi 的一个子模块**（挂载在 `tianzi/lexloader/lexicons/`），
其次才是一个独立 GitHub 仓库。tianzi 的 lexloader 运行时只加载目录里的 `.pq`，
其余文件（源文件、编译器、脚本）都会被忽略，因此把整个仓库放在词库目录里
不会影响运行时。

## 布局

```
.                           # 仓库根目录 == tianzi/lexloader/lexicons/
├── .github/workflows/compile.yml   # CI：编译 + 发布 parquets 分支
├── compiler/                       # 编译器（从 lexloader 独立出来的扁平模块）
│   ├── pqcompile.py                # 主入口：compile_dsv()
│   ├── colproto.py
│   ├── headparser.py
│   └── typing_utils.py
├── tools/
│   └── sync-parquets.py            # 兼容层：把 parquets 分支的 .pq 拉到本地工作区
├── compile.py                      # 构建脚本：编译根目录下所有源文件
├── 词.tsv / 字.tsv / ...           # 词库源文件（main 分支只跟踪源）
└── requirements.txt
```

`.gitignore` 忽略 `*.pq`（编译产物）、`misc/`、`自定义.txt`（其他项目的词库
格式，后续由外部项目按 csv/tsv 流程迁移回来）。

## 本地编译

```bash
pip install -r requirements.txt
python compile.py          # 在仓库根目录生成 .pq
```

## CI 与 parquets 分支

`compile.yml` 在源文件/编译器变更时运行（也可手动触发）：

1. 用 Python 3.13 安装依赖
2. `python compile.py` 从 0 编译所有源文件
3. 把所有 `.pq` 以**干净快照**形式 force-push 到 `parquets` 分支
   （分支上只有 .pq，历史始终 1 个 commit，无旧文件残留）

### 下游（tianzi 部署侧）同步

```bash
# 在 tianzi/lexloader/lexicons/（子模块工作区）里：
python tools/sync-parquets.py https://github.com/<owner>/lexicons.git

# 等价于手动：
git clone --depth 1 --branch parquets https://github.com/<owner>/lexicons.git /tmp/lex-pq
cp /tmp/lex-pq/*.pq .
```

> 注意：parquets 分支每次 force-push，不要用 `git pull` 更新。

## 注意事项

- **拼音版本一致性**：`.pq` 里的拼音列是 `pinyinparser.Syllable` 的枚举值，
  编译端与下游运行端必须使用同一版本。requirements.txt 以全局 pip 环境实际
  安装版本为准（当前 `pinyinparser==1.4.0`）。已知 `1.3.0 -> 1.4.0` 会让所有
  拼音值偏移 +32，导致拼音查询全部错位。
- 编译器模块与 tianzi `lexloader/` 下的源码保持同步，修改时两边一起改。
- 首次 CI 产物会与历史遗留的 .pq 不同（旧版本编译器产物），属正常。
