# pubmed_enzyme_ner.py
"""
基于蛋白 / 基因符号的轻量级酶识别（MVP）
"""

import re

# 常见糖酵解相关基因符号（你后面可以自动生成）
KNOWN_ENZYMES = [
    "HK1", "HK2",
    "PFKM", "PFKP",
    "ALDOA",
    "GAPDH",
    "PGK1",
    "ENO1",
    "PKM", "PKM2",
    "LDHA", "LDHB"
]


def extract_enzyme_names(text: str):
    """
    从 PubMed 摘要中识别酶/基因符号
    """
    found = set()
    text_upper = text.upper()

    for name in KNOWN_ENZYMES:
        # 使用单词边界，避免误匹配
        if re.search(rf"\b{name}\b", text_upper):
            found.add(name)

    return list(found)
