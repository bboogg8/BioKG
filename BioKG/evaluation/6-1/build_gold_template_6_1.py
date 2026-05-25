from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


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


DEFAULT_OUTPUT = EXPERIMENT_DIR / "data" / "ner_annotation_template.jsonl"
ENTITY_LABELS = ("Enzyme/Gene", "Compound", "Pathway", "Protein")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


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

            protein_rows = session.run(
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
            )
            for row in protein_rows:
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

            enzyme_rows = session.run(
                """
                MATCH (e:Enzyme)
                RETURN DISTINCT e.ec AS ec, e.id AS id, e.name AS name
                """
            )
            for row in enzyme_rows:
                add_terms(vocab["Enzyme/Gene"], row.get("ec"), row.get("id"), row.get("name"))

            pathway_rows = session.run(
                """
                MATCH (p:Pathway)
                WHERE p.name IS NOT NULL
                RETURN DISTINCT p.name AS name
                """
            )
            for row in pathway_rows:
                name = str(row["name"])
                add_terms(vocab["Pathway"], name, name.split(" - ", 1)[0])

            compound_rows = session.run(
                """
                MATCH (c:Compound)
                RETURN DISTINCT c.id AS id, c.name AS name
                """
            )
            for row in compound_rows:
                add_terms(vocab["Compound"], row.get("id"), row.get("name"))

            return {
                label: sorted((term for term in terms if len(term) >= 3), key=len, reverse=True)
                for label, terms in vocab.items()
            }
    finally:
        driver.close()


def find_dictionary_spans(text: str, vocab: dict[str, list[str]]) -> list[dict[str, Any]]:
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
                spans.append(
                    {
                        "start": start,
                        "end": end,
                        "text": text[start:end],
                        "label": label,
                        "source": "dictionary_preplace",
                    }
                )

    spans.sort(key=lambda item: (item["start"], item["end"], item["label"]))
    return spans


def fetch_abstracts(sample_size: int, keywords: list[str] | None) -> list[dict[str, str]]:
    keyword_filter = ""
    params: dict[str, Any] = {"sample_size": sample_size}
    if keywords:
        keyword_filter = """
        AND any(keyword IN $keywords WHERE toLower(p.abstract) CONTAINS toLower(keyword))
        """
        params["keywords"] = keywords

    driver = get_driver()
    try:
        with driver.session() as session:
            rows = session.run(
                f"""
                MATCH (p:Publication)
                WHERE p.abstract IS NOT NULL
                {keyword_filter}
                RETURN p.pmid AS pmid, p.abstract AS abstract
                ORDER BY rand()
                LIMIT $sample_size
                """,
                **params,
            )
            return [{"pmid": str(row["pmid"]), "abstract": str(row["abstract"])} for row in rows]
    finally:
        driver.close()


def build_template(sample_size: int, keywords: list[str] | None) -> list[dict[str, Any]]:
    vocab = fetch_vocabulary()
    records: list[dict[str, Any]] = []

    for row in fetch_abstracts(sample_size, keywords):
        text = row["abstract"]
        records.append(
            {
                "pmid": row["pmid"],
                "text": text,
                "candidate_entities": find_dictionary_spans(text, vocab),
                "gold_entities": [],
                "annotation_status": "needs_manual_review",
                "annotation_note": "Copy reviewed entities into gold_entities before evaluation.",
            }
        )

    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Table 6-1 NER gold annotation template.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=int, default=300)
    parser.add_argument(
        "--keyword",
        action="append",
        dest="keywords",
        help="Optional PubMed abstract keyword filter. Repeat for multiple keywords.",
    )
    args = parser.parse_args()

    records = build_template(args.sample_size, args.keywords)
    write_jsonl(args.output, records)
    print(f"Wrote {len(records)} annotation records to {args.output}")


if __name__ == "__main__":
    main()
