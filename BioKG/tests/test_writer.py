from neo4j_utils.neo4j_conn import get_driver

def get_synonym_dict_from_neo4j(driver):
    with driver.session() as session:
        # 查询所有有 EC 编号的蛋白及其关联的名字
        result = session.run("""
            MATCH (p:Protein) 
            WHERE p.ec IS NOT NULL
            RETURN p.name as name, p.gene_name as gene, p.ec as ec
        """)
        
        syn_map = {}
        for record in result:
            ec = record['ec']
            # 将全名和基因名都映射到这个 EC
            if record['name']: syn_map[record['name'].upper()] = ec
            if record['gene']: syn_map[record['gene'].upper()] = ec
        return syn_map
