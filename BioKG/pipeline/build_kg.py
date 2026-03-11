# build_kg.py
"""
构建 KEGG 知识图谱（人类 hsa）
Pathway -> Enzyme
Pathway -> Compound
"""

from config.config import ORGANISM
from kegg.kegg_api import get_real_pathways, get_pathway_detail
from kegg.kegg_parser import parse_pathway
from neo4j_utils.neo4j_conn import get_driver


def build_kegg_graph(limit=None):
    """
    构建 KEGG 知识图谱
    :param limit: 仅构建前 N 条通路（用于测试）
    """

    driver = get_driver()

    pathways = get_real_pathways()
    if limit:
        pathways = pathways[:limit]

    print(f"开始构建 {ORGANISM} KEGG 图谱，共 {len(pathways)} 条通路")

    with driver.session() as session:
        for idx, pathway in enumerate(pathways, start=1):
            pid = pathway["id"]
            pname = pathway["name"]

            print(f"[{idx}/{len(pathways)}] 处理通路 {pid}")

            try:
                text = get_pathway_detail(pid)
            except Exception as e:
                print(f"  × 获取失败：{e}")
                continue

            enzymes, compounds = parse_pathway(text)

            # ========== 创建 Pathway ==========
            session.run(
                """
                MERGE (p:Pathway {id: $pid})
                SET p.name = $name,
                    p.organism = $org
                """,
                pid=pid,
                name=pname,
                org=ORGANISM
            )

            # ========== 创建 Enzyme 并建立关系 ==========
            for ec in enzymes:
                session.run(
                    """
                    MERGE (e:Enzyme {ec: $ec})
                    MERGE (p:Pathway {id: $pid})
                    MERGE (p)-[:HAS_ENZYME]->(e)
                    """,
                    ec=ec,
                    pid=pid
                )

            # ========== 创建 Compound 并建立关系 ==========
            for cid in compounds:
                session.run(
                    """
                    MERGE (c:Compound {id: $cid})
                    MERGE (p:Pathway {id: $pid})
                    MERGE (p)-[:HAS_COMPOUND]->(c)
                    """,
                    cid=cid,
                    pid=pid
                )

    driver.close()
    print("KEGG 图谱构建完成")


# ===========================
# 测试入口
# ===========================
if __name__ == "__main__":
    # ?? 测试阶段强烈建议 limit=5 或 10
    build_kegg_graph()
