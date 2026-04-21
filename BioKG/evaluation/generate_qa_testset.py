from __future__ import annotations

import argparse
import random
from pathlib import Path

from chapter6_common import DATA_DIR, ensure_dirs, publication_title_from_abstract, write_csv, write_jsonl

try:
    from BioKG.neo4j_utils.neo4j_conn import get_driver
except ModuleNotFoundError:
    from neo4j_utils.neo4j_conn import get_driver


DEFAULT_OUTPUT = DATA_DIR / "qa_eval_100.jsonl"
DEFAULT_SUMMARY = DATA_DIR / "qa_eval_100_summary.csv"


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
            result = {}
            for row in rows:
                abstract = row.get("abstract") or ""
                result[str(row["pmid"])] = {
                    "title": publication_title_from_abstract(abstract),
                    "abstract": abstract,
                }
            return result
    finally:
        driver.close()


def sample_ec_questions(limit: int, rng: random.Random) -> list[dict]:
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
                    WHERE size([x IN proteins WHERE x IS NOT NULL]) > 0
                    CALL {
                        WITH e
                        MATCH (pwy:Pathway)-[:HAS_ENZYME]->(e)
                        RETURN collect(DISTINCT pwy.name)[0..4] AS pathways
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
                        [x IN proteins WHERE x IS NOT NULL][0..6] AS proteins,
                        pathways,
                        pmids
                    """
                )
            )
    finally:
        driver.close()

    rng.shuffle(rows)
    records: list[dict] = []
    for row in rows[:limit]:
        ec_number = str(row["ec_number"])
        proteins = [str(item) for item in row["proteins"] if item]
        pathways = [str(item) for item in row["pathways"] if item]
        pmids = [str(item) for item in row["pmids"] if item]
        pub_map = fetch_publications_by_pmids(pmids)
        publication_titles = [pub_map[pmid]["title"] for pmid in pmids if pmid in pub_map and pub_map[pmid]["title"]]
        reference = (
            f"EC 编号 {ec_number} 在当前图谱中关联的代表性酶/蛋白包括："
            f"{'、'.join(proteins[:5])}。"
        )
        if pathways:
            reference += f" 其相关代谢通路包括：{'、'.join(pathways[:3])}。"
        if pmids:
            reference += f" 可追溯文献 PMID 包括：{', '.join(pmids[:3])}。"

        records.append(
            {
                "question_type": "ec_to_enzyme",
                "question": f"EC 编号 {ec_number} 对应哪些酶或蛋白？请给出代表性条目并附 PMID 证据。",
                "target": {"ec_number": ec_number},
                "gold": {
                    "entities": proteins[:5],
                    "pathways": pathways[:3],
                    "pmids": pmids[:3],
                    "publication_titles": publication_titles[:3],
                },
                "reference_answer": reference,
                "annotation_status": "graph_verified",
            }
        )
    return records


def sample_pathway_questions(limit: int, rng: random.Random) -> list[dict]:
    driver = get_driver()
    try:
        with driver.session() as session:
            rows = list(
                session.run(
                    """
                    MATCH (pwy:Pathway)-[:HAS_ENZYME]->(e:Enzyme)
                    WITH
                        pwy,
                        collect(DISTINCT coalesce(e.name, e.id, e.ec))[0..8] AS enzymes,
                        collect(DISTINCT e.ec)[0..8] AS ecs,
                        count(DISTINCT e) AS enzyme_count
                    WHERE enzyme_count >= 3
                    OPTIONAL MATCH (pwy)-[:HAS_ENZYME]->(:Enzyme)<-[:MENTIONS_EC]-(pub:Publication)
                    WITH pwy, enzymes, ecs, enzyme_count, collect(DISTINCT pub.pmid) AS pmids
                    RETURN
                        pwy.name AS pathway_name,
                        enzymes,
                        ecs,
                        [x IN pmids WHERE x IS NOT NULL][0..3] AS pmids,
                        enzyme_count
                    """
                )
            )
    finally:
        driver.close()

    rng.shuffle(rows)
    records: list[dict] = []
    for row in rows[:limit]:
        pathway_name = str(row["pathway_name"])
        enzymes = [str(item) for item in row["enzymes"] if item]
        ecs = [str(item) for item in row["ecs"] if item]
        pmids = [str(item) for item in row["pmids"] if item]
        reference = (
            f"{pathway_name} 在当前知识图谱中的关键酶包括：{'、'.join(enzymes[:6])}。"
            f" 对应 EC 编号示例为：{', '.join(ecs[:6])}。"
        )
        if pmids:
            reference += f" 相关证据文献 PMID 包括：{', '.join(pmids[:3])}。"
        records.append(
            {
                "question_type": "pathway_to_enzymes",
                "question": f"特定代谢通路“{pathway_name}”包含哪些关键酶？请结合 PMID 证据概括回答。",
                "target": {"pathway_name": pathway_name},
                "gold": {
                    "entities": enzymes[:6],
                    "ec_numbers": ecs[:6],
                    "pmids": pmids[:3],
                },
                "reference_answer": reference,
                "annotation_status": "graph_verified",
            }
        )
    return records


def sample_compound_questions(limit: int, rng: random.Random) -> list[dict]:
    driver = get_driver()
    try:
        with driver.session() as session:
            rows = list(
                session.run(
                    """
                    MATCH (c:Compound)<-[:HAS_COMPOUND]-(pwy:Pathway)-[:HAS_ENZYME]->(e:Enzyme)
                    WHERE c.id IS NOT NULL
                    WITH
                        c,
                        collect(DISTINCT pwy.name)[0..4] AS pathways,
                        collect(DISTINCT e.ec)[0..6] AS ecs,
                        count(DISTINCT pwy) AS pathway_count
                    WHERE pathway_count > 0
                    OPTIONAL MATCH (c)<-[:HAS_COMPOUND]-(p2:Pathway)-[:HAS_ENZYME]->(:Enzyme)<-[:MENTIONS_EC]-(pub:Publication)
                    WITH c, pathways, ecs, pathway_count, collect(DISTINCT pub.pmid) AS pmids
                    WHERE size([x IN pmids WHERE x IS NOT NULL]) > 0
                    RETURN
                        c.id AS compound_id,
                        pathways,
                        ecs,
                        [x IN pmids WHERE x IS NOT NULL][0..3] AS pmids,
                        pathway_count
                    """
                )
            )
    finally:
        driver.close()

    rng.shuffle(rows)
    records: list[dict] = []
    for row in rows[:limit]:
        compound_id = str(row["compound_id"])
        pathways = [str(item) for item in row["pathways"] if item]
        ecs = [str(item) for item in row["ecs"] if item]
        pmids = [str(item) for item in row["pmids"] if item]
        pub_map = fetch_publications_by_pmids(pmids)
        publication_titles = [pub_map[pmid]["title"] for pmid in pmids if pmid in pub_map and pub_map[pmid]["title"]]
        reference = (
            f"与化合物 {compound_id} 相关的最新文献 PMID 包括：{', '.join(pmids[:3])}。"
        )
        if publication_titles:
            reference += f" 代表性题名为：{'；'.join(publication_titles[:2])}。"
        if pathways:
            reference += f" 这些证据多与通路 {'、'.join(pathways[:3])} 及 EC {', '.join(ecs[:4])} 相关。"
        records.append(
            {
                "question_type": "compound_to_latest_literature",
                "question": f"请查找与化合物 {compound_id} 相关的最新文献，并给出 PMID 与简要说明。",
                "target": {"compound_id": compound_id},
                "gold": {
                    "pathways": pathways[:3],
                    "ec_numbers": ecs[:4],
                    "pmids": pmids[:3],
                    "publication_titles": publication_titles[:3],
                },
                "reference_answer": reference,
                "annotation_status": "graph_verified",
            }
        )
    return records


def build_dataset(seed: int = 42, ec_count: int = 34, pathway_count: int = 33, compound_count: int = 33) -> list[dict]:
    rng = random.Random(seed)
    records = []
    records.extend(sample_ec_questions(ec_count, rng))
    records.extend(sample_pathway_questions(pathway_count, rng))
    records.extend(sample_compound_questions(compound_count, rng))

    for idx, record in enumerate(records, start=1):
        record["question_id"] = f"QA{idx:03d}"
    return records[:100]


def write_summary_csv(records: list[dict], path: Path) -> None:
    rows = []
    for record in records:
        rows.append(
            {
                "question_id": record["question_id"],
                "question_type": record["question_type"],
                "question": record["question"],
                "gold_entities": " | ".join(record["gold"].get("entities", [])),
                "gold_ec_numbers": " | ".join(record["gold"].get("ec_numbers", [])),
                "gold_pmids": " | ".join(record["gold"].get("pmids", [])),
                "reference_answer": record["reference_answer"],
            }
        )
    write_csv(
        path,
        rows,
        [
            "question_id",
            "question_type",
            "question",
            "gold_entities",
            "gold_ec_numbers",
            "gold_pmids",
            "reference_answer",
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成第六章问答可信度实验的 100 题评测集。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    ensure_dirs()
    records = build_dataset(seed=args.seed)
    write_jsonl(args.output, records)
    write_summary_csv(records, args.summary)
    print(f"Generated {len(records)} QA samples -> {args.output}")
    print(f"Summary CSV -> {args.summary}")


if __name__ == "__main__":
    main()
