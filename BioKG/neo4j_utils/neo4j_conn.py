# -*- coding: utf-8 -*-
# neo4j_conn.py
from neo4j import GraphDatabase

try:
    from BioKG.config.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
except ModuleNotFoundError:
    from config.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

def get_driver():
    """
    Get Neo4j Driver (globally unique)
    """
    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASSWORD)
    )
    return driver


# ===========================
# Test
# ===========================
if __name__ == "__main__":
    driver = get_driver()
    with driver.session() as session:
        result = session.run("RETURN 1 AS test")
        print(result.single()["test"])
    driver.close()
