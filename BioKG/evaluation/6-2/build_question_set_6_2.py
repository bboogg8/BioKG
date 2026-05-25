from __future__ import annotations

import argparse
import csv
import json
import random
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


DEFAULT_OUTPUT = EXPERIMENT_DIR / "data" / "qa_eval_100.jsonl"
DEFAULT_SUMMARY = EXPERIMENT_DIR / "data" / "qa_eval_100_summary.csv"


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


def clean_list(values: Any, limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result[:limit] if limit else result


def publication_title_from_abstract(abstract: str | None) -> str:
    if not abstract:
        return ""
    for raw_line in str(abstract).splitlines():
        line = raw_line.strip()
        if len(line) >= 8 and not line.lower().startswith("doi:"):
            return line.rstrip(".")
    return str(abstract).split(".", 1)[0].strip()


def fetch_publications_by_pmids(pmids: list[str]) -> dict[str, dict[str, str]]:
    if not pmids:
        return {}

    driver = get_driver()
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (p:Publication)
                WHERE p.pmid IN $pmids
                RETURN p.pmid AS pmid, p.abstract AS abstract
                """,
                pmids=pmids,
            )
            return {
                str(row["pmid"]): {
                    "title": publication_title_from_abstract(row.get("abstract")),
                    "abstract": str(row.get("abstract") or ""),
                }
                for row in rows
            }
    finally:
        driver.close()


def sample_ec_questions(limit: int, rng: random.Random) -> list[dict[str, Any]]:
    driver = get_driver()
    try:
        with driver.session() as session:
            rows = list(
                session.run(
                    """
                    MATCH (e:Enzyme)
                    WHERE e.ec IS NOT NULL
                    OPTIONAL MATCH (p:Protein)-[:HAS_EC]->(e)
                    WITH e, collect(DISTINCT coalesce(
                        p.`Gene Names (primary)`,
                        p.Entry,
                        p.`Entry Name`,
                        p.`Protein names`,
                        p.name
                    )) AS proteins
                    WHERE size([item IN proteins WHERE item IS NOT NULL]) > 0
                    CALL {
                        WITH e
                        MATCH (pathway:Pathway)-[:HAS_ENZYME]->(e)
                        RETURN collect(DISTINCT pathway.name)[0..4] AS pathways
                    }
                    CALL {
                        WITH e
                        MATCH (pub:Publication)-[:MENTIONS_EC]->(e)
                        WITH pub ORDER BY toInteger(pub.pmid) DESC
                        RETURN collect(DISTINCT pub.pmid)[0..3] AS pmids
                    }
                    RETURN
                        e.ec AS ec_number,
                        coalesce(e.name, e.id, e.ec) AS enzyme_name,
                        [item IN proteins WHERE item IS NOT NULL][0..6] AS proteins,
                        pathways,
                        pmids
                    """
                )
            )
    finally:
        driver.close()

    rng.shuffle(rows)
    records: list[dict[str, Any]] = []
    for row in rows[:limit]:
        ec_number = str(row["ec_number"])
        proteins = clean_list(row["proteins"], 5)
        pathways = clean_list(row["pathways"], 3)
        pmids = clean_list(row["pmids"], 3)
        pub_map = fetch_publications_by_pmids(pmids)
        titles = [pub_map[pmid]["title"] for pmid in pmids if pmid in pub_map and pub_map[pmid]["title"]]

        reference = f"EC 编号 {ec_number} 在当前图谱中关联的代表性酶或蛋白包括：{'、'.join(proteins)}。"
        if pathways:
            reference += f" 相关代谢通路包括：{'、'.join(pathways)}。"
        if pmids:
            reference += f" 可追溯文献 PMID 包括：{', '.join(pmids)}。"

        records.append(
            {
                "question_type": "ec_to_enzyme",
                "question": f"EC 编号 {ec_number} 对应哪些酶或蛋白？请给出代表性条目并附 PMID 证据。",
                "target": {"ec_number": ec_number},
                "gold": {
                    "entities": proteins,
                    "pathways": pathways,
                    "pmids": pmids,
                    "publication_titles": titles[:3],
                },
                "reference_answer": reference,
                "annotation_status": "graph_verified",
            }
        )
    return records


def sample_pathway_questions(limit: int, rng: random.Random) -> list[dict[str, Any]]:
    driver = get_driver()
    try:
        with driver.session() as session:
            rows = list(
                session.run(
                    """
                    MATCH (pathway:Pathway)-[:HAS_ENZYME]->(e:Enzyme)
                    WITH
                        pathway,
                        collect(DISTINCT coalesce(e.name, e.id, e.ec))[0..8] AS enzymes,
                        collect(DISTINCT e.ec)[0..8] AS ecs,
                        count(DISTINCT e) AS enzyme_count
                    WHERE enzyme_count >= 3
                    OPTIONAL MATCH (pathway)-[:HAS_ENZYME]->(:Enzyme)<-[:MENTIONS_EC]-(pub:Publication)
                    WITH pathway, enzymes, ecs, collect(DISTINCT pub.pmid) AS pmids
                    RETURN
                        pathway.name AS pathway_name,
                        enzymes,
                        ecs,
                        [item IN pmids WHERE item IS NOT NULL][0..3] AS pmids
                    """
                )
            )
    finally:
        driver.close()

    rng.shuffle(rows)
    records: list[dict[str, Any]] = []
    for row in rows[:limit]:
        pathway_name = str(row["pathway_name"])
        enzymes = clean_list(row["enzymes"], 6)
        ecs = clean_list(row["ecs"], 6)
        pmids = clean_list(row["pmids"], 3)
        reference = f"{pathway_name} 在当前知识图谱中的关键酶包括：{'、'.join(enzymes)}。"
        if ecs:
            reference += f" 对应 EC 编号示例为：{', '.join(ecs)}。"
        if pmids:
            reference += f" 相关证据文献 PMID 包括：{', '.join(pmids)}。"

        records.append(
            {
                "question_type": "pathway_to_enzymes",
                "question": f"特定代谢通路“{pathway_name}”包含哪些关键酶？请结合 PMID 证据概括回答。",
                "target": {"pathway_name": pathway_name},
                "gold": {"entities": enzymes, "ec_numbers": ecs, "pmids": pmids},
                "reference_answer": reference,
                "annotation_status": "graph_verified",
            }
        )
    return records


def sample_compound_questions(limit: int, rng: random.Random) -> list[dict[str, Any]]:
    driver = get_driver()
    try:
        with driver.session() as session:
            rows = list(
                session.run(
                    """
                    MATCH (compound:Compound)<-[:HAS_COMPOUND]-(pathway:Pathway)-[:HAS_ENZYME]->(enzyme:Enzyme)
                    WHERE compound.id IS NOT NULL
                    WITH
                        compound,
                        collect(DISTINCT pathway.name)[0..4] AS pathways,
                        collect(DISTINCT enzyme.ec)[0..6] AS ecs,
                        count(DISTINCT pathway) AS pathway_count
                    WHERE pathway_count > 0
                    OPTIONAL MATCH (compound)<-[:HAS_COMPOUND]-(:Pathway)-[:HAS_ENZYME]->(:Enzyme)<-[:MENTIONS_EC]-(pub:Publication)
                    WITH compound, pathways, ecs, collect(DISTINCT pub.pmid) AS pmids
                    WHERE size([item IN pmids WHERE item IS NOT NULL]) > 0
                    RETURN
                        compound.id AS compound_id,
                        pathways,
                        ecs,
                        [item IN pmids WHERE item IS NOT NULL][0..3] AS pmids
                    """
                )
            )
    finally:
        driver.close()

    rng.shuffle(rows)
    records: list[dict[str, Any]] = []
    for row in rows[:limit]:
        compound_id = str(row["compound_id"])
        pathways = clean_list(row["pathways"], 3)
        ecs = clean_list(row["ecs"], 4)
        pmids = clean_list(row["pmids"], 3)
        pub_map = fetch_publications_by_pmids(pmids)
        titles = [pub_map[pmid]["title"] for pmid in pmids if pmid in pub_map and pub_map[pmid]["title"]]
        reference = f"与化合物 {compound_id} 相关的最新文献 PMID 包括：{', '.join(pmids)}。"
        if pathways:
            reference += f" 这些证据主要关联通路 {'、'.join(pathways)}。"

        records.append(
            {
                "question_type": "compound_to_latest_literature",
                "question": f"请查找与化合物 {compound_id} 相关的最新文献，并给出 PMID 与简要说明。",
                "target": {"compound_id": compound_id},
                "gold": {
                    "pathways": pathways,
                    "ec_numbers": ecs,
                    "pmids": pmids,
                    "publication_titles": titles[:3],
                },
                "reference_answer": reference,
                "annotation_status": "graph_verified",
            }
        )
    return records


def build_dataset(seed: int, ec_count: int, pathway_count: int, compound_count: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    records.extend(sample_ec_questions(ec_count, rng))
    records.extend(sample_pathway_questions(pathway_count, rng))
    records.extend(sample_compound_questions(compound_count, rng))

    for index, record in enumerate(records[:100], start=1):
        record["question_id"] = f"QA{index:03d}"
    return records[:100]


def write_summary(records: list[dict[str, Any]], path: Path) -> None:
    rows = []
    for record in records:
        gold = record["gold"]
        rows.append(
            {
                "question_id": record["question_id"],
                "question_type": record["question_type"],
                "question": record["question"],
                "gold_entities": " | ".join(gold.get("entities", [])),
                "gold_ec_numbers": " | ".join(gold.get("ec_numbers", [])),
                "gold_pmids": " | ".join(gold.get("pmids", [])),
                "reference_answer": record["reference_answer"],
            }
        )
    write_csv(
        path,
        rows,
        ["question_id", "question_type", "question", "gold_entities", "gold_ec_numbers", "gold_pmids", "reference_answer"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the 100-question dataset for Table 6-2.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ec-count", type=int, default=34)
    parser.add_argument("--pathway-count", type=int, default=33)
    parser.add_argument("--compound-count", type=int, default=33)
    args = parser.parse_args()

    records = build_dataset(args.seed, args.ec_count, args.pathway_count, args.compound_count)
    write_jsonl(args.output, records)
    write_summary(records, args.summary)
    print(f"Wrote {len(records)} questions to {args.output}")
    print(f"Wrote summary to {args.summary}")


if __name__ == "__main__":
    main()
