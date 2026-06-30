# codegraph-gov

> 一个挂在 [CodeGraph](https://github.com/colbymchenry/codegraph) 索引旁边的**复用治理层（reuse-governance）**：在你动手写一个新函数 / 类 / 工具**之前**，先替你回答一个问题——*"代码库里是不是已经有等价实现了？"*

中文 | [English](README.en.md)

它把**关键词检索**（CodeGraph 的 SQLite FTS5）和**本地语义检索**（ONNX 向量，不出网）用 RRF 融合，所以连"同义但换了名字"的符号也能找出来——这正是纯关键词搜索会漏掉的。它还以 MCP 工具的形式暴露能力，让 AI 编码 agent 在写新代码前**自动**先查一遍有没有现成的。

> 只读：codegraph-gov 从不写入 CodeGraph 的数据库。

---

## 一、关于上游 CodeGraph（本项目的地基）

本项目构建在 **CodeGraph**（npm 包 `@colbymchenry/codegraph`，MIT）之上。CodeGraph 是一个面向 AI 编码 agent 的**本地代码智能（local-first code intelligence）**工具，以 MCP 服务形式提供：

- 它用 **tree-sitter** 解析你的代码库，预先建好一张**知识图谱（knowledge graph）**——符号、调用关系、代码结构——存进项目根目录的 `.codegraph/codegraph.db`。
- AI agent 直接**查这张图**，而不是一遍遍 grep / glob / 读文件，因此**更省 token、更少工具调用、100% 本地**（官方基准：平均省约 16% 成本、约 47% token、约 58% 工具调用）。
- 支持 TypeScript / Python / Rust / Java / Go / Swift 等多语言；支持 Claude Code / Cursor / Codex / opencode / Gemini 等多种 agent。
- 项目地址：**https://github.com/colbymchenry/codegraph** ｜ 文档站：https://colbymchenry.github.io/codegraph/ ｜ npm：`@colbymchenry/codegraph`

建索引（CodeGraph 侧，一次性）：

```bash
cd your-project
codegraph init -i      # 创建 .codegraph/ 并建好初始图谱（之后用 codegraph index 增量更新）
```

---

## 二、本项目与 CodeGraph 的关系

| 维度 | CodeGraph（上游） | codegraph-gov（本项目） |
| --- | --- | --- |
| 职责 | 把代码库**变成**一张可查询的符号图谱 | 在这张图谱**之上**做"写代码之前的复用治理" |
| 先后 | **先**建好 `codegraph.db` | 在它**之上**工作，**只读**，从不写 |
| 流程位置 | 索引层 | **动笔之前**的那道复用闸（reuse-first） |

一句话：**CodeGraph 是地基（索引）；codegraph-gov 是地基之上、动笔之前的那道复用检查。** 它不替代 CodeGraph，而是站在它产出的索引上，专门解决"重复造轮子"这一件事。

---

## 三、能做什么

| 命令 | 作用 |
| --- | --- |
| `codegraph_reuse_candidates(intent)`（MCP 工具） | 按"意图"返回排好序的现有可复用符号，带 `文件:行号`、签名、调用方数量、跨仓库分布 |
| `python -m cg_gov.cli reuse <intent>` | 同上，命令行版 |
| `python -m cg_gov.cli search <intent>` | 只跑语义检索 |
| `python -m cg_gov.cli gate <intent>` | 把 FTS 与语义两路结果并排对照 |
| `python -m cg_gov.cli scan` | 全库扫描：语义近重复的符号簇（重复造的轮子）+ 零调用方的孤儿符号 |
| `python -m cg_gov.cli gen-docs` | 生成可浏览的接口目录（JSON + markdown） |
| `python -m cg_gov.cli perception-scan` | *（可选）* 轮询 Gitea，发现新增的数据库 schema 字段 |

---

## 四、本项目的优势

- **找得到"换了名字的等价实现"。** 纯关键词搜索看不出 `formatFileSize` 和 `bytesToHuman` 是同一件事；codegraph-gov 把 FTS（关键词）和本地语义向量用 **RRF（Reciprocal Rank Fusion，倒数排名融合）**合在一起，语义相近的也能浮上来。
- **100% 本地、默认不出网。** 默认用本地 ONNX 嵌入模型（fastembed），不需要任何 API key，也不会把你的代码发到外部。
- **只读、不污染。** 从不写 CodeGraph 的库；并自动剔除**非规范路径**——worktree 分支副本、vendored 第三方目录、AI 工具镜像目录（`.claude/`、`.cursor/` 等）、测试文件——避免这些重复/镜像符号盖过真正的源。
- **不止"写前查"，还能"主动扫"。** `scan` 一次性扫出整库里语义近重复的符号簇和零调用方的孤儿符号，把"已经重复了"的存量也揪出来。
- **可被 AI agent 自动调用。** 暴露 MCP 工具 `codegraph_reuse_candidates`，让 agent 在写任何可复用符号前**自动**先查一遍。
- **附带接口目录 + 可选 schema 感知。** `gen-docs` 生成可浏览的接口目录；`perception-scan` 可选地轮询 Gitea 上新增的数据库字段。
- **配置全靠环境变量、开箱即跑。** 所有部署相关路径都走 env 变量并带通用默认值，clone 下来即可导入运行。

---

## 五、实现方法（原理）

```
CodeGraph 建好的 codegraph.db（符号图谱，只读）
        │
        ▼
  extract  ── 读出可复用类型的符号(函数/方法/类/接口/类型/结构体/枚举)
        │     经 canonical 过滤掉非规范路径(worktree/vendored/AI镜像/测试)
        ▼
  index    ── 把每个符号的「名字+签名+docstring」用本地 ONNX 模型嵌入
        │     成向量, 存 emb.npy + meta.json
        ▼
  reuse    ── 对一个「意图」同时跑两路检索:
        │       · FTS    (CodeGraph 的 bm25 关键词)
        │       · semantic(本地向量余弦相似)
        │     再用 RRF 融合两个排名, top-k 补上调用方数量 + 跨仓库分布
        ▼
   排好序的复用候选(命中→直接复用, 没有→才新建)
```

- **canonical**：决定哪些路径算"规范真源"。worktree 副本、vendored 目录、AI 工具镜像目录、测试一律剔除——否则镜像符号会在检索里盖过真正的源。
- **fuse（RRF）**：`score(id) = Σ 1 / (60 + rank)`，对两路排名各自取倒数排名相加，无需两路分数可比即可融合。
- **perception（可选）**：纯函数式解析新旧 `.sql`，diff 出"新增表 / 新增字段"，产出结构化变更流；网络轮询走标准库 `urllib`，传输层可注入，测试零网络。

---

## 六、要求

- Python 3.10+
- 一个由上游 **CodeGraph** 建好的 `codegraph.db` 索引。codegraph-gov 只读它，**不负责构建**（构建见上面第一节 `codegraph init -i`）。

## 七、安装

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## 八、配置

所有部署相关路径都是环境变量（见 `.env.example`）：

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `CODEGRAPH_WORKSPACE_ROOT` | `~/workspace` | CodeGraph 扫描的代码根目录 |
| `CODEGRAPH_DB_PATH` | `$CODEGRAPH_WORKSPACE_ROOT/.codegraph/codegraph.db` | 只读的 codegraph 索引 |
| `CODEGRAPH_BLACKLIST_ROOTS` | *(空)* | 逗号分隔的顶层目录名，当作 vendored 剔除 |
| `CODEGRAPH_DOCS_MARKDOWN_OUT` | `docs/interface_catalog.md` | `gen-docs` 输出 markdown 的位置 |
| `CODEGRAPH_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | 本地 fastembed 模型；切换后必须重建 index 并重启 MCP |
| `CODEGRAPH_QUERY_EXPANSION` | `1` | 是否启用查询扩展 |
| `CODEGRAPH_QUERY_ALIASES_JSON` / `CODEGRAPH_QUERY_ALIASES_FILE` | *(空)* | 业务词到工程词的别名表(JSON object) |
| `CODEGRAPH_DOC_HINT_ROOTS` | *(空)* | 冒号分隔的 markdown 文档根目录，只做低权重 query hint |
| `CODEGRAPH_DOC_HINT_MAX_AGE_DAYS` | `30` | 文档 hint 的新鲜度阈值，超期自动降权 |
| `CODEGRAPH_DOC_HINTS` | `1` | 是否启用文档 hint |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | *(未设)* | 仅当你切换到 API 嵌入器时才需要 |
| `GITEA_HOST` / `GITEA_OWNER` / `GITEA_TOKEN` | 示例值 | 仅 `perception-scan` 需要 |

按项目切分的接口文档配置在 `projects.json`（可复制 `projects.example.json` 起步）。

### 查询扩展: 中文 / 业务词 → 工程词

`reuse` 会先保留原始意图,再自动生成若干扩展 query,最后用加权 RRF 融合:

1. 原始 FTS + 原始语义检索。
2. 内置少量常见别名,以及你通过 `CODEGRAPH_QUERY_ALIASES_JSON` / `CODEGRAPH_QUERY_ALIASES_FILE` 配置的业务词典。
3. 可选 markdown 文档 hint: 从包含业务词的文档行里抽取反引号中的代码标识符。文档只做低权重提示,最终答案仍落回 codegraph 符号 / schema 文件。

例:

```bash
export CODEGRAPH_QUERY_ALIASES_JSON='{"达人专属池":["dedicated_user_id","managed_strategy_group","managed_dedicated_assignment"]}'
python -m cg_gov.cli reuse "查一下达人专属池和内容池路由"
```

如需用多语言 embedding,可设置 `CODEGRAPH_EMBED_MODEL` 后重建:

```bash
export CODEGRAPH_EMBED_MODEL=BAAI/bge-m3
python -m cg_gov.cli index
```

长驻 MCP 进程会缓存模型和索引,重建后请重启 agent / MCP server。

## 九、用法

```bash
# 1. 在 CodeGraph 的符号上建本地语义索引(首次会下载嵌入模型)
python -m cg_gov.cli index

# 2. 问"这件事是不是已经有现成实现了"
python -m cg_gov.cli reuse "format a byte count into a human readable string"

# 3. 扫描重复实现
python -m cg_gov.cli scan --reimpl-only
```

### 作为 MCP 服务

```json
{
  "mcpServers": {
    "codegraph-gov": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "cg_gov.mcp_server"],
      "env": { "CODEGRAPH_WORKSPACE_ROOT": "/path/to/your/workspace" }
    }
  }
}
```

## 十、测试

```bash
pip install -e ".[test]"
pytest
```

测试是封闭的：覆盖融合(RRF)、FTS 预处理、规范路径过滤、SQL schema 变更解析、余弦排序、Gitea 客户端(注入假传输层)——**零网络、零模型、不需要 codegraph 索引**即可全部跑过。

## 十一、嵌入器（embedding provider）

`embed.py` 内置两种：`LocalFastembed`（默认，ONNX，离线）和 `ApiEmbed`（OpenAI 兼容，需要 `OPENAI_API_KEY`）。

## 十二、许可证

Apache-2.0，见 [LICENSE](LICENSE)。CodeGraph 本身为其作者所有，许可证以其[官方仓库](https://github.com/colbymchenry/codegraph)为准。
