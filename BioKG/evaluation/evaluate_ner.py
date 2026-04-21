from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

import spacy

from chapter6_common import DATA_DIR, RESULTS_DIR, ensure_dirs, markdown_table, write_csv
from generate_ner_annotation_template import fetch_vocab


DEFAULT_DATASET = DATA_DIR / "ner_annotation_template.jsonl"
DEFAULT_OUTPUT = RESULTS_DIR / "table6_1_ner_metrics.csv"


def load_dataset(path: Path) -> list[dict]:
    import json

    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def exact_match_metrics(predicted: list[dict], gold: list[dict]) -> tuple[int, int, int]:
    pred_set = {(item["start"], item["end"], item["label"]) for item in predicted}
    gold_set = {(item["start"], item["end"], item["label"]) for item in gold}
    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    return tp, fp, fn


def rule_extract(text: str, vocab: dict[str, list[str]]) -> list[dict]:
    entities = []
    occupied: list[tuple[int, int]] = []
    for label, terms in vocab.items():
        for term in terms:
            if len(term) < 3:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", flags=re.I)
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(not (end <= s or start >= e) for s, e in occupied):
                    continue
                occupied.append((start, end))
                entities.append({"start": start, "end": end, "label": label})
    return entities


def scispacy_extract(text: str, vocab: dict[str, list[str]], nlp) -> list[dict]:
    doc = nlp(text)
    entities = []
    protein_terms = {term.upper() for term in vocab["Protein"]}
    enzyme_terms = {term.upper() for term in vocab["Enzyme/Gene"]}
    compound_terms = {term.upper() for term in vocab["Compound"]}

    for ent in doc.ents:
        raw = ent.text.strip()
        raw_upper = raw.upper()
        label = None
        if ent.label_ == "GENE_OR_GENE_PRODUCT":
            label = "Protein" if raw_upper in protein_terms else "Enzyme/Gene"
        elif ent.label_ in {"SIMPLE_CHEMICAL", "CHEMICAL", "AMINO_ACID"} or raw_upper in compound_terms:
            label = "Compound"
        elif raw_upper in enzyme_terms:
            label = "Enzyme/Gene"
        if label:
            entities.append({"start": ent.start_char, "end": ent.end_char, "label": label})

    pathway_entities = rule_extract(text, {"Pathway": vocab["Pathway"]})
    entities.extend(pathway_entities)

    unique = {}
    for item in entities:
        unique[(item["start"], item["end"], item["label"])] = item
    return list(unique.values())


def calc_scores(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def evaluate_records(records: list[dict]) -> list[dict]:
    vocab = fetch_vocab()
    nlp = spacy.load("en_ner_bionlp13cg_md")

    totals = {
        "规则匹配": defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0}),
        "ScispaCy NER": defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0}),
    }

    for record in records:
        gold = record.get("gold_entities", [])
        rule_pred = rule_extract(record["text"], vocab)
        sci_pred = scispacy_extract(record["text"], vocab, nlp)

        for label in ("Enzyme/Gene", "Compound", "Pathway", "Protein"):
            gold_label = [item for item in gold if item["label"] == label]
            rule_label = [item for item in rule_pred if item["label"] == label]
            sci_label = [item for item in sci_pred if item["label"] == label]

            tp, fp, fn = exact_match_metrics(rule_label, gold_label)
            totals["规则匹配"][label]["tp"] += tp
            totals["规则匹配"][label]["fp"] += fp
            totals["规则匹配"][label]["fn"] += fn

            tp, fp, fn = exact_match_metrics(sci_label, gold_label)
            totals["ScispaCy NER"][label]["tp"] += tp
            totals["ScispaCy NER"][label]["fp"] += fp
            totals["ScispaCy NER"][label]["fn"] += fn

    rows = []
    weighted_data = {"规则匹配": [], "ScispaCy NER": []}

    for label in ("Enzyme/Gene", "Compound", "Pathway", "Protein"):
        for method in ("规则匹配", "ScispaCy NER"):
            tp = totals[method][label]["tp"]
            fp = totals[method][label]["fp"]
            fn = totals[method][label]["fn"]
            precision, recall, f1 = calc_scores(tp, fp, fn)
            support = tp + fn
            weighted_data[method].append((support, precision, recall, f1))
            rows.append(
                {
                    "entity_type": label,
                    "method": method,
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "precision": f"{precision * 100:.1f}%",
                    "recall": f"{recall * 100:.1f}%",
                    "f1": f"{f1 * 100:.1f}%",
                }
            )

    for method in ("规则匹配", "ScispaCy NER"):
        total_support = sum(item[0] for item in weighted_data[method]) or 1
        precision = sum(item[0] * item[1] for item in weighted_data[method]) / total_support
        recall = sum(item[0] * item[2] for item in weighted_data[method]) / total_support
        f1 = sum(item[0] * item[3] for item in weighted_data[method]) / total_support
        rows.append(
            {
                "entity_type": "加权平均",
                "method": method,
                "tp": "—",
                "fp": "—",
                "fn": "—",
                "precision": f"{precision * 100:.1f}%",
                "recall": f"{recall * 100:.1f}%",
                "f1": f"{f1 * 100:.1f}%",
            }
        )

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="运行第六章 NER 对比实验。")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    ensure_dirs()
    records = load_dataset(args.dataset)
    rows = evaluate_records(records)
    write_csv(
        args.output,
        rows,
        ["entity_type", "method", "tp", "fp", "fn", "precision", "recall", "f1"],
    )
    print(f"NER metrics -> {args.output}")
    print(
        markdown_table(
            rows,
            [
                ("entity_type", "实体类型"),
                ("method", "方法"),
                ("tp", "TP"),
                ("fp", "FP"),
                ("fn", "FN"),
                ("precision", "精确率 P"),
                ("recall", "召回率 R"),
                ("f1", "F1值"),
            ],
        )
    )


if __name__ == "__main__":
    main()
