# BioKG: Biomedical Knowledge Graph and Graph RAG System

BioKG 是一个面向生物医学知识整合与问答的知识图谱项目。系统从 KEGG 获取通路、酶和化合物等结构化信息，从 PubMed 增量获取文献摘要，并将解析后的实体与关系写入 Neo4j。基于图数据库中的结构化证据，项目还提供了本地 Ollama 模型驱动的 Graph RAG 问答能力，以及 Streamlit 交互式探索界面。

## 核心功能

- **KEGG 图谱构建**：抓取指定物种的 KEGG pathway，解析酶 EC 编号和化合物，并写入 Neo4j。
- **PubMed 增量更新**：按关键词检索最新 PubMed 文献，跳过已存在 PMID，并补充新的文献节点和实体关系。
- **实体识别与链接**：使用 SciSpacy 识别文献中的基因/蛋白相关实体，并结合动态同义词表、标准化匹配和模糊匹配链接到图谱中的酶节点。
- **Neo4j 图存储**：使用 `Pathway`、`Enzyme`、`Compound`、`Protein`、`Publication` 等节点及 `HAS_ENZYME`、`HAS_COMPOUND`、`HAS_EC`、`MENTIONS_EC` 等关系组织数据。
- **Graph RAG 问答**：从 Neo4j 检索通路、蛋白、文献证据和 PMID，再调用本地 Ollama 模型生成分析报告。
- **Streamlit UI**：提供知识查询、文献检索、两跳子图可视化、RAG 报告生成、图谱统计和数据更新入口。

## 项目结构

```text
.
├── app.py                         # Streamlit UI 入口
├── BioKG/
│   ├── main.py                    # CLI 入口
│   ├── config/                    # KEGG、Neo4j、PubMed 配置
│   ├── data/                      # 本地字典与 UniProt 数据文件
│   ├── kegg/                      # KEGG API 与 pathway 解析
│   ├── pubmed/                    # PubMed 检索、解析、NER、写入逻辑
│   ├── neo4j_utils/               # Neo4j 连接与写入工具
│   ├── pipeline/                  # 图谱构建与增量更新流水线
│   ├── RAG/                       # Graph RAG 检索与 Ollama 生成
│   ├── tests/                     # 连接和写入相关轻量测试
│   └── evaluation/                # 第六章实验与评估脚本
├── thesis_materials/              # 论文材料、图表脚本和生成资产
├── scripts/                       # 辅助脚本
└── skills/                        # 本地技能定义，不属于核心运行路径
```

## 环境要求

- Python 3.10+，当前代码在 Python 3.12 环境下也可运行。
- Neo4j，默认地址为 `neo4j://127.0.0.1:7687`。
- Ollama，用于 RAG 生成，默认模型为 `deepseek-r1:7b`。
- SciSpacy 模型 `en_ner_bionlp13cg_md`，用于 PubMed NER。
- 可访问 KEGG REST API 和 PubMed E-utilities。

> 当前仓库没有 `requirements.txt`，需要手动安装依赖。

## 安装

### 1. 创建虚拟环境

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. 安装 Python 依赖

```powershell
pip install neo4j requests pandas streamlit spacy scispacy thefuzz rapidfuzz
```

安装 SciSpacy NER 模型：

```powershell
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bionlp13cg_md-0.5.4.tar.gz
```

### 3. 配置 Neo4j

默认配置位于 `BioKG/config/config.py`：

```python
NEO4J_URI = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345678"
```

如果使用 Streamlit UI，也可以通过环境变量覆盖连接信息：

```powershell
$env:NEO4J_URI = "neo4j://127.0.0.1:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "your-password"
```

### 4. 配置 PubMed 邮箱

将 `BioKG/config/config.py` 中的邮箱替换为真实邮箱：

```python
PUBMED_TOOL_EMAIL = "your.email@example.com"
```

### 5. 准备 Ollama 模型

```powershell
ollama pull deepseek-r1:7b
ollama run deepseek-r1:7b
```

## 使用方法

所有命令建议从仓库根目录运行。

### 构建初始 KEGG 图谱

```powershell
python BioKG\pipeline\build_kg.py
```

该命令会根据 `BioKG/config/config.py` 中的 `ORGANISM` 抓取 KEGG pathway。默认值为 `hsa`。

### 运行 PubMed 增量更新

```powershell
python BioKG\main.py --update
```

当前增量检索关键词定义在 `BioKG/pipeline/update_pipeline.py`：

```python
QUERY = "glycolysis enzyme human"
RETMAX = 10
```

### 查看图谱统计

```powershell
python BioKG\main.py --stats
```

### 运行 Graph RAG 问答

```powershell
python BioKG\main.py --ask "LDHA" --model "deepseek-r1:7b"
```

也可以查询 EC 编号、蛋白 Entry Name 或基因名，具体命中效果取决于 Neo4j 中已写入的数据。

### 启动 Streamlit UI

```powershell
streamlit run app.py
```

UI 功能包括：

- 知识查询
- 文献检索
- 节点两跳子图可视化
- Graph RAG 分析报告生成
- 图谱统计
- PubMed 增量更新

## 验证

可根据改动范围选择窄范围检查：

```powershell
python BioKG\main.py --stats
python BioKG\main.py --ask "LDHA" --model "deepseek-r1:7b"
pytest BioKG\tests -q
streamlit run app.py
```

这些检查依赖本地 Neo4j、Ollama、SciSpacy 模型和网络访问。若相关服务未启动或依赖未安装，命令会失败。

## 配置项

主要配置集中在 `BioKG/config/config.py`：

- `KEGG_BASE_URL`
- `ORGANISM`
- `TEST_PATHWAY`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- `PUBMED_BASE_URL`
- `PUBMED_ESEARCH_URL`
- `PUBMED_EFETCH_URL`
- `PUBMED_TOOL_EMAIL`

## 图谱模式概览

常见节点：

- `Pathway`
- `Enzyme`
- `Compound`
- `Protein`
- `Publication`

常见关系：

- `(Pathway)-[:HAS_ENZYME]->(Enzyme)`
- `(Pathway)-[:HAS_COMPOUND]->(Compound)`
- `(Protein)-[:HAS_EC]->(Enzyme)`
- `(Publication)-[:MENTIONS_EC]->(Enzyme)`

修改 Cypher 或写入逻辑时，应保持标签名、属性名和关系类型兼容，避免破坏已有查询与 RAG 检索路径。

## 非核心材料

`thesis_materials/`、`scripts/` 和根目录下的论文草稿主要用于毕业论文写作、图表渲染和材料整理，不属于 BioKG 的核心运行路径。除非任务明确要求，不需要为运行系统修改这些文件。
