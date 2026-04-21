from __future__ import annotations

import argparse
import re
from pathlib import Path

from chapter6_common import DATA_DIR, ensure_dirs, write_jsonl

try:
    from BioKG.neo4j_utils.neo4j_conn import get_driver
except ModuleNotFoundError:
    from neo4j_utils.neo4j_conn import get_driver


DEFAULT_OUTPUT = DATA_DIR / "ner_annotation_template.jsonl"


def fetch_vocab() -> dict[str, list[str]]:
    driver = get_driver()
    try:
        with driver.session() as session:
            vocab = {
                "Enzyme/Gene": set(),
                "Compound": set(),
                "Pathway": set(),
                "Protein": set(),
            }
            for row in session.run(
                """
                MATCH (p:Protein)
                RETURN DISTINCT
                    p.`Gene Names (primary)` AS gene_primary,
                    p.Entry AS entry,
                    p.`Entry Name` AS entry_name,
                    p.`Protein names` AS protein_name
                """
            ):
                for key in ("gene_primary", "entry", "entry_name"):
                    value = row.get(key)
                    if value:
                        vocab["Enzyme/Gene"].add(str(value))
                if row.get("protein_name"):
                    vocab["Protein"].add(str(row["protein_name"]))

            for row in session.run("MATCH (p:Pathway) WHERE p.name IS NOT NULL RETURN DISTINCT p.name AS name"):
                name = str(row["name"])
                vocab["Pathway"].add(name)
                vocab["Pathway"].add(name.split(" - ", 1)[0])

            for row in session.run("MATCH (c:Compound) WHERE c.id IS NOT NULL RETURN DISTINCT c.id AS compound_id"):
                vocab["Compound"].add(str(row["compound_id"]))

            return {label: sorted(values, key=len, reverse=True) for label, values in vocab.items()}
    finally:
        driver.close()


def find_spans(text: str, vocab: dict[str, list[str]]) -> list[dict]:
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
                entities.append(
                    {
                        "start": start,
                        "end": end,
                        "text": text[start:end],
                        "label": label,
                        "source": "dictionary_prelabel",
                    }
                )
    entities.sort(key=lambda item: (item["start"], item["end"]))
    return entities


def build_template(sample_size: int) -> list[dict]:
    vocab = fetch_vocab()
    driver = get_driver()
    try:
        with driver.session() as session:
            rows = list(
                session.run(
                    """
                    MATCH (p:Publication)
                    WHERE p.abstract IS NOT NULL
                    RETURN p.pmid AS pmid, p.abstract AS abstract
                    ORDER BY toInteger(p.pmid) DESC
                    LIMIT $sample_size
                    """,
                    sample_size=sample_size,
                )
            )
    finally:
        driver.close()

    records = []
    for row in rows:
        text = str(row["abstract"])
        records.append(
            {
                "pmid": str(row["pmid"]),
                "text": text,
                "gold_entities": find_spans(text, vocab),
                "annotation_status": "needs_manual_review",
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="生成第六章 NER 实验的人工标注模板。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=int, default=200)
    args = parser.parse_args()

    ensure_dirs()
    records = build_template(args.sample_size)
    write_jsonl(args.output, records)
    print(f"NER annotation template -> {args.output} ({len(records)} abstracts)")


if __name__ == "__main__":
    main()
