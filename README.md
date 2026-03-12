# BioKG: 基于多源数据融合的生物制造知识图谱构建

## 项目简介
BioKG 是一个基于多源数据融合的生物制造知识图谱，旨在整合和利用来自 KEGG 数据库和 PubMed 文献的生物医学信息。该系统通过构建和维护一个 Neo4j 知识图谱，并结合检索增强生成（RAG）技术，提供智能问答和知识探索功能。它特别关注酶、基因、疾病和化合物之间的关系，并通过增量更新管道保持知识图谱的及时性。

## 主要功能
-   **KEGG 知识图谱构建**: 从 KEGG 数据库中提取通路、酶、化合物等信息，构建初始知识图谱。
-   **PubMed 文献增量更新**: 定期从 PubMed 检索最新生物医学文献，并将其整合到知识图谱中。
-   **智能实体识别与链接**: 利用 SciSpacy 进行命名实体识别（NER），并采用三层匹配算法（精确、标准化、模糊匹配）将文献中提及的实体链接到知识图谱中的现有节点。
-   **Neo4j 图数据库**: 使用 Neo4j 存储和管理复杂的生物医学关系数据。
-   **检索增强生成 (RAG) 问答**: 结合 Neo4j 图谱检索和本地大语言模型（如 Ollama）进行智能问答，为用户提供基于证据的深度分析报告。
-   **模块化设计**: 清晰的目录结构，便于代码维护和功能扩展。

## 模块结构
项目采用模块化设计，主要目录结构如下：

-   `config/`: 存放项目配置文件，如数据库连接、API URL 等。
    -   `config.py`: 全局配置文件。
-   `data/`: 存放数据文件，例如酶字典。
    -   `enzyme_dict.py`: 酶相关字典数据。
-   `kegg/`: 负责 KEGG 数据获取和解析的模块。
    -   `kegg_api.py`: KEGG REST API 接口封装。
    -   `kegg_parser.py`: KEGG 通路数据解析逻辑。
-   `pubmed/`: 负责 PubMed 数据获取、解析和写入的模块。
    -   `pubmed_api.py`: PubMed E-utilities API 接口封装。
    -   `pubmed_parser.py`: PubMed 文献摘要的 NLP 解析、实体识别和链接逻辑。
    -   `pubmed_enzyme_ner.py`: 针对 PubMed 酶实体的 NER 辅助功能。
    -   `pubmed_enzyme_writer.py`: PubMed 酶实体写入逻辑。
    -   `pubmed_writer.py`: PubMed 文献相关节点和关系写入逻辑。
-   `neo4j_utils/`: Neo4j 数据库连接和写入操作的工具模块。
    -   `neo4j_conn.py`: Neo4j 驱动连接管理。
    -   `neo4j_writer.py`: Neo4j 节点和关系创建的通用函数。
-   `pipeline/`: 数据处理管道的编排模块。
    -   `build_kg.py`: 初始 KEGG 知识图谱构建脚本。
    -   `update_pipeline.py`: PubMed 增量更新管道逻辑。
-   `rag/`: 检索增强生成（RAG）问答引擎模块。
    -   `rag_engine.py`: 结合 Neo4j 检索和 Ollama LLM 的问答核心逻辑。
-   `tests/`: 存放单元测试和辅助测试脚本。
    -   `check_ec.py`: EC 号码检查工具。
    -   `test_conn.py`: Neo4j 连接测试。
    -   `test_writer.py`: Neo4j 写入功能测试。
-   `main.py`: 项目主入口，提供命令行界面。

## 安装指南

### 1. 克隆仓库
```bash
git clone https://github.com/bboogg8/BioKG.git
cd BioKG
```

### 2. Python 环境
建议使用 `conda` 或 `venv` 创建虚拟环境。
```bash
python -m venv .venv
.\.venv\Scripts\activate # Windows
source ./.venv/bin/activate # Linux/macOS
```

### 3. 安装 Python 依赖
```bash
pip install -r requirements.txt # 如果存在 requirements.txt
# 或者手动安装以下关键依赖：
pip install neo4j requests lxml spacy scispacy thefuzz rapidfuzz
```

### 4. 安装 SciSpacy 模型
`BioKG` 使用 `en_ner_bionlp13cg_md` 模型进行命名实体识别。
```bash
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bionlp13cg_md-0.5.4.tar.gz
```

### 5. Neo4j 数据库
-   安装并启动 [Neo4j Desktop](https://neo4j.com/download/neo4j-desktop/) 或 [Neo4j Community Server](https://neo4j.com/download-center/#community)。
-   确保 Neo4j 实例运行在 `neo4j://localhost:7687`。
-   在 `config/config.py` 中配置 Neo4j 的用户名和密码（默认为 `neo4j` 和 `12345678`）。

### 6. Ollama (用于 RAG 功能)
-   安装 [Ollama](https://ollama.com/) 并在本地运行。
-   拉取一个你喜欢的大语言模型，例如 `deepseek-r1:7b` (项目默认使用)。
    ```bash
    ollama run deepseek-r1:7b
    ```

## 使用方法

### 1. 构建初始 KEGG 知识图谱
首次运行或需要重建 KEGG 图谱时执行此命令。
```bash
python pipeline/build_kg.py
```

### 2. 运行 PubMed 增量更新管道
从 PubMed 获取最新文献并更新知识图谱。
```bash
python main.py --update
```

### 3. 查看知识图谱统计
查看 Neo4j 数据库中不同类型节点的数量分布。
```bash
python main.py --stats
```

### 4. 智能问答 (RAG)
查询特定酶的深度综述。系统将从 Neo4j 知识图谱中检索相关信息，并结合本地 Ollama 大模型生成回答。
```bash
python main.py --ask "LDHA"
# 你也可以指定不同的 Ollama 模型
python main.py --ask "LDHA" --model "llama2"
```

## 配置
所有核心配置项都位于 `config/config.py` 文件中，包括：
-   `KEGG_BASE_URL`
-   `ORGANISM` (例如: `hsa` 代表人类)
-   `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
-   `PUBMED_BASE_URL`, `PUBMED_ESEARCH_URL`, `PUBMED_EFETCH_URL`, `PUBMED_TOOL_EMAIL`

请根据你的实际环境修改这些配置。

## 贡献
欢迎提交问题和拉取请求！
