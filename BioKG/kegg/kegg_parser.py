# kegg_parser.py
"""
KEGG Pathway 文件解析
- 从 GENE 行提取 EC 编号
- 从 COMPOUND 行提取 Compound ID（Cxxxxx）
"""

import re


EC_PATTERN = re.compile(r"\[EC:([^\]]+)\]")
COMPOUND_PATTERN = re.compile(r"(C\d{5})")


def parse_pathway(text: str):
    """
    解析 KEGG pathway 原始文本，提取：
    - enzymes: EC 编号列表
    - compounds: KEGG Compound ID 列表
    """

    enzymes = set()
    compounds = set()

    in_compound_block = False

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()

        # ===== COMPOUND 区块 =====
        if line.startswith("COMPOUND"):
            in_compound_block = True
            compounds.update(COMPOUND_PATTERN.findall(line))

        elif in_compound_block and line.startswith(" "):
            compounds.update(COMPOUND_PATTERN.findall(line))

        else:
            in_compound_block = False

        # ===== 从 GENE 行提取 EC =====
        if "EC:" in line:
            match = EC_PATTERN.search(line)
            if match:
                ec_block = match.group(1)

                # 统一按 ; 和空格拆分
                for ec in re.split(r"[;\s]+", ec_block):
                    ec = ec.strip()
                    if ec:
                        enzymes.add(ec)

    return sorted(enzymes), sorted(compounds)


# ===========================
# 测试
# ===========================
if __name__ == "__main__":
    from config.config import TEST_PATHWAY
    from .kegg_api import get_pathway_detail

    text = get_pathway_detail(TEST_PATHWAY)
    enzymes, compounds = parse_pathway(text)

    print(f"测试通路：{TEST_PATHWAY}")
    print("Enzyme (EC) 数量：", len(enzymes))
    print("Compound 数量：", len(compounds))

    print("Enzyme 示例：", enzymes[:10])
    print("Compound 示例：", compounds[:10])
