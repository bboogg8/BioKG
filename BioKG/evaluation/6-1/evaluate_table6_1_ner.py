from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


EXPERIMENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPERIMENT_DIR.parents[2]
for candidate in (PROJECT_ROOT, PROJECT_ROOT / "BioKG"):
    text = str(candidate)
    if text not in sys.path:
        sys.path.insert(0, text)

try:
    import spacy
except ModuleNotFoundError as exc:
    spacy = None
    SPACY_IMPORT_ERROR = exc
else:
    SPACY_IMPORT_ERROR = None

try:
    from BioKG.neo4j_utils.neo4j_conn import get_driver
except ModuleNotFoundError:
    from neo4j_utils.neo4j_conn import get_driver


DEFAULT_DATASET = EXPERIMENT_DIR / "data" / "ner_gold.jsonl"
DEFAULT_CSV = EXPERIMENT_DIR / "results" / "table6_1_ner_metrics.csv"
DEFAULT_MD = EXPERIMENT_DIR / "results" / "table6_1_ner_metrics.md"
ENTITY_LABELS = ("Enzyme/Gene", "Compound", "Pathway", "Protein")
METHODS = ("规则匹配", "ScispaCy NER")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def add_terms(target: set[str], *values: Any) -> None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            target.add(text)


def fetch_vocabulary() -> dict[str, list[str]]:
    driver = get_driver()
    try:
        with driver.session() as session:
            vocab: dict[str, set[str]] = {label: set() for label in ENTITY_LABELS}

            for row in session.run(
                """
                MATCH (p:Protein)
                RETURN DISTINCT
                    p.`Gene Names (primary)` AS gene_primary,
                    p.`Gene Names` AS gene_names,
                    p.Entry AS entry,
                    p.`Entry Name` AS entry_name,
                    p.`Protein names` AS protein_names,
                    p.name AS name
                """
            ):
                add_terms(
                    vocab["Enzyme/Gene"],
                    row.get("gene_primary"),
                    row.get("gene_names"),
                    row.get("entry"),
                    row.get("entry_name"),
                    row.get("name"),
                )
                add_terms(vocab["Protein"], row.get("protein_names"))
                entry_name = row.get("entry_name")
                if entry_name and "_" in str(entry_name):
                    add_terms(vocab["Enzyme/Gene"], str(entry_name).split("_", 1)[0])

            for row in session.run("MATCH (e:Enzyme) RETURN DISTINCT e.ec AS ec, e.id AS id, e.name AS name"):
                add_terms(vocab["Enzyme/Gene"], row.get("ec"), row.get("id"), row.get("name"))

            for row in session.run("MATCH (p:Pathway) WHERE p.name IS NOT NULL RETURN DISTINCT p.name AS name"):
                name = str(row["name"])
                add_terms(vocab["Pathway"], name, name.split(" - ", 1)[0])

            for row in session.run("MATCH (c:Compound) RETURN DISTINCT c.id AS id, c.name AS name"):
                add_terms(vocab["Compound"], row.get("id"), row.get("name"))

            return {
                label: sorted((term for term in terms if len(term) >= 3), key=len, reverse=True)
                for label, terms in vocab.items()
            }
    finally:
        driver.close()


def normalize_span_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def resolve_gold_entities(record: dict[str, Any]) -> list[dict[str, Any]]:
    text = record.get("text", "")
    resolved: list[dict[str, Any]] = []
    used: set[tuple[int, int, str]] = set()

    for item in record.get("gold_entities", []):
        label = item.get("label")
        if label not in ENTITY_LABELS:
            continue

        if "start" in item and "end" in item:
            start = int(item["start"])
            end = int(item["end"])
        elif item.get("text"):
            needle = normalize_span_text(str(item["text"]))
            match = re.search(re.escape(needle), text, flags=re.I)
            if not match:
                continue
            start, end = match.span()
        else:
            continue

        key = (start, end, label)
        if 0 <= start < end <= len(text) and key not in used:
            resolved.append({"start": start, "end": end, "label": label})
            used.add(key)

    return resolved


def exact_match_metrics(predicted: list[dict[str, Any]], gold: list[dict[str, Any]]) -> tuple[int, int, int]:
    pred_set = {(int(item["start"]), int(item["end"]), str(item["label"])) for item in predicted}
    gold_set = {(int(item["start"]), int(item["end"]), str(item["label"])) for item in gold}
    return len(pred_set & gold_set), len(pred_set - gold_set), len(gold_set - pred_set)


def rule_extract(text: str, vocab: dict[str, list[str]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []

    for label in ENTITY_LABELS:
        for term in vocab[label]:
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", flags=re.I)
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(not (end <= left or start >= right) for left, right in occupied):
                    continue
                occupied.append((start, end))
                spans.append({"start": start, "end": end, "label": label})

    return spans


def scispacy_extract(text: str, vocab: dict[str, list[str]], nlp: Any) -> list[dict[str, Any]]:
    doc = nlp(text)
    spans: list[dict[str, Any]] = []
    protein_terms = {term.upper() for term in vocab["Protein"]}
    compound_terms = {term.upper() for term in vocab["Compound"]}
    enzyme_terms = {term.upper() for term in vocab["Enzyme/Gene"]}

    for ent in doc.ents:
        raw_upper = ent.text.strip().upper()
        label = None

        if ent.label_ in {"GENE_OR_GENE_PRODUCT", "GENE", "PROTEIN"}:
            label = "Protein" if raw_upper in protein_terms else "Enzyme/Gene"
        elif ent.label_ in {"SIMPLE_CHEMICAL", "CHEMICAL", "AMINO_ACID"} or raw_upper in compound_terms:
            label = "Compound"
        elif raw_upper in enzyme_terms:
            label = "Enzyme/Gene"

        if label:
            spans.append({"start": ent.start_char, "end": ent.end_char, "label": label})

    # The selected ScispaCy model is weak for pathway names, so both systems use
    # the same exact dictionary pathway recognizer for this entity type.
    spans.extend(rule_extract(text, {"Pathway": vocab["Pathway"], "Enzyme/Gene": [], "Compound": [], "Protein": []}))

    unique: dict[tuple[int, int, str], dict[str, Any]] = {}
    for span in spans:
        unique[(span["start"], span["end"], span["label"])] = span
    return list(unique.values())


def calc_scores(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def evaluate(records: list[dict[str, Any]], scispacy_model: str) -> list[dict[str, Any]]:
    if spacy is None:
        raise RuntimeError(f"spaCy is required for ScispaCy evaluation: {SPACY_IMPORT_ERROR}")

    vocab = fetch_vocabulary()
    nlp = spacy.load(scispacy_model)
    totals: dict[str, dict[str, dict[str, int]]] = {
        method: defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0}) for method in METHODS
    }

    for record in records:
        text = record.get("text", "")
        gold = resolve_gold_entities(record)
        predictions = {
            "规则匹配": rule_extract(text, vocab),
            "ScispaCy NER": scispacy_extract(text, vocab, nlp),
        }

        for label in ENTITY_LABELS:
            gold_label = [item for item in gold if item["label"] == label]
            for method in METHODS:
                pred_label = [item for item in predictions[method] if item["label"] == label]
                tp, fp, fn = exact_match_metrics(pred_label, gold_label)
                totals[method][label]["tp"] += tp
                totals[method][label]["fp"] += fp
                totals[method][label]["fn"] += fn

    rows: list[dict[str, Any]] = []
    weighted: dict[str, list[tuple[int, float, float, float]]] = {method: [] for method in METHODS}

    for label in ENTITY_LABELS:
        for method in METHODS:
            tp = totals[method][label]["tp"]
            fp = totals[method][label]["fp"]
            fn = totals[method][label]["fn"]
            precision, recall, f1 = calc_scores(tp, fp, fn)
            support = tp + fn
            weighted[method].append((support, precision, recall, f1))
            rows.append(
                {
                    "entity_type": label,
                    "method": method,
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "precision": pct(precision),
                    "recall": pct(recall),
                    "f1": pct(f1),
                }
            )

    for method in METHODS:
        total_support = sum(item[0] for item in weighted[method]) or 1
        precision = sum(support * p for support, p, _, _ in weighted[method]) / total_support
        recall = sum(support * r for support, _, r, _ in weighted[method]) / total_support
        f1 = sum(support * score for support, _, _, score in weighted[method]) / total_support
        rows.append(
            {
                "entity_type": "加权平均",
                "method": method,
                "tp": "-",
                "fp": "-",
                "fn": "-",
                "precision": pct(precision),
                "recall": pct(recall),
                "f1": pct(f1),
            }
        )

    return rows


def markdown_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        ("entity_type", "实体类型"),
        ("method", "方法"),
        ("tp", "TP"),
        ("fp", "FP"),
        ("fn", "FN"),
        ("precision", "精确率 P"),
        ("recall", "召回率 R"),
        ("f1", "F1值"),
    ]
    lines = [
        "| " + " | ".join(label for _, label in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[key]) for key, _ in headers) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Table 6-1 NER metrics.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    parser.add_argument("--scispacy-model", default="en_ner_bionlp13cg_md")
    args = parser.parse_args()

    records = load_jsonl(args.dataset)
    rows = evaluate(records, args.scispacy_model)
    fieldnames = ["entity_type", "method", "tp", "fp", "fn", "precision", "recall", "f1"]
    write_csv(args.csv, rows, fieldnames)
    write_text(args.markdown, markdown_table(rows))
    print(f"Table 6-1 CSV: {args.csv}")
    print(f"Table 6-1 Markdown: {args.markdown}")


if __name__ == "__main__":
    main()
