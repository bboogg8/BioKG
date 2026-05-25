# Table 6-1 NER Performance Comparison Test Results

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
