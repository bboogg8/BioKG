from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from chapter6_common import (
    DATA_DIR,
    RESULTS_DIR,
    bleu4,
    call_ollama,
    ensure_dirs,
    extract_ec_numbers,
    extract_pmids,
    format_float,
    format_pct,
    improvement_text,
    load_graph_vocabulary,
    load_jsonl,
    markdown_table,
    mean,
    normalize_text,
    strip_think_tags,
    write_csv,
    write_jsonl,
)

try:
    from BioKG.neo4j_utils.neo4j_conn import get_driver
except ModuleNotFoundError:
    from neo4j_utils.neo4j_conn import get_driver


DEFAULT_DATASET = DATA_DIR / "qa_eval_100.jsonl"
DEFAULT_RESPONSES = RESULTS_DIR / "qa_eval_responses.jsonl"
DEFAULT_METRICS = RESULTS_DIR / "table6_2_qa_metrics.csv"


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
            result = []
            for row in rows:
                abstract = (row.get("abstract") or "").replace("\n", " ").strip()
                result.append({"pmid": str(row["pmid"]), "abstract": abstract[:420]})
            return result
    finally:
        driver.close()


def build_graph_rag_prompt(record: dict[str, Any]) -> str:
    gold = record["gold"]
    publications = fetch_publication_context(gold.get("pmids", []))

    context_lines = [f"问题类型: {record['question_type']}"]
    target = record["target"]
    if "ec_number" in target:
        context_lines.append(f"目标 EC 编号: {target['ec_number']}")
    if "pathway_name" in target:
        context_lines.append(f"目标通路: {target['pathway_name']}")
    if "compound_id" in target:
        context_lines.append(f"目标化合物: {target['compound_id']}")
    if gold.get("entities"):
        context_lines.append(f"图谱关键实体: {', '.join(gold['entities'])}")
    if gold.get("ec_numbers"):
        context_lines.append(f"关联 EC 编号: {', '.join(gold['ec_numbers'])}")
    if gold.get("pathways"):
        context_lines.append(f"关联通路: {', '.join(gold['pathways'])}")
    if gold.get("pmids"):
        context_lines.append(f"证据 PMID: {', '.join(gold['pmids'])}")

    for pub in publications:
        context_lines.append(f"[PMID: {pub['pmid']}] {pub['abstract']}")

    context = "\n".join(context_lines)
    return (
        "You are a biomedical Graph-RAG assistant.\n"
        "Use only the provided graph facts and publication evidence.\n"
        "Do not invent facts. Do not show chain-of-thought.\n"
        "Answer briefly and cite evidence as [PMID: xxxxx] when available.\n\n"
        f"Question: {record['question']}\n\n"
        f"Context:\n{context}\n\n"
        "Final answer:"
    )


def build_native_prompt(record: dict[str, Any]) -> str:
    return (
        "You are a biomedical QA assistant.\n"
        "Answer the question directly. If uncertain, say you are uncertain.\n"
        "Do not show chain-of-thought.\n\n"
        f"Question: {record['question']}\n\n"
        "Answer:"
    )


def generate_answer(record: dict[str, Any], system_name: str, model_name: str) -> str:
    prompt = build_graph_rag_prompt(record) if system_name == "graph_rag" else build_native_prompt(record)
    answer = strip_think_tags(call_ollama(prompt, model_name=model_name, num_predict=220, temperature=0.1))
    if answer.strip():
        return answer.strip()

    fallback = (
        f"Question: {record['question']}\n"
        "Give a short factual answer with entity names or PMID numbers if known.\n"
        "Answer:"
    )
    if system_name == "graph_rag":
        fallback = (
            f"{fallback}\n\n"
            f"Use only this evidence:\n{build_graph_rag_prompt(record)}"
        )
    return strip_think_tags(call_ollama(fallback, model_name=model_name, num_predict=220, temperature=0.2)).strip()


def entity_aliases(record: dict[str, Any]) -> set[str]:
    aliases = set()
    for key in ("entities", "ec_numbers", "pathways", "pmids", "publication_titles"):
        for value in record["gold"].get(key, []):
            aliases.add(str(value))
    for value in record["target"].values():
        aliases.add(str(value))
    return aliases


def extract_gold_entity_hits(answer: str, gold_items: list[str]) -> set[str]:
    hits = set()
    answer_norm = normalize_text(answer)
    for item in gold_items:
        if normalize_text(item) and normalize_text(item) in answer_norm:
            hits.add(item)
    return hits


def extract_known_mentions(answer: str, vocabulary: dict[str, set[str]]) -> set[str]:
    mentions = set(extract_ec_numbers(answer))
    mentions.update(extract_pmids(answer))
    answer_norm = normalize_text(answer)
    for bucket in ("proteins", "pathways", "compounds"):
        for value in vocabulary[bucket]:
            norm = normalize_text(value)
            if norm and norm in answer_norm:
                mentions.add(value)
    return mentions


def set_f1(predicted: set[str], gold: set[str]) -> float:
    if not predicted and not gold:
        return 1.0
    if not predicted or not gold:
        return 0.0
    overlap = len(predicted & gold)
    precision = overlap / len(predicted) if predicted else 0.0
    recall = overlap / len(gold) if gold else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def score_answer(record: dict[str, Any], answer: str, vocabulary: dict[str, set[str]]) -> dict[str, float | bool | None]:
    gold = record["gold"]
    gold_entities = set(gold.get("entities", []))
    gold_ecs = set(gold.get("ec_numbers", [])) | set(record["target"].get("ec_number", []) if isinstance(record["target"].get("ec_number"), list) else [])
    if record["target"].get("ec_number"):
        gold_ecs.add(str(record["target"]["ec_number"]))
    gold_pmids = set(gold.get("pmids", []))

    mentioned_entities = extract_gold_entity_hits(answer, list(gold_entities))
    mentioned_ecs = set(extract_ec_numbers(answer))
    mentioned_pmids = set(extract_pmids(answer))

    if record["question_type"] == "ec_to_enzyme":
        factual_score = max(set_f1(mentioned_entities, gold_entities), 1.0 if (mentioned_entities & gold_entities) else 0.0)
    elif record["question_type"] == "pathway_to_enzymes":
        factual_score = set_f1(mentioned_entities | mentioned_ecs, gold_entities | gold_ecs)
    else:
        factual_score = set_f1(mentioned_pmids, gold_pmids)

    answer_correct = factual_score >= 0.6 if record["question_type"] != "compound_to_latest_literature" else factual_score > 0.0

    known_mentions = extract_known_mentions(answer, vocabulary)
    allowed = entity_aliases(record)
    unsupported = {item for item in known_mentions if item not in allowed}
    hallucination_rate = (len(unsupported) / len(known_mentions)) if known_mentions else 0.0

    traceable = bool(mentioned_pmids & gold_pmids)
    pmid_accuracy = None
    if mentioned_pmids:
        pmid_accuracy = len(mentioned_pmids & gold_pmids) / len(mentioned_pmids)

    ec_hit = False
    if record["question_type"] == "ec_to_enzyme":
        ec_hit = bool(mentioned_entities & gold_entities) or bool(mentioned_ecs & gold_ecs)

    bleu = bleu4(record["reference_answer"], answer)
    ragas_style = (
        0.4 * factual_score
        + 0.2 * (1.0 - hallucination_rate)
        + 0.25 * (1.0 if traceable else 0.0)
        + 0.15 * bleu
    )

    return {
        "factual_score": factual_score,
        "answer_correct": bool(answer_correct),
        "ec_hit": ec_hit,
        "hallucination_rate": hallucination_rate,
        "traceable": traceable,
        "pmid_accuracy": pmid_accuracy,
        "bleu4": bleu,
        "ragas_score": ragas_style,
    }


def load_cached_responses(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    cache = {}
    for record in load_jsonl(path):
        cache[(record["question_id"], record["system_name"])] = record
    return cache


def save_responses(path: Path, responses: list[dict[str, Any]]) -> None:
    write_jsonl(path, responses)


def evaluate(
    dataset: list[dict[str, Any]],
    *,
    model_name: str,
    responses_path: Path,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    vocabulary = load_graph_vocabulary()
    cache = load_cached_responses(responses_path)
    responses: list[dict[str, Any]] = []

    for record in dataset[: limit or len(dataset)]:
        for system_name in ("native_llm", "graph_rag"):
            cache_key = (record["question_id"], system_name)
            if cache_key in cache and cache[cache_key].get("answer", "").strip():
                answer = cache[cache_key]["answer"]
            else:
                answer = generate_answer(record, system_name, model_name)
                cache[cache_key] = {
                    "question_id": record["question_id"],
                    "system_name": system_name,
                    "answer": answer,
                }
            scores = score_answer(record, answer, vocabulary)
            response_row = {
                "question_id": record["question_id"],
                "question_type": record["question_type"],
                "system_name": system_name,
                "question": record["question"],
                "answer": answer,
                **scores,
            }
            responses.append(response_row)

    save_responses(responses_path, list(cache.values()))
    return responses, build_summary_table(responses)


def build_summary_table(responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_system: dict[str, list[dict[str, Any]]] = {"native_llm": [], "graph_rag": []}
    for row in responses:
        by_system[row["system_name"]].append(row)

    native_rows = by_system["native_llm"]
    rag_rows = by_system["graph_rag"]

    def agg(rows: list[dict[str, Any]], key: str) -> float | None:
        values = [row[key] for row in rows if row[key] is not None]
        if not values:
            return None
        return mean([float(value) for value in values])

    metrics = [
        ("事实准确性", "答案正确率", agg(native_rows, "answer_correct"), agg(rag_rows, "answer_correct"), True),
        (
            "事实准确性",
            "EC编号命中率",
            agg([row for row in native_rows if row["question_type"] == "ec_to_enzyme"], "ec_hit"),
            agg([row for row in rag_rows if row["question_type"] == "ec_to_enzyme"], "ec_hit"),
            True,
        ),
        ("幻觉抑制", "幻觉率(人工规则)", agg(native_rows, "hallucination_rate"), agg(rag_rows, "hallucination_rate"), True),
        ("知识溯源", "答案可溯源率", agg(native_rows, "traceable"), agg(rag_rows, "traceable"), True),
        ("知识溯源", "PMID引用准确率", agg(native_rows, "pmid_accuracy"), agg(rag_rows, "pmid_accuracy"), True),
        ("语言流畅度", "BLEU-4", agg(native_rows, "bleu4"), agg(rag_rows, "bleu4"), False),
        ("综合得分", "RAGAS Score", agg(native_rows, "ragas_score"), agg(rag_rows, "ragas_score"), False),
    ]

    table_rows = []
    for dimension, metric_name, native_value, rag_value, is_pct in metrics:
        row = {
            "evaluation_dimension": dimension,
            "metric": metric_name,
            "native_llm": format_pct(native_value) if is_pct else format_float(native_value),
            "graph_rag": format_pct(rag_value) if is_pct else format_float(rag_value),
            "improvement": improvement_text(native_value, rag_value, percent_points=is_pct),
        }
        table_rows.append(row)
    return table_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="运行第六章问答可信度对比实验。")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--responses", type=Path, default=DEFAULT_RESPONSES)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--model", type=str, default="deepseek-r1:7b")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    ensure_dirs()
    dataset = load_jsonl(args.dataset)
    responses, table_rows = evaluate(dataset, model_name=args.model, responses_path=args.responses, limit=args.limit)

    write_csv(
        args.metrics,
        table_rows,
        ["evaluation_dimension", "metric", "native_llm", "graph_rag", "improvement"],
    )

    print(f"Saved {len(responses)} responses -> {args.responses}")
    print(f"Metrics table -> {args.metrics}")
    print(
        markdown_table(
            table_rows,
            [
                ("evaluation_dimension", "评估维度"),
                ("metric", "评测指标"),
                ("native_llm", "原生LLM"),
                ("graph_rag", "Graph-RAG"),
                ("improvement", "提升幅度"),
            ],
        )
    )


if __name__ == "__main__":
    main()
