from neo4j_utils.neo4j_conn import get_driver

driver = get_driver()
with driver.session() as s:
    r = s.run("MATCH (e:Enzyme {ec:'1.1.1.27'}) RETURN e, labels(e) as l")
    print(list(r))
driver.close()
