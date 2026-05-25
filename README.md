# BioKG

BioKG 是一个面向生物医学知识整合、图谱检索和循证问答的知识图谱系统。项目从 KEGG 构建通路、酶和化合物等结构化知识，从 PubMed 增量接入文献摘要，通过 SciSpacy 与同义词匹配完成实体识别和 EC 编号对齐，最终将数据写入 Neo4j，并在此基础上提供本地 Ollama 驱动的 Graph-RAG 问答和 Streamlit 可视化工作台。

## 功能概览

- KEGG 图谱构建：抓取指定物种的 pathway，解析 `Enzyme` 与 `Compound`，写入 Neo4j。
- PubMed 增量更新：按关键词检索文献，跳过已存在 PMID，补充 `Publication` 节点和文献证据关系。
- 实体识别与链接：使用 SciSpacy 识别基因/蛋白实体，并结合 Neo4j 中的 Protein/EC 同义词表链接到 `Enzyme`。
- 图数据库存储：以 `Pathway`、`Enzyme`、`Compound`、`Protein`、`Publication` 等节点组织知识。
- Graph-RAG 问答：从 Neo4j 检索通路、蛋白、化合物和 PMID 证据，再调用本地 Ollama 模型生成可追溯回答。
- Streamlit 工作台：支持知识查询、文献检索、两跳子图可视化、RAG 报告、数据统计和 PubMed 更新。
- 第六章实验复现：`BioKG/evaluation` 已按表6-1、表6-2、表6-3拆分为三个独立实验目录。

## 项目结构

```text
.
├── requirements.txt               # Python 依赖
├── README.md
├── BioKG/
│   ├── app.py                     # Streamlit UI 入口
│   ├── main.py                    # CLI 入口
│   ├── config/                    # KEGG、Neo4j、PubMed 配置
│   ├── data/                      # 本地数据和字典
│   ├── kegg/                      # KEGG API 调用与 pathway 解析
│   ├── pubmed/                    # PubMed 检索、解析、NER、写入
│   ├── neo4j_utils/               # Neo4j 连接与写入工具
│   ├── pipeline/                  # KEGG 构建与 PubMed 增量流水线
│   ├── RAG/                       # 图谱检索与 Ollama 生成
│   ├── tests/                     # 轻量连接和写入检查
│   └── evaluation/                # 第六章实验代码
│       ├── 6-1/                   # NER 性能对比实验
│       ├── 6-2/                   # Graph-RAG 问答可信度实验
│       └── 6-3/                   # 图检索响应性能实验
```

## 环境要求

- Python 3.10+。
- Neo4j，本项目默认连接 `neo4j://127.0.0.1:7687`。
- Ollama，用于 Graph-RAG 生成，默认模型为 `deepseek-r1:7b`。
- KEGG REST 与 PubMed E-utilities 网络访问。
- 可选：Graphviz 命令行工具，用于在 UI 中导出子图 PNG。

## 安装依赖

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`requirements.txt` 已包含 SciSpacy 模型安装地址。若模型下载失败，可单独安装：

```powershell
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bionlp13cg_md-0.5.4.tar.gz
```

准备默认 Ollama 模型：

```powershell
ollama pull deepseek-r1:7b
ollama run deepseek-r1:7b
```

## 配置

核心配置位于 `BioKG/config/config.py`：

```python
ORGANISM = "hsa"
NEO4J_URI = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345678"
PUBMED_TOOL_EMAIL = "your.email@example.com"
```

使用前建议修改：

- `NEO4J_PASSWORD`：改为本机 Neo4j 密码。
- `PUBMED_TOOL_EMAIL`：改为真实邮箱，便于符合 PubMed E-utilities 使用要求。
- `ORGANISM`：默认 `hsa`，如需其他 KEGG 物种可改为对应 organism code。

Streamlit UI 会优先读取以下环境变量覆盖 Neo4j 连接：

```powershell
$env:NEO4J_URI = "neo4j://127.0.0.1:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "your-password"
```

## 快速开始

所有命令建议从仓库根目录运行。

### 1. 检查 Neo4j 连接

```powershell
python BioKG\neo4j_utils\neo4j_conn.py
```

成功时会输出 `1`。

### 2. 构建 KEGG 初始图谱

```powershell
python BioKG\pipeline\build_kg.py
```

该命令会根据 `BioKG/config/config.py` 中的 `ORGANISM` 抓取 KEGG pathway，并写入 `Pathway`、`Enzyme`、`Compound` 及其关系。

### 3. 执行 PubMed 增量更新

```powershell
python BioKG\main.py --update
```

当前更新关键词和抓取数量位于 `BioKG/pipeline/update_pipeline.py`：

```python
QUERY = "glycolysis enzyme human"
RETMAX = 1000
```

更新流程会先从 Neo4j 构建 Protein/EC 同义词字典，再检索 PubMed、获取摘要、运行 NER，并写入 `Publication` 与 `MENTIONS_EC` 关系。

### 4. 查看图谱统计

```powershell
python BioKG\main.py --stats
```

### 5. 运行 Graph-RAG 问答

```powershell
python BioKG\main.py --ask "LDHA" --model "deepseek-r1:7b"
```

可输入基因名、蛋白名、Entry Name 或 EC 编号。回答质量取决于当前 Neo4j 中的图谱规模、文献更新情况和本地 Ollama 模型状态。

### 6. 启动 Streamlit 工作台

```powershell
streamlit run BioKG/app.py
```

工作台包含：

- 首页：查看图谱概览和推荐工作流。
- 知识查询：按酶、基因、EC 编号或通路检索结构化关系。
- 文献检索：在 `Publication` 标题和摘要中检索关键词。
- 图谱可视化：选择中心节点，展示一跳/二跳邻域，支持 PyVis 交互和 DOT/PNG 导出。
- RAG 问答：选择候选实体，生成带 PMID 证据的 Markdown 报告。
- 数据统计：查看节点类型、关系类型和文献趋势。
- 系统更新：从界面触发 PubMed 增量更新。

## 图谱模式

常见节点标签：

- `Pathway`
- `Enzyme`
- `Compound`
- `Protein`
- `Publication`

常见关系类型：

- `(Pathway)-[:HAS_ENZYME]->(Enzyme)`
- `(Pathway)-[:HAS_COMPOUND]->(Compound)`
- `(Protein)-[:HAS_EC]->(Enzyme)`
- `(Publication)-[:MENTIONS_EC]->(Enzyme)`

这些标签、属性和关系类型会被查询、更新流水线、RAG 检索和评估脚本共同使用。修改 Cypher 或写入逻辑时，应保持兼容，除非明确执行 schema 迁移。

## 第六章实验

实验代码位于 `BioKG/evaluation`，按论文表格拆分：

```text
BioKG/evaluation/
├── 6-1/
│   ├── build_gold_template_6_1.py
│   └── evaluate_table6_1_ner.py
├── 6-2/
│   ├── build_question_set_6_2.py
│   ├── run_qa_responses_6_2.py
│   └── score_table6_2_metrics.py
└── 6-3/
    └── benchmark_table6_3_graph_retrieval.py
```

用途：

- 表6-1：构建 NER 人工标注模板，并计算规则匹配与 SciSpacy NER 的 TP、FP、FN、Precision、Recall、F1。
- 表6-2：从图谱构建 100 题评测集，对比原生 LLM 与 Graph-RAG 的事实准确性、幻觉率、溯源率、BLEU-4 和 RAGAS 风格分数。
- 表6-3：对单节点查询、1跳查询、2跳查询、聚合查询、文献全文查询和 Graph-RAG 完整链路做延迟基准测试。

实验脚本依赖 Neo4j、Ollama、SciSpacy 和当前图谱数据。正式复现实验前，请先阅读各子目录的 `README.md`。

## 常用验证命令

```powershell
python BioKG\main.py --stats
python BioKG\main.py --ask "LDHA" --model "deepseek-r1:7b"
pytest BioKG\tests -q
streamlit run BioKG/app.py
```

如果 Neo4j、Ollama、SciSpacy 模型或网络服务未就绪，相关命令会失败。先确认本地服务状态，再判断是否为代码问题。

## 开发注意事项

- 从 `BioKG/app.py`、`BioKG/main.py`、`BioKG/pipeline/build_kg.py`、`BioKG/pipeline/update_pipeline.py` 可以快速理解主流程。
- 数据获取、解析、写入、RAG 生成和 UI 展示应尽量保持分层，不要把核心业务逻辑堆到 UI 中。
- 不要随意重命名 Neo4j 标签、属性键或关系类型，尤其是 `HAS_EC`、`HAS_ENZYME`、`HAS_COMPOUND`、`MENTIONS_EC`。
- `毕业论文.md` 和论文材料用于文档与展示，不是系统运行入口；除非任务明确要求，不应因为代码改动同步修改论文内容。
- `__pycache__`、生成结果和临时文件不应作为核心代码维护对象。
