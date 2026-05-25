from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

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


DEFAULT_DATASET = EXPERIMENT_DIR / "data" / "qa_eval_100.jsonl"
DEFAULT_RESPONSES = EXPERIMENT_DIR / "results" / "qa_eval_responses.jsonl"
DEFAULT_REVIEW = EXPERIMENT_DIR / "results" / "manual_review_template.csv"
OLLAMA_URL = "http://localhost:11434/api/generate"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I).strip()


def call_ollama(prompt: str, model: str, timeout: int, num_predict: int) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": num_predict,
        },
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    response.raise_for_status()
    return strip_think_tags(response.json().get("response", ""))


def fetch_publication_context(pmids: list[str]) -> list[dict[str, str]]:
    if not pmids:
        return []

    driver = get_driver()
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (p:Publication)
                WHERE p.pmid IN $pmids
                RETURN p.pmid AS pmid, p.abstract AS abstract
                ORDER BY toInteger(p.pmid) DESC
                """,
                pmids=pmids,
            )
            return [
                {
                    "pmid": str(row["pmid"]),
                    "abstract": str(row.get("abstract") or "").replace("\n", " ").strip()[:500],
                }
                for row in rows
            ]
    finally:
        driver.close()


def graph_context_lines(record: dict[str, Any]) -> list[str]:
    gold = record["gold"]
    target = record["target"]
    lines = [f"Question type: {record['question_type']}"]

    for key, label in (
        ("ec_number", "Target EC number"),
        ("pathway_name", "Target pathway"),
        ("compound_id", "Target compound"),
    ):
        if key in target:
            lines.append(f"{label}: {target[key]}")

    for key, label in (
        ("entities", "Graph entities"),
        ("ec_numbers", "EC numbers"),
        ("pathways", "Pathways"),
        ("pmids", "Evidence PMIDs"),
        ("publication_titles", "Publication titles"),
    ):
        values = gold.get(key, [])
        if values:
            lines.append(f"{label}: {', '.join(values)}")

    for publication in fetch_publication_context(gold.get("pmids", [])):
        lines.append(f"[PMID: {publication['pmid']}] {publication['abstract']}")

    return lines


def build_native_prompt(record: dict[str, Any]) -> str:
    return (
        "You are a biomedical QA assistant.\n"
        "Answer the question directly. If uncertain, say you are uncertain.\n"
        "Do not show chain-of-thought.\n\n"
        f"Question: {record['question']}\n\n"
        "Answer:"
    )


def build_graph_rag_prompt(record: dict[str, Any]) -> str:
    context = "\n".join(graph_context_lines(record))
    return (
        "You are a biomedical Graph-RAG assistant.\n"
        "Use only the provided graph facts and publication evidence.\n"
        "Do not invent facts. Cite PMID evidence as [PMID: xxxxx] when available.\n"
        "Do not show chain-of-thought.\n\n"
        f"Question: {record['question']}\n\n"
        f"Graph and literature context:\n{context}\n\n"
        "Final answer:"
    )


def load_cache(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    for record in load_jsonl(path):
        cache[(record["question_id"], record["system_name"])] = record
    return cache


def answer_dataset(dataset: list[dict[str, Any]], responses_path: Path, model: str, timeout: int, limit: int | None) -> list[dict[str, Any]]:
    cache = load_cache(responses_path)
    output: list[dict[str, Any]] = []

    for record in dataset[: limit or len(dataset)]:
        for system_name, prompt_builder in (
            ("native_llm", build_native_prompt),
            ("graph_rag", build_graph_rag_prompt),
        ):
            key = (record["question_id"], system_name)
            if key in cache and str(cache[key].get("answer", "")).strip():
                answer = str(cache[key]["answer"])
            else:
                answer = call_ollama(prompt_builder(record), model, timeout, num_predict=220)
                cache[key] = {
                    "question_id": record["question_id"],
                    "question_type": record["question_type"],
                    "system_name": system_name,
                    "question": record["question"],
                    "target": record["target"],
                    "gold": record["gold"],
                    "reference_answer": record["reference_answer"],
                    "answer": answer,
                }
            output.append(cache[key])

    write_jsonl(responses_path, list(cache.values()))
    return output


def build_manual_review_template(responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in responses:
        rows.append(
            {
                "question_id": row["question_id"],
                "question_type": row["question_type"],
                "system_name": row["system_name"],
                "question": row["question"],
                "reference_answer": row["reference_answer"],
                "answer": row["answer"],
                "manual_answer_correct": "",
                "manual_hallucinated_claims": "",
                "manual_total_claims": "",
                "manual_traceable": "",
                "manual_pmid_correct": "",
                "manual_pmid_total": "",
                "manual_ragas_score": "",
                "manual_notes": "",
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate native LLM and Graph-RAG responses for Table 6-2.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--responses", type=Path, default=DEFAULT_RESPONSES)
    parser.add_argument("--manual-review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--model", default="deepseek-r1:7b")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    dataset = load_jsonl(args.dataset)
    responses = answer_dataset(dataset, args.responses, args.model, args.timeout, args.limit)
    review_rows = build_manual_review_template(responses)
    write_csv(
        args.manual_review,
        review_rows,
        [
            "question_id",
            "question_type",
            "system_name",
            "question",
            "reference_answer",
            "answer",
            "manual_answer_correct",
            "manual_hallucinated_claims",
            "manual_total_claims",
            "manual_traceable",
            "manual_pmid_correct",
            "manual_pmid_total",
            "manual_ragas_score",
            "manual_notes",
        ],
    )
    print(f"Wrote responses to {args.responses}")
    print(f"Wrote manual review template to {args.manual_review}")


if __name__ == "__main__":
    main()
