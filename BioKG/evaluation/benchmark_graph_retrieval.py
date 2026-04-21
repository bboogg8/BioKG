from __future__ import annotations

import argparse
from pathlib import Path

from chapter6_common import (
    RESULTS_DIR,
    ensure_dirs,
    markdown_table,
    measure_runtime,
    summarize_latency,
    write_csv,
)

try:
    from BioKG.neo4j_utils.neo4j_conn import get_driver
except ModuleNotFoundError:
    from neo4j_utils.neo4j_conn import get_driver

from evaluate_qa_trustworthiness import build_graph_rag_prompt
from generate_qa_testset import build_dataset
from chapter6_common import call_ollama


DEFAULT_OUTPUT = RESULTS_DIR / "table6_3_graph_latency.csv"


def prepare_targets() -> dict[str, str]:
    driver = get_driver()
    try:
        with driver.session() as session:
            ec = session.run(
                """
                MATCH (e:Enzyme)<-[:HAS_EC]-(:Protein)
                RETURN e.ec AS ec
                LIMIT 1
                """
            ).single()["ec"]
            keyword = session.run(
                """
                MATCH (pub:Publication)
                RETURN split(toLower(coalesce(pub.abstract, "")), " ")[10] AS keyword
                LIMIT 1
                """
            ).single()["keyword"]
            return {"ec": str(ec), "keyword": str(keyword or "glycolysis")}
    finally:
        driver.close()


def run_benchmark(repetitions: int, full_chain_repetitions: int, model_name: str) -> list[dict[str, str]]:
    targets = prepare_targets()
    driver = get_driver()
    try:
        with driver.session() as session:
            def single_node_query():
                list(
                    session.run(
                        "MATCH (e:Enzyme {ec: $ec}) RETURN e.ec AS ec, e.id AS enzyme_id, e.name AS name",
                        ec=targets["ec"],
                    )
                )

            def one_hop_query():
                list(
                    session.run(
                        """
                        MATCH (e:Enzyme {ec: $ec})-[r]-(n)
                        RETURN type(r) AS rel_type, count(n) AS neighbor_count
                        """,
                        ec=targets["ec"],
                    )
                )

            def two_hop_query():
                list(
                    session.run(
                        """
                        MATCH (e:Enzyme {ec: $ec})-[*1..2]-(n)
                        RETURN count(DISTINCT n) AS node_count
                        """,
                        ec=targets["ec"],
                    )
                )

            def pathway_aggregation_query():
                list(
                    session.run(
                        """
                        MATCH (p:Pathway)-[:HAS_ENZYME]->(e:Enzyme)
                        RETURN p.name AS pathway, count(DISTINCT e) AS enzyme_count
                        ORDER BY enzyme_count DESC
                        LIMIT 20
                        """
                    )
                )

            def publication_text_query():
                list(
                    session.run(
                        """
                        MATCH (pub:Publication)
                        WHERE toLower(coalesce(pub.abstract, "")) CONTAINS toLower($keyword)
                        RETURN count(pub) AS publication_count
                        """,
                        keyword=targets["keyword"],
                    )
                )

            samples = [
                (
                    "单节点属性查询",
                    "MATCH (e) WHERE e.ec = ... RETURN e",
                    measure_runtime(single_node_query, repetitions),
                ),
                (
                    "1跳关系查询",
                    "MATCH (e)-[r]-(n) RETURN ...",
                    measure_runtime(one_hop_query, repetitions),
                ),
                (
                    "2跳多关系查询",
                    "MATCH (e)-[*1..2]-(n) RETURN ...",
                    measure_runtime(two_hop_query, repetitions),
                ),
                (
                    "通路-酶聚合查询",
                    "MATCH (p)-[:HAS_ENZYME]->(e)",
                    measure_runtime(pathway_aggregation_query, repetitions),
                ),
                (
                    "文献全文索引查询",
                    "MATCH (pub) WHERE contains(...)",
                    measure_runtime(publication_text_query, repetitions),
                ),
            ]
    finally:
        driver.close()

    graph_rag_record = build_dataset(seed=7, ec_count=1, pathway_count=0, compound_count=0)[0]

    def graph_rag_full_chain():
        prompt = build_graph_rag_prompt(graph_rag_record)
        call_ollama(prompt, model_name=model_name, num_predict=140, temperature=0.1, timeout=180)

    samples.append(
        (
            "Graph-RAG完整链路",
            "图检索 + LLM推理(DeepSeek)",
            measure_runtime(graph_rag_full_chain, full_chain_repetitions),
        )
    )

    rows = []
    for query_type, cypher, latencies in samples:
        summary = summarize_latency(latencies)
        mean_ms = summary["mean_ms"]
        p95_ms = summary["p95_ms"]
        qps = summary["qps"]
        if mean_ms >= 1000:
            mean_str = f"{mean_ms / 1000:.2f} s"
            p95_str = f"{p95_ms / 1000:.2f} s"
        else:
            mean_str = f"{mean_ms:.0f} ms"
            p95_str = f"{p95_ms:.0f} ms"
        rows.append(
            {
                "query_type": query_type,
                "cypher_pattern": cypher,
                "mean_latency": mean_str,
                "p95_latency": p95_str,
                "qps": f"{qps:.2f}",
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="运行第六章图检索响应性能基准测试。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repetitions", type=int, default=300)
    parser.add_argument("--full-chain-repetitions", type=int, default=20)
    parser.add_argument("--model", type=str, default="deepseek-r1:7b")
    args = parser.parse_args()

    ensure_dirs()
    rows = run_benchmark(args.repetitions, args.full_chain_repetitions, args.model)
    write_csv(args.output, rows, ["query_type", "cypher_pattern", "mean_latency", "p95_latency", "qps"])

    print(f"Latency table -> {args.output}")
    print(
        markdown_table(
            rows,
            [
                ("query_type", "查询类型"),
                ("cypher_pattern", "典型Cypher模式"),
                ("mean_latency", "平均响应时间"),
                ("p95_latency", "P95延迟"),
                ("qps", "吞吐量(QPS)"),
            ],
        )
    )


if __name__ == "__main__":
    main()
