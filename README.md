# lexicons

填字（Tianzi）引擎的词库仓库。存放 csv/tsv 格式的词库源文件，
编译产物（parquet, `.pq`）由 GitHub Actions 生成并发布到 `parquets` 分支。

本仓库**首先是 tianzi 的一个子模块**（挂载在 `tianzi/lexloader/lexicons/`），
其次才是一个独立 GitHub 仓库。tianzi 的 lexloader 运行时只加载目录里的 `.pq`，
其余文件（源文件、脚本）都会被忽略，因此把整个仓库放在词库目录里
不会影响运行时。

## 布局

```
.                           # 仓库根目录 == tianzi/lexloader/lexicons/
├── .github/workflows/compile.yml   # CI：拉取编译器 + 编译 + 发布 parquets 分支
├── tools/
│   └── sync-parquets.py            # 兼容层：把 parquets 分支的 .pq 拉到本地工作区
├── compile.py                      # 构建脚本：编译根目录下所有源文件
├── 词.tsv / 字.tsv / ...           # 词库源文件（main 分支只跟踪源）
└── requirements.txt
```

`.gitignore` 忽略 `*.pq`（编译产物）、`misc/`、`自定义.txt`（其他项目的词库
格式，后续由外部项目按 csv/tsv 流程迁移回来）。

## 编译器来源（实时引用，无副本）

编译模块（`pqcompile.py` / `colproto.py` / `headparser.py` / `typing_utils.py`）
**不随本仓库分发**，唯一权威副本在 tianzi 的 `lexloader/`，本仓库实时引用：

- **本地（tianzi 子模块上下文）**：`compile.py` 直接引用父目录 `lexloader/`
  下的文件，编辑 lexloader 立即生效，不存在副本过期问题。
- **CI**：workflow 浅克隆 tianzi 仓库的 `lexloader/` 后，通过
  `LEX_COMPILER_DIR` 指向它再编译。默认按公开仓库
  `https://github.com/WFLing-seaer/Tianzi.git` 拉取；若 tianzi 是私有仓库，
  在 lexicons 仓库的 Secrets 里加 `TIANZI_CLONE_URL`
  （形如 `https://<用户名>:<PAT>@github.com/WFLing-seaer/Tianzi.git`）。

> 因此 lexicons 的 CI 编译结果会随 tianzi 主线的编译器改动而变化（实时反映），
> 这是设计内行为；如需可复现的产物，可在 workflow 里把克隆改为钉住某个 ref。

## 本地编译

```bash
pip install -r requirements.txt
python compile.py          # 在仓库根目录生成 .pq
```

## CI 与 parquets 分支

`compile.yml` 在源文件/脚本变更时运行（也可手动触发）：

1. 用 Python 3.13 安装依赖
2. 从 tianzi 拉取编译器
3. `python compile.py` 从 0 编译所有源文件
4. 把所有 `.pq` 以**干净快照**形式 force-push 到 `parquets` 分支
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
- 首次 CI 产物会与历史遗留的 .pq 不同（旧版本编译器产物），属正常。
