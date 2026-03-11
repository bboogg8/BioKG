# pubmed_enzyme_writer.py

def link_pub_enzyme(tx, pmid, enzyme_name, ec_list):
    """
    Publication (pmid) -> EC (ec number) -> Enzyme (ec)
    创建 Publication 节点（key: pmid）
    为每个 EC 编号创建 EC 节点（key: EC编号）
    EC 通过 CATALYZES 关系连接到图谱中已存在的 Enzyme 节点（key: ec）
    """
    tx.run(
        """
        MERGE (p:Publication {pmid: $pmid})
        FOREACH (ec IN $ecs |
            MERGE (ecnode:EC {name: $ename})
            MERGE (p)-[:INVOLVED_IN]->(ecnode)
            MERGE (enzyme:Enzyme {ec: ec})
            MERGE (ecnode)-[:CATALYZES]->(enzyme)
        )
        """,
        pmid=pmid,
        ename=enzyme_name,
        ecs=ec_list
    )
