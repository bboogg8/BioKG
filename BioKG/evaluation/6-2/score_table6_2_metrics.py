from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


EXPERIMENT_DIR = Path(__file__).resolve().parent
DEFAULT_RESPONSES = EXPERIMENT_DIR / "results" / "qa_eval_responses.jsonl"
DEFAULT_REVIEW = EXPERIMENT_DIR / "results" / "manual_review_template.csv"
DEFAULT_CSV = EXPERIMENT_DIR / "results" / "table6_2_qa_metrics.csv"
DEFAULT_MD = EXPERIMENT_DIR / "results" / "table6_2_qa_metrics.md"
EC_PATTERN = re.compile(r"\b\d+\.\d+\.\d+\.\d+\b")
PMID_PATTERN = re.compile(r"\bPMID[:\s]*([0-9]{6,9})\b", flags=re.I)
PLAIN_PMID_PATTERN = re.compile(r"\b([0-9]{6,9})\b")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_manual_review(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return {
            (row["question_id"], row["system_name"]): row
            for row in reader
            if row.get("question_id") and row.get("system_name")
        }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "是", "正确", "可溯源"}:
        return True
    if text in {"0", "false", "no", "n", "否", "错误", "不可溯源"}:
        return False
    return None


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_text(text: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (text or "").upper())


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def extract_ec_numbers(text: str) -> list[str]:
    return dedupe(EC_PATTERN.findall(text or ""))


def extract_pmids(text: str) -> list[str]:
    pmids = [match.group(1) for match in PMID_PATTERN.finditer(text or "")]
    if pmids:
        return dedupe(pmids)
    return dedupe(PLAIN_PMID_PATTERN.findall(text or ""))


def tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9.]+|[\u4e00-\u9fff]", text or "") if token.strip()]


def bleu4(reference: str, hypothesis: str) -> float:
    ref_tokens = tokenize(reference)
    hyp_tokens = tokenize(hypothesis)
    if not ref_tokens or not hyp_tokens:
        return 0.0

    precisions: list[float] = []
    for n in range(1, 5):
        ref_counts = Counter(tuple(ref_tokens[i : i + n]) for i in range(max(len(ref_tokens) - n + 1, 0)))
        hyp_counts = Counter(tuple(hyp_tokens[i : i + n]) for i in range(max(len(hyp_tokens) - n + 1, 0)))
        if not hyp_counts:
            precisions.append(1e-9)
            continue
        overlap = sum(min(count, ref_counts.get(gram, 0)) for gram, count in hyp_counts.items())
        precisions.append((overlap + 1) / (sum(hyp_counts.values()) + 1))

    brevity_penalty = 1.0 if len(hyp_tokens) > len(ref_tokens) else math.exp(1 - len(ref_tokens) / max(len(hyp_tokens), 1))
    return brevity_penalty * math.exp(sum(0.25 * math.log(score) for score in precisions))


def set_f1(predicted: set[str], gold: set[str]) -> float:
    if not predicted and not gold:
        return 1.0
    if not predicted or not gold:
        return 0.0
    overlap = len(predicted & gold)
    precision = overlap / len(predicted)
    recall = overlap / len(gold)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def gold_text_hits(answer: str, gold_items: list[str]) -> set[str]:
    answer_norm = normalize_text(answer)
    return {item for item in gold_items if normalize_text(item) and normalize_text(item) in answer_norm}


def automatic_scores(row: dict[str, Any]) -> dict[str, float | bool | None]:
    answer = row.get("answer", "")
    gold = row.get("gold", {})
    target = row.get("target", {})
    gold_entities = set(gold.get("entities", []))
    gold_ecs = set(gold.get("ec_numbers", []))
    if target.get("ec_number"):
        gold_ecs.add(str(target["ec_number"]))
    gold_pmids = set(gold.get("pmids", []))

    mentioned_entities = gold_text_hits(answer, list(gold_entities))
    mentioned_ecs = set(extract_ec_numbers(answer))
    mentioned_pmids = set(extract_pmids(answer))

    if row["question_type"] == "ec_to_enzyme":
        factual_score = max(set_f1(mentioned_entities, gold_entities), 1.0 if mentioned_entities else 0.0)
    elif row["question_type"] == "pathway_to_enzymes":
        factual_score = set_f1(mentioned_entities | mentioned_ecs, gold_entities | gold_ecs)
    else:
        factual_score = set_f1(mentioned_pmids, gold_pmids)

    answer_correct = factual_score >= 0.6 if row["question_type"] != "compound_to_latest_literature" else factual_score > 0.0
    traceable = bool(mentioned_pmids & gold_pmids)
    pmid_accuracy = len(mentioned_pmids & gold_pmids) / len(mentioned_pmids) if mentioned_pmids else None
    ec_hit = bool((mentioned_ecs & gold_ecs) or (mentioned_entities & gold_entities))
    unsupported = (mentioned_ecs - gold_ecs) | (mentioned_pmids - gold_pmids)
    hallucination_rate = len(unsupported) / max(len(mentioned_ecs | mentioned_pmids), 1)
    bleu = bleu4(row.get("reference_answer", ""), answer)
    ragas_score = 0.4 * factual_score + 0.2 * (1.0 - hallucination_rate) + 0.25 * float(traceable) + 0.15 * bleu

    return {
        "factual_score": factual_score,
        "answer_correct": answer_correct,
        "ec_hit": ec_hit,
        "hallucination_rate": hallucination_rate,
        "traceable": traceable,
        "pmid_accuracy": pmid_accuracy,
        "bleu4": bleu,
        "ragas_score": ragas_score,
    }


def apply_manual_scores(scores: dict[str, float | bool | None], review: dict[str, str] | None) -> dict[str, float | bool | None]:
    if not review:
        return scores

    manual_correct = parse_bool(review.get("manual_answer_correct"))
    if manual_correct is not None:
        scores["answer_correct"] = manual_correct
        scores["factual_score"] = 1.0 if manual_correct else 0.0

    hallucinated = parse_float(review.get("manual_hallucinated_claims"))
    total_claims = parse_float(review.get("manual_total_claims"))
    if hallucinated is not None and total_claims and total_claims > 0:
        scores["hallucination_rate"] = hallucinated / total_claims

    traceable = parse_bool(review.get("manual_traceable"))
    if traceable is not None:
        scores["traceable"] = traceable

    pmid_correct = parse_float(review.get("manual_pmid_correct"))
    pmid_total = parse_float(review.get("manual_pmid_total"))
    if pmid_correct is not None and pmid_total and pmid_total > 0:
        scores["pmid_accuracy"] = pmid_correct / pmid_total

    ragas_score = parse_float(review.get("manual_ragas_score"))
    if ragas_score is not None:
        scores["ragas_score"] = ragas_score

    return scores


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def aggregate(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return None
    return mean([float(value) for value in values])


def format_pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def format_float(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def improvement(base: float | None, new: float | None, percent_points: bool) -> str:
    if base is None or new is None:
        return "N/A"
    if percent_points:
        return f"{(new - base) * 100:+.1f}pp"
    if abs(base) < 1e-9:
        return "N/A"
    return f"{((new - base) / base) * 100:+.1f}%"


def build_metric_rows(scored: list[dict[str, Any]]) -> list[dict[str, str]]:
    native = [row for row in scored if row["system_name"] == "native_llm"]
    graph = [row for row in scored if row["system_name"] == "graph_rag"]
    native_ec = [row for row in native if row["question_type"] == "ec_to_enzyme"]
    graph_ec = [row for row in graph if row["question_type"] == "ec_to_enzyme"]

    metric_defs = [
        ("事实准确性", "答案正确率", aggregate(native, "answer_correct"), aggregate(graph, "answer_correct"), True),
        ("事实准确性", "EC编号命中率", aggregate(native_ec, "ec_hit"), aggregate(graph_ec, "ec_hit"), True),
        ("幻觉抑制", "幻觉率(人工标注)", aggregate(native, "hallucination_rate"), aggregate(graph, "hallucination_rate"), True),
        ("知识溯源", "答案可溯源率", aggregate(native, "traceable"), aggregate(graph, "traceable"), True),
        ("知识溯源", "PMID引用准确率", aggregate(native, "pmid_accuracy"), aggregate(graph, "pmid_accuracy"), True),
        ("语言流畅度", "BLEU-4", aggregate(native, "bleu4"), aggregate(graph, "bleu4"), False),
        ("综合得分", "RAGAS Score", aggregate(native, "ragas_score"), aggregate(graph, "ragas_score"), False),
    ]

    rows: list[dict[str, str]] = []
    for dimension, metric, native_value, graph_value, is_pct in metric_defs:
        rows.append(
            {
                "evaluation_dimension": dimension,
                "metric": metric,
                "native_llm": format_pct(native_value) if is_pct else format_float(native_value),
                "graph_rag": format_pct(graph_value) if is_pct else format_float(graph_value),
                "improvement": improvement(native_value, graph_value, percent_points=is_pct),
            }
        )
    return rows


def markdown_table(rows: list[dict[str, str]]) -> str:
    headers = [
        ("evaluation_dimension", "评估维度"),
        ("metric", "评测指标"),
        ("native_llm", "原生LLM"),
        ("graph_rag", "Graph-RAG"),
        ("improvement", "提升幅度"),
    ]
    lines = [
        "| " + " | ".join(label for _, label in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row[key] for key, _ in headers) + " |")
    return "\n".join(lines) + "\n"


def score_responses(responses: list[dict[str, Any]], manual_review: dict[tuple[str, str], dict[str, str]]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in responses:
        scores = automatic_scores(row)
        scores = apply_manual_scores(scores, manual_review.get((row["question_id"], row["system_name"])))
        scored.append({**row, **scores})
    return scored


def main() -> None:
    parser = argparse.ArgumentParser(description="Score Table 6-2 Graph-RAG trustworthiness metrics.")
    parser.add_argument("--responses", type=Path, default=DEFAULT_RESPONSES)
    parser.add_argument("--manual-review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()

    responses = load_jsonl(args.responses)
    manual_review = load_manual_review(args.manual_review)
    scored = score_responses(responses, manual_review)
    rows = build_metric_rows(scored)
    fieldnames = ["evaluation_dimension", "metric", "native_llm", "graph_rag", "improvement"]
    write_csv(args.csv, rows, fieldnames)
    write_text(args.markdown, markdown_table(rows))
    print(f"Table 6-2 CSV: {args.csv}")
    print(f"Table 6-2 Markdown: {args.markdown}")


if __name__ == "__main__":
    main()
