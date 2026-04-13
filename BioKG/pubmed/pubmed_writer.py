def write_publication(tx, pmid, abstract):
    # 增加更新时间，体现“动态流水线”
    tx.run("""
        MERGE (p:Publication {pmid: $pmid})
        SET p.abstract = $abstract,
            p.last_updated = datetime()
    """, pmid=pmid, abstract=abstract)

def link_pub_ec(tx, pmid, entity_info):
    """
    entity_info 包含: id (EC号), mention (原文词汇), confidence (置信度)
    """
    tx.run("""
        MATCH (p:Publication {pmid: $pmid})
        MATCH (e:Enzyme {ec: $ec})
        MERGE (p)-[r:MENTIONS_EC]->(e)
        ON CREATE SET 
            r.confidence = $conf,
            r.mention = $mention,
            r.method = "Scispacy_NER",
            r.found_date = date()
        ON MATCH SET
            r.last_seen = date() 
    """, 
    pmid=pmid, 
    ec=entity_info['id'], 
    conf=entity_info['confidence'],
    mention=entity_info['mention'])
