from neo4j_utils.neo4j_conn import get_driver

with get_driver().session() as session:
    result = session.run("RETURN 1 AS test")
    print(result.single()["test"])
