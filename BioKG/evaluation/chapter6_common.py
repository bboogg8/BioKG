from __future__ import annotations

import csv
import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BIOKG_ROOT = PROJECT_ROOT / "BioKG"
for path in (PROJECT_ROOT, BIOKG_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

try:
    from BioKG.neo4j_utils.neo4j_conn import get_driver
except ModuleNotFoundError:
    from neo4j_utils.neo4j_conn import get_driver


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
RESULTS_DIR = ROOT_DIR / "results"
OLLAMA_URL = "http://localhost:11434/api/generate"
EC_PATTERN = re.compile(r"\b\d+\.\d+\.\d+\.\d+\b")
PMID_PATTERN = re.compile(r"\bPMID[:\s]*([0-9]{6,9})\b", flags=re.I)
PLAIN_PMID_PATTERN = re.compile(r"\b([0-9]{6,9})\b")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path: str | Path, records: list[dict[str, Any]]) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I).strip()


def call_ollama(
    prompt: str,
    model_name: str = "deepseek-r1:7b",
    *,
    num_predict: int = 180,
    temperature: float = 0.1,
    timeout: int = 180,
) -> str:
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        },
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    return strip_think_tags(body.get("response", ""))


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[^A-Z0-9]+", "", text.upper())


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def publication_title_from_abstract(abstract: str | None) -> str:
    if not abstract:
        return ""
    for raw_line in abstract.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("doi:"):
            continue
        if re.match(r"^\d+\.\s", line):
            continue
        if len(line) < 8:
            continue
        return line.rstrip(".")
    return abstract.strip().split(".")[0].strip()


def extract_ec_numbers(text: str) -> list[str]:
    return dedupe_keep_order(EC_PATTERN.findall(text or ""))


def extract_pmids(text: str) -> list[str]:
    pmids = [match.group(1) for match in PMID_PATTERN.finditer(text or "")]
    if pmids:
        return dedupe_keep_order(pmids)
    return dedupe_keep_order(PLAIN_PMID_PATTERN.findall(text or ""))


def tokenize_for_bleu(text: str) -> list[str]:
    text = strip_think_tags(text)
    return [token for token in re.findall(r"[A-Za-z0-9\.]+|[\u4e00-\u9fff]", text) if token.strip()]


def bleu4(reference: str, hypothesis: str) -> float:
    ref_tokens = tokenize_for_bleu(reference)
    hyp_tokens = tokenize_for_bleu(hypothesis)
    if not ref_tokens or not hyp_tokens:
        return 0.0

    weights = [0.25, 0.25, 0.25, 0.25]
    precisions: list[float] = []

    for n in range(1, 5):
        ref_counts = Counter(tuple(ref_tokens[i : i + n]) for i in range(max(len(ref_tokens) - n + 1, 0)))
        hyp_counts = Counter(tuple(hyp_tokens[i : i + n]) for i in range(max(len(hyp_tokens) - n + 1, 0)))
        if not hyp_counts:
            precisions.append(1e-9)
            continue

        overlap = 0
        for gram, count in hyp_counts.items():
            overlap += min(count, ref_counts.get(gram, 0))
        precisions.append((overlap + 1) / (sum(hyp_counts.values()) + 1))

    ref_len = len(ref_tokens)
    hyp_len = len(hyp_tokens)
    brevity_penalty = 1.0 if hyp_len > ref_len else math.exp(1 - (ref_len / max(hyp_len, 1)))
    score = brevity_penalty * math.exp(sum(w * math.log(p) for w, p in zip(weights, precisions)))
    return float(score)


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return ordered[int(idx)]
    frac = idx - lower
    return ordered[lower] * (1 - frac) + ordered[upper] * frac


def markdown_table(rows: list[dict[str, Any]], headers: list[tuple[str, str]]) -> str:
    header_line = "| " + " | ".join(label for _, label in headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(key, "")) for key, _ in headers) + " |")
    return "\n".join([header_line, sep_line, *body])


def load_graph_vocabulary() -> dict[str, set[str]]:
    driver = get_driver()
    try:
        with driver.session() as session:
            vocabulary = {
                "ec_numbers": set(),
                "proteins": set(),
                "pathways": set(),
                "compounds": set(),
                "pmids": set(),
            }

            for row in session.run(
                """
                MATCH (e:Enzyme)
                WHERE e.ec IS NOT NULL
                RETURN DISTINCT e.ec AS ec
                """
            ):
                vocabulary["ec_numbers"].add(str(row["ec"]))

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
                for key in ("gene_primary", "entry", "entry_name", "protein_name"):
                    value = row.get(key)
                    if value:
                        vocabulary["proteins"].add(str(value))
                        if key == "entry_name" and "_" in str(value):
                            vocabulary["proteins"].add(str(value).split("_", 1)[0])

            for row in session.run("MATCH (p:Pathway) WHERE p.name IS NOT NULL RETURN DISTINCT p.name AS name"):
                name = str(row["name"])
                vocabulary["pathways"].add(name)
                vocabulary["pathways"].add(name.split(" - ", 1)[0])

            for row in session.run("MATCH (c:Compound) WHERE c.id IS NOT NULL RETURN DISTINCT c.id AS compound_id"):
                vocabulary["compounds"].add(str(row["compound_id"]))

            for row in session.run("MATCH (p:Publication) WHERE p.pmid IS NOT NULL RETURN DISTINCT p.pmid AS pmid"):
                vocabulary["pmids"].add(str(row["pmid"]))

            return vocabulary
    finally:
        driver.close()


def measure_runtime(fn, repetitions: int) -> list[float]:
    samples: list[float] = []
    for _ in range(repetitions):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


def summarize_latency(samples_ms: list[float]) -> dict[str, float]:
    avg = mean(samples_ms)
    p95 = percentile(samples_ms, 0.95)
    qps = 1000.0 / avg if avg else 0.0
    return {
        "mean_ms": round(avg, 2),
        "p95_ms": round(p95, 2),
        "qps": round(qps, 2),
    }


def format_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def format_float(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def improvement_text(base: float | None, new: float | None, *, percent_points: bool = True) -> str:
    if base is None or new is None:
        return "N/A"
    delta = new - base
    if percent_points:
        return f"{delta * 100:+.1f}pp"
    if abs(base) < 1e-9:
        return "N/A"
    return f"{(delta / base) * 100:+.1f}%"
