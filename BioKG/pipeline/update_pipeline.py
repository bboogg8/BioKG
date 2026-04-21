# update_pipeline.py
# ==========================================
# PubMed → Neo4j 自动更新流水线（数据清洗+高质量对齐版）
# ==========================================

try:
    from BioKG.neo4j_utils.neo4j_conn import get_driver
    from BioKG.pubmed.pubmed_api import search_pubmed, fetch_abstract
    from BioKG.pubmed.pubmed_writer import write_publication
    from BioKG.pubmed.pubmed_parser import PubMedParser
except ModuleNotFoundError:
    from neo4j_utils.neo4j_conn import get_driver
    from pubmed.pubmed_api import search_pubmed, fetch_abstract
    from pubmed.pubmed_writer import write_publication
    from pubmed.pubmed_parser import PubMedParser
import datetime

# 配置参数
QUERY = "glycolysis enzyme human"
RETMAX = 1000  # 每次获取最新的10篇

def build_dynamic_dict(driver):
    """
    从 Neo4j 动态构建同义词映射表：利用 Entry Name, Gene Names, Protein names
    """
    syn_map = {}
    with driver.session() as session:
        print("正在从数据库加载 UniProt 同义词字典...")
        # 属性名包含空格，使用反引号包裹
        result = session.run("""
            MATCH (p:Protein) 
            WHERE p.`EC number` IS NOT NULL
            RETURN p.`Entry Name` AS entry_name, 
                   p.`Gene Names` AS gene_names, 
                   p.`Protein names` AS protein_full_name,
                   p.`EC number` AS ec
        """)
        
        for record in result:
            ec = str(record['ec']).strip()
            names_to_extract = []
            
            # 1. Entry Name 处理 (如 D2HDH_HUMAN -> D2HDH)
            if record['entry_name']:
                full_entry = str(record['entry_name']).upper()
                names_to_extract.append(full_entry)
                if "_" in full_entry:
                    names_to_extract.append(full_entry.split("_")[0])
            
            # 2. Gene Names 处理 (空格分隔)
            if record['gene_names']:
                genes = str(record['gene_names']).upper().split()
                names_to_extract.extend(genes)
            
            # 3. Protein names 处理 (移除 EC 后缀)
            if record['protein_full_name']:
                full_name = str(record['protein_full_name']).upper().split("(EC")[0].strip()
                names_to_extract.append(full_name)

            for name in set(names_to_extract):
                if name:
                    syn_map[name] = ec
                    
    print(f"字典构建完成，共有 {len(syn_map)} 条语义映射规则")
    return syn_map

def check_if_pmid_exists(driver, pmid):
    """
    检查数据库中是否已存在该 PMID，实现增量更新的核心逻辑
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (p:Publication {pmid: $pmid}) 
            RETURN count(p) > 0 AS exists
        """, pmid=pmid)
        return result.single()["exists"]

def link_pub_ec_enhanced(tx, pmid, entity):
    """
    增强版写入函数：记录匹配方法和置信度
    """
    tx.run("""
        MATCH (p:Publication {pmid: $pmid})
        MATCH (e:Enzyme {ec: $ec})
        MERGE (p)-[r:MENTIONS_EC]->(e)
        ON CREATE SET 
            r.confidence = $conf,
            r.mention = $mention,
            r.method = $method,
            r.timestamp = datetime()
    """, pmid=pmid, ec=entity['id'], conf=entity['confidence'], 
         mention=entity['mention'], method=entity.get('method', 'Scispacy_NER'))

def run_pipeline():
    driver = get_driver()
    
    # 1. 初始化解析器（此时会加载最新构建的字典）
    syn_dict = build_dynamic_dict(driver)
    parser = PubMedParser(synonym_dict=syn_dict)

    print(f"流水线启动 | 关键词: {QUERY}")

    # 2. 检索最新的文献 ID (按发表日期排序)
    pmids = search_pubmed(QUERY, retmax=RETMAX)
    print(f"PubMed 返回了最新的 {len(pmids)} 篇文献 ID")

    new_count = 0
    skip_count = 0

    with driver.session() as session:
        for idx, pmid in enumerate(pmids, start=1):
            
            # --- 增量更新逻辑：跳过已处理的文献 ---
            if check_if_pmid_exists(driver, pmid):
                print(f"[{idx}/{len(pmids)}] PMID {pmid} 已存在，跳过...")
                skip_count += 1
                continue

            print(f"\n[{idx}/{len(pmids)}] 处理新文献 PMID: {pmid}")
            abstract = fetch_abstract(pmid)
            if not abstract:
                continue

            # 3. 写入新文献节点
            session.execute_write(write_publication, pmid, abstract)

            # 4. 智能 NER 解析 (包含噪音过滤与三级对齐)
            entities = parser.extract_entities_with_ner(abstract)
            
            # 5. 建立跨源关联并分类结果
            valid_links = 0
            found_methods = set()
            clean_candidates = []

            for ent in entities:
                if ent['id']:
                    session.execute_write(link_pub_ec_enhanced, pmid, ent)
                    valid_links += 1
                    found_methods.add(ent['method'])
                else:
                    # parser 已经过滤了 DOI 等噪声，这里剩下的都是潜在蛋白
                    clean_candidates.append(ent['mention'])

            new_count += 1
            method_str = f" [{', '.join(found_methods)}]" if found_methods else ""
            print(f"  成功建立 {valid_links} 条知识关联{method_str}")
            
            if clean_candidates:
                # 限制打印数量，保持日志整洁
                display_cand = clean_candidates[:5]
                more = f" ...等{len(clean_candidates)}个" if len(clean_candidates) > 5 else ""
                print(f"    识别到高质量候选实体: {', '.join(display_cand)}{more}")

    driver.close()
    print(f"\n 任务圆满完成！")
    print(f" 统计结果: 新增文献 {new_count} 篇，跳过重复 {skip_count} 篇。")

if __name__ == "__main__":
    run_pipeline()
