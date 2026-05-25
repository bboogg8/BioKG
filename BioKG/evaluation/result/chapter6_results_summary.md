# Chapter 6 Experiment Results

The following tables are transcribed from Chapter 6 of `毕业论文.md`.

## Table 6-1 NER Performance Comparison Test Results

| 实体类型 | 方法 | TP | FP | FN | 精确率 P | 召回率 R | F1值 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Enzyme/Gene | 规则匹配 | 156 | 42 | 68 | 78.8% | 69.6% | 73.9% |
| Enzyme/Gene | ScispaCy NER | 203 | 19 | 21 | 91.4% | 90.6% | 91.0% |
| Compound | 规则匹配 | 89 | 35 | 52 | 71.8% | 63.1% | 67.2% |
| Compound | ScispaCy NER | 138 | 22 | 34 | 86.3% | 80.2% | 83.1% |
| Pathway | 规则匹配 | 64 | 28 | 39 | 69.6% | 62.1% | 65.6% |
| Pathway | ScispaCy NER | 97 | 14 | 21 | 87.4% | 82.2% | 84.7% |
| Protein | 规则匹配 | 112 | 51 | 60 | 68.7% | 65.1% | 66.9% |
| Protein | ScispaCy NER | 178 | 23 | 28 | 88.6% | 86.4% | 87.5% |
| 加权平均 | 规则匹配 | — | — | — | 72.8% | 65.1% | 68.8% |
| 加权平均 | ScispaCy NER | — | — | — | 89.0% | 85.5% | 87.2% |

## Table 6-2 Comparative Experiment on the Credibility of Graph-RAG vs. Native LLM Q&A

| 评估维度 | 评测指标 | 原生LLM | Graph-RAG | 提升幅度 |
| --- | --- | --- | --- | --- |
| 事实准确性 | 答案正确率 | 61.3% | 88.7% | +27.4pp |
| 事实准确性 | EC编号命中率 | 54.2% | 94.1% | +39.9pp |
| 幻觉抑制 | 幻觉率(人工标注) | 38.6% | 8.2% | -30.4pp |
| 知识溯源 | 答案可溯源率 | 0% | 93.5% | +93.5pp |
| 知识溯源 | PMID引用准确率 | — | 91.8% | N/A |
| 语言流畅度 | BLEU-4 | 0.312 | 0.358 | +14.7% |
| 综合得分 | RAGAS Score | 0.41 | 0.79 | +92.7% |

## Table 6-3 Response Performance Test Results for Various Graph Retrieval Operations

| 查询类型 | 典型Cypher模式 | 平均响应时间 | P95延迟 | 吞吐量(QPS) |
| --- | --- | --- | --- | --- |
| 单节点属性查询 | MATCH (e) WHERE ... RETURN e | 12 ms | 21 ms | 83.3 |
| 1跳关系查询 | MATCH (e)-[r]->(n) RETURN ... | 28 ms | 47 ms | 35.7 |
| 2跳多关系查询 | MATCH (e)-[*2]->(n) RETURN ... | 85 ms | 143 ms | 11.8 |
| 通路-酶聚合查询 | MATCH (p)-[:HAS_ENZYME]->(e) | 124 ms | 198 ms | 8.1 |
| 文献全文索引查询 | MATCH (pub) WHERE contains... | 67 ms | 110 ms | 14.9 |
| Graph-RAG完整链路 | 图检索+LLM推理(DeepSeek) | 4.8 s | 7.2 s | 0.21 |
