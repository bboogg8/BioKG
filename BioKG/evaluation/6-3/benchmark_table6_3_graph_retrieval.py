from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

import requests


EXPERIMENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPERIMENT_DIR.parents[2]
for candidate in (PROJECT_ROOT, PROJECT_ROOT / "BioKG"):
    text = str(candidate)
    if text not in sys.path:
        sys.path.insert(0, text)

try:
    from BioKG.neo4j_utils.neo4j_conn import get_driver
except ModuleNotFoundError:
    from neo4j_utils.neo4j_conn import get_driver


DEFAULT_SUMMARY = EXPERIMENT_DIR / "results" / "table6_3_graph_latency.csv"
DEFAULT_MARKDOWN = EXPERIMENT_DIR / "results" / "table6_3_graph_latency.md"
DEFAULT_RAW = EXPERIMENT_DIR / "results" / "table6_3_raw_samples.csv"
OLLAMA_URL = "http://localhost:11434/api/generate"


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I).strip()


def call_ollama(prompt: str, model: str, timeout: int) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 140},
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    response.raise_for_status()
    return strip_think_tags(response.json().get("response", ""))


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def summarize(samples_ms: list[float]) -> dict[str, float]:
    mean_ms = sum(samples_ms) / len(samples_ms) if samples_ms else 0.0
    p95_ms = percentile(samples_ms, 0.95)
    qps = 1000.0 / mean_ms if mean_ms else 0.0
    return {"mean_ms": mean_ms, "p95_ms": p95_ms, "qps": qps}


def format_latency(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.2f} s"
    return f"{ms:.0f} ms"


def measure(name: str, operation: Callable[[], Any], repetitions: int, warmup: int) -> list[dict[str, Any]]:
    for _ in range(warmup):
        operation()

    rows: list[dict[str, Any]] = []
    for index in range(1, repetitions + 1):
        start = time.perf_counter()
        operation()
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        rows.append({"query_type": name, "iteration": index, "latency_ms": f"{elapsed_ms:.4f}"})
    return rows


def prepare_targets() -> dict[str, str]:
    driver = get_driver()
    try:
        with driver.session() as session:
            ec_row = session.run(
                """
                MATCH (e:Enzyme)<-[:HAS_EC]-(:Protein)
                WHERE e.ec IS NOT NULL
                RETURN e.ec AS ec
                LIMIT 1
                """
            ).single()
            keyword_row = session.run(
                """
                MATCH (pub:Publication)
                WHERE pub.abstract IS NOT NULL
                WITH split(toLower(pub.abstract), " ") AS tokens
                UNWIND tokens AS token
                WITH trim(token) AS token
                WHERE size(token) >= 6
                RETURN token AS keyword
                LIMIT 1
                """
            ).single()

            if ec_row is None:
                raise RuntimeError("No Enzyme EC target found for benchmarking.")

            return {
                "ec": str(ec_row["ec"]),
                "keyword": str(keyword_row["keyword"]) if keyword_row else "glycolysis",
            }
    finally:
        driver.close()


def fetch_graph_rag_context(ec_number: str) -> dict[str, Any]:
    driver = get_driver()
    try:
        with driver.session() as session:
            row = session.run(
                """
                MATCH (e:Enzyme {ec: $ec})
                OPTIONAL MATCH (p:Protein)-[:HAS_EC]->(e)
                OPTIONAL MATCH (pathway:Pathway)-[:HAS_ENZYME]->(e)
                OPTIONAL MATCH (pub:Publication)-[:MENTIONS_EC]->(e)
                RETURN
                    e.ec AS ec,
                    coalesce(e.name, e.id, e.ec) AS enzyme_name,
                    collect(DISTINCT coalesce(p.`Gene Names (primary)`, p.Entry, p.`Entry Name`, p.`Protein names`))[0..5] AS proteins,
                    collect(DISTINCT pathway.name)[0..5] AS pathways,
                    collect(DISTINCT pub.pmid)[0..3] AS pmids
                """,
                ec=ec_number,
            ).single()
            if row is None:
                return {"ec": ec_number, "proteins": [], "pathways": [], "pmids": []}
            return {
                "ec": str(row["ec"]),
                "enzyme_name": str(row.get("enzyme_name") or ""),
                "proteins": [str(item) for item in row.get("proteins") or [] if item],
                "pathways": [str(item) for item in row.get("pathways") or [] if item],
                "pmids": [str(item) for item in row.get("pmids") or [] if item],
            }
    finally:
        driver.close()


def build_graph_rag_prompt(context: dict[str, Any]) -> str:
    return (
        "You are a biomedical Graph-RAG assistant. Use only the supplied graph evidence.\n"
        "Answer briefly and cite PMID values when available. Do not show chain-of-thought.\n\n"
        f"Question: EC 编号 {context['ec']} 对应哪些酶或蛋白？\n\n"
        "Graph evidence:\n"
        f"EC: {context['ec']}\n"
        f"Enzyme name: {context.get('enzyme_name', '')}\n"
        f"Proteins: {', '.join(context.get('proteins', []))}\n"
        f"Pathways: {', '.join(context.get('pathways', []))}\n"
        f"PMIDs: {', '.join(context.get('pmids', []))}\n\n"
        "Final answer:"
    )


def run_benchmark(repetitions: int, full_chain_repetitions: int, warmup: int, model: str, timeout: int) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    targets = prepare_targets()
    raw_rows: list[dict[str, Any]] = []

    driver = get_driver()
    try:
        with driver.session() as session:
            def single_node_query() -> None:
                list(
                    session.run(
                        """
                        MATCH (e:Enzyme {ec: $ec})
                        RETURN e.ec AS ec, e.id AS enzyme_id, e.name AS name
                        """,
                        ec=targets["ec"],
                    )
                )

            def one_hop_query() -> None:
                list(
                    session.run(
                        """
                        MATCH (e:Enzyme {ec: $ec})-[r]-(n)
                        RETURN type(r) AS rel_type, count(n) AS neighbor_count
                        """,
                        ec=targets["ec"],
                    )
                )

            def two_hop_query() -> None:
                list(
                    session.run(
                        """
                        MATCH (e:Enzyme {ec: $ec})-[*1..2]-(n)
                        RETURN count(DISTINCT n) AS node_count
                        """,
                        ec=targets["ec"],
                    )
                )

            def pathway_aggregation_query() -> None:
                list(
                    session.run(
                        """
                        MATCH (pathway:Pathway)-[:HAS_ENZYME]->(enzyme:Enzyme)
                        RETURN pathway.name AS pathway, count(DISTINCT enzyme) AS enzyme_count
                        ORDER BY enzyme_count DESC
                        LIMIT 20
                        """
                    )
                )

            def publication_text_query() -> None:
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

            operations: list[tuple[str, str, Callable[[], Any], int]] = [
                ("单节点属性查询", "MATCH (e) WHERE e.ec = ... RETURN e", single_node_query, repetitions),
                ("1跳关系查询", "MATCH (e)-[r]-(n) RETURN ...", one_hop_query, repetitions),
                ("2跳多关系查询", "MATCH (e)-[*1..2]-(n) RETURN ...", two_hop_query, repetitions),
                ("通路-酶聚合查询", "MATCH (p)-[:HAS_ENZYME]->(e)", pathway_aggregation_query, repetitions),
                ("文献全文索引查询", "MATCH (pub) WHERE contains(...)", publication_text_query, repetitions),
            ]

            for query_type, _, operation, count in operations:
                raw_rows.extend(measure(query_type, operation, count, warmup))
    finally:
        driver.close()

    context = fetch_graph_rag_context(targets["ec"])
    prompt = build_graph_rag_prompt(context)

    def graph_rag_full_chain() -> None:
        call_ollama(prompt, model, timeout)

    raw_rows.extend(measure("Graph-RAG完整链路", graph_rag_full_chain, full_chain_repetitions, min(warmup, 2)))

    cypher_by_type = {
        "单节点属性查询": "MATCH (e) WHERE e.ec = ... RETURN e",
        "1跳关系查询": "MATCH (e)-[r]-(n) RETURN ...",
        "2跳多关系查询": "MATCH (e)-[*1..2]-(n) RETURN ...",
        "通路-酶聚合查询": "MATCH (p)-[:HAS_ENZYME]->(e)",
        "文献全文索引查询": "MATCH (pub) WHERE contains(...)",
        "Graph-RAG完整链路": "图检索 + LLM推理(DeepSeek)",
    }

    summary_rows: list[dict[str, str]] = []
    for query_type in cypher_by_type:
        samples = [float(row["latency_ms"]) for row in raw_rows if row["query_type"] == query_type]
        stats = summarize(samples)
        summary_rows.append(
            {
                "query_type": query_type,
                "cypher_pattern": cypher_by_type[query_type],
                "mean_latency": format_latency(stats["mean_ms"]),
                "p95_latency": format_latency(stats["p95_ms"]),
                "qps": f"{stats['qps']:.2f}",
            }
        )

    return summary_rows, raw_rows


def markdown_table(rows: list[dict[str, str]]) -> str:
    headers = [
        ("query_type", "查询类型"),
        ("cypher_pattern", "典型Cypher模式"),
        ("mean_latency", "平均响应时间"),
        ("p95_latency", "P95延迟"),
        ("qps", "吞吐量(QPS)"),
    ]
    lines = [
        "| " + " | ".join(label for _, label in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row[key] for key, _ in headers) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Table 6-3 graph retrieval operations.")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--repetitions", type=int, default=300)
    parser.add_argument("--full-chain-repetitions", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--model", default="deepseek-r1:7b")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    summary_rows, raw_rows = run_benchmark(
        args.repetitions,
        args.full_chain_repetitions,
        args.warmup,
        args.model,
        args.timeout,
    )
    write_csv(args.summary, summary_rows, ["query_type", "cypher_pattern", "mean_latency", "p95_latency", "qps"])
    write_csv(args.raw, raw_rows, ["query_type", "iteration", "latency_ms"])
    write_text(args.markdown, markdown_table(summary_rows))
    print(f"Table 6-3 CSV: {args.summary}")
    print(f"Table 6-3 raw samples: {args.raw}")
    print(f"Table 6-3 Markdown: {args.markdown}")


if __name__ == "__main__":
    main()
