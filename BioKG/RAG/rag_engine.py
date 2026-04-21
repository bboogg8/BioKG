import re
from typing import Any

import requests

try:
    from BioKG.neo4j_utils.neo4j_conn import get_driver
except ModuleNotFoundError:
    from neo4j_utils.neo4j_conn import get_driver


OLLAMA_URL = "http://localhost:11434/api/generate"
EC_PATTERN = re.compile(r"^\d+(?:\.\d+){2,3}$")


CANDIDATE_WHERE = """
WHERE (candidate:Protein OR candidate:Enzyme) AND (
    toUpper(coalesce(candidate.name, "")) = toUpper($name) OR
    toUpper(coalesce(candidate.Entry, "")) = toUpper($name) OR
    toUpper(coalesce(candidate.`Entry Name`, "")) = toUpper($name) OR
    toUpper(coalesce(candidate.`Gene Names (primary)`, "")) = toUpper($name) OR
    toUpper(coalesce(candidate.`Protein names`, "")) = toUpper($name) OR
    toUpper(toString(coalesce(candidate.id, ""))) = toUpper($name) OR
    toUpper(toString(coalesce(candidate.`EC number`, ""))) = toUpper($name) OR
    toUpper(toString(coalesce(candidate.ec, ""))) = toUpper($name) OR
    toUpper(coalesce(candidate.Entry, "")) CONTAINS toUpper($name) OR
    toUpper(coalesce(candidate.`Entry Name`, "")) CONTAINS toUpper($name) OR
    toUpper(coalesce(candidate.`Protein names`, "")) CONTAINS toUpper($name) OR
    toUpper(coalesce(candidate.`Gene Names`, "")) CONTAINS toUpper($name) OR
    toUpper(coalesce(candidate.`Gene Names (primary)`, "")) CONTAINS toUpper($name) OR
    toUpper(toString(coalesce(candidate.id, ""))) CONTAINS toUpper($name) OR
    toUpper(toString(coalesce(candidate.`EC number`, ""))) CONTAINS toUpper($name) OR
    toUpper(toString(coalesce(candidate.ec, ""))) CONTAINS toUpper($name)
)
"""


CANDIDATE_PRIORITY = """
CASE
    WHEN candidate:Enzyme AND toUpper(toString(coalesce(candidate.id, ""))) = toUpper($name) THEN 0
    WHEN candidate:Enzyme AND toUpper(toString(coalesce(candidate.ec, ""))) = toUpper($name) THEN 1
    WHEN candidate:Enzyme AND toUpper(toString(coalesce(candidate.`EC number`, ""))) = toUpper($name) THEN 2
    WHEN candidate:Enzyme AND toUpper(coalesce(candidate.name, "")) = toUpper($name) THEN 3
    WHEN candidate:Enzyme AND toUpper(coalesce(candidate.`Entry Name`, "")) = toUpper($name) THEN 4
    WHEN candidate:Protein AND toUpper(coalesce(candidate.`Gene Names (primary)`, "")) = toUpper($name) THEN 5
    WHEN candidate:Protein AND toUpper(coalesce(candidate.Entry, "")) = toUpper($name) THEN 6
    WHEN candidate:Protein AND toUpper(coalesce(candidate.`Entry Name`, "")) = toUpper($name) THEN 7
    WHEN candidate:Protein AND toUpper(coalesce(candidate.`Protein names`, "")) = toUpper($name) THEN 8
    WHEN candidate:Protein AND toUpper(coalesce(candidate.name, "")) = toUpper($name) THEN 9
    WHEN candidate:Protein AND toUpper(toString(coalesce(candidate.id, ""))) = toUpper($name) THEN 10
    WHEN candidate:Protein AND toUpper(toString(coalesce(candidate.`EC number`, ""))) = toUpper($name) THEN 11
    WHEN candidate:Protein AND toUpper(toString(coalesce(candidate.ec, ""))) = toUpper($name) THEN 12
    WHEN candidate:Enzyme AND toUpper(toString(coalesce(candidate.id, ""))) CONTAINS toUpper($name) THEN 13
    WHEN candidate:Enzyme AND toUpper(toString(coalesce(candidate.ec, ""))) CONTAINS toUpper($name) THEN 14
    WHEN candidate:Enzyme AND toUpper(toString(coalesce(candidate.`EC number`, ""))) CONTAINS toUpper($name) THEN 15
    WHEN candidate:Protein AND toUpper(coalesce(candidate.`Protein names`, "")) CONTAINS toUpper($name) THEN 16
    WHEN candidate:Protein AND toUpper(coalesce(candidate.`Gene Names`, "")) CONTAINS toUpper($name) THEN 17
    WHEN candidate:Protein AND toUpper(coalesce(candidate.`Gene Names (primary)`, "")) CONTAINS toUpper($name) THEN 18
    WHEN candidate:Protein AND toUpper(coalesce(candidate.`Entry Name`, "")) CONTAINS toUpper($name) THEN 19
    WHEN candidate:Protein AND toUpper(coalesce(candidate.Entry, "")) CONTAINS toUpper($name) THEN 20
    WHEN candidate:Protein AND toUpper(toString(coalesce(candidate.id, ""))) CONTAINS toUpper($name) THEN 21
    WHEN candidate:Protein AND toUpper(toString(coalesce(candidate.`EC number`, ""))) CONTAINS toUpper($name) THEN 22
    WHEN candidate:Protein AND toUpper(toString(coalesce(candidate.ec, ""))) CONTAINS toUpper($name) THEN 23
    ELSE 99
END
"""


def _deduplicate_lines(raw_response: str) -> str:
    lines = raw_response.splitlines()
    seen_lines: set[str] = set()
    deduplicated_lines: list[str] = []

    for line in lines:
        stripped_line = line.strip()
        if stripped_line and stripped_line not in seen_lines:
            deduplicated_lines.append(line)
            seen_lines.add(stripped_line)
        elif not stripped_line:
            deduplicated_lines.append(line)

    return "\n".join(deduplicated_lines)


def _call_ollama(prompt: str, model_name: str = "deepseek-r1:7b", timeout: int = 120) -> str:
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    response.raise_for_status()
    result = response.json()
    return result.get("response", "")


def generate_answer_with_ollama(prompt, model_name="deepseek-r1:7b"):
    try:
        raw_response = _call_ollama(prompt, model_name=model_name, timeout=120)
        if not raw_response.strip():
            return "模型未能返回任何内容。"
        return _deduplicate_lines(raw_response)
    except requests.exceptions.ConnectionError:
        return "无法连接到 Ollama，请确认后台已启动 `ollama run deepseek-r1:7b`。"
    except Exception as exc:
        return f"LLM 调用异常: {exc}"


def _is_ec_like(value: str | None) -> bool:
    return bool(value and EC_PATTERN.fullmatch(str(value).strip()))


def _clean_values(values) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if text not in seen:
            cleaned.append(text)
            seen.add(text)
    return cleaned


def _normalize_entry_name(value: str) -> str:
    value = value.strip()
    if "_" in value:
        return value.split("_", 1)[0]
    return value


def _strip_embedded_ec_suffix(value: str, ec_number: str | None) -> str:
    text = value.strip()
    if not ec_number:
        return text
    pattern = rf"\s*\(EC\s*{re.escape(ec_number)}\)\s*$"
    return re.sub(pattern, "", text, flags=re.I)


def _build_short_protein_name(
    full_name: str | None,
    ec_number: str | None,
    gene_primary: str | None = None,
    entry_name: str | None = None,
) -> str | None:
    if not full_name and not gene_primary and not entry_name:
        return None

    alias = (gene_primary or "").strip()
    if not alias and entry_name:
        alias = _normalize_entry_name(entry_name)

    if full_name:
        cleaned = _strip_embedded_ec_suffix(full_name, ec_number)
        base_name = re.split(r"\s+\(", cleaned, maxsplit=1)[0].strip()
    else:
        base_name = ""

    if not base_name:
        return alias or None

    if alias and alias.upper() not in base_name.upper():
        return f"{base_name} ({alias})"
    return base_name


def _summarize_protein_names(
    protein_full_names: list[str],
    ec_number: str | None,
) -> list[str]:
    summarized: list[str] = []
    seen: set[str] = set()
    for full_name in protein_full_names:
        short_name = _build_short_protein_name(full_name, ec_number)
        if short_name and short_name not in seen:
            summarized.append(short_name)
            seen.add(short_name)
    return summarized


def _choose_report_name(
    enzyme_name: str | None,
    enzyme_id: str | None,
    ec_number: str | None,
    matched_protein_full_name: str | None,
    matched_protein_name: str | None,
    matched_protein_entry_name: str | None,
    matched_protein_gene_primary: str | None,
    protein_full_names: list[str],
    protein_names: list[str],
    protein_entry_names: list[str],
    protein_gene_names: list[str],
) -> tuple[str | None, str]:
    for candidate in _clean_values([enzyme_id, enzyme_name]):
        if not _is_ec_like(candidate):
            return candidate, "关联 Enzyme 节点"

    for candidate in _clean_values([matched_protein_full_name]):
        normalized = _build_short_protein_name(
            candidate,
            ec_number,
            gene_primary=matched_protein_gene_primary,
            entry_name=matched_protein_entry_name,
        )
        if normalized:
            return normalized, "命中 Protein 节点"

    for candidate in _clean_values([matched_protein_name]):
        if not _is_ec_like(candidate):
            return candidate, "命中 Protein 节点"

    for candidate in _clean_values([matched_protein_entry_name]):
        normalized = _normalize_entry_name(candidate)
        if normalized and not _is_ec_like(normalized):
            return normalized, "命中 Protein 节点"

    for raw_value in _clean_values([matched_protein_gene_primary]):
        for token in raw_value.split():
            if token and not _is_ec_like(token):
                return token, "命中 Protein 节点"

    for candidate in _clean_values(protein_full_names):
        normalized = _build_short_protein_name(candidate, ec_number)
        if normalized:
            return normalized, "关联 Protein 节点"

    for candidate in _clean_values(protein_names):
        if not _is_ec_like(candidate):
            return candidate, "关联 Protein 节点"

    for candidate in _clean_values(protein_entry_names):
        normalized = _normalize_entry_name(candidate)
        if normalized and not _is_ec_like(normalized):
            return normalized, "关联 Protein 节点"

    for raw_value in _clean_values(protein_gene_names):
        for token in raw_value.split():
            if token and not _is_ec_like(token):
                return token, "关联 Protein 节点"

    fallback_candidates = _clean_values([ec_number, enzyme_id, enzyme_name])
    return (fallback_candidates[0] if fallback_candidates else None), "EC 编号"


def _extract_candidate_name(raw_text: str) -> str | None:
    if not raw_text:
        return None

    text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.S | re.I).strip()
    if not text:
        return None

    for line in text.splitlines():
        candidate = line.strip().strip("`\"' ")
        candidate = re.sub(
            r"^(候选酶名|候选名称|标准名称|名称|enzyme name|candidate name)\s*[:：]\s*",
            "",
            candidate,
            flags=re.I,
        )
        if not candidate:
            continue
        upper_candidate = candidate.upper()
        if upper_candidate in {"UNKNOWN", "N/A", "NONE"}:
            return None
        if "无法确定" in candidate or "不确定" in candidate or "UNKNOWN" in upper_candidate:
            return None
        if len(candidate) > 120:
            continue
        return candidate

    return None


def _infer_candidate_enzyme_name(
    ec_number: str | None,
    pathways: list[str],
    protein_full_names: list[str],
    protein_names: list[str],
    model_name: str = "deepseek-r1:7b",
) -> str | None:
    if not ec_number:
        return None

    prompt = (
        "你是生物化学命名助手。请根据给定 EC 编号和上下文，推断该酶最可能的常用名称。"
        "如果无法较有把握地判断，只输出 UNKNOWN。\n\n"
        f"EC 编号: {ec_number}\n"
        f"相关通路: {', '.join(_clean_values(pathways)[:8]) or '无'}\n"
        f"关联 Protein 全称: {', '.join(_clean_values(protein_full_names)[:5]) or '无'}\n"
        f"关联 Protein 名称: {', '.join(_clean_values(protein_names)[:5]) or '无'}\n\n"
        "只输出一行候选酶名，不要解释。"
    )

    try:
        raw_text = _call_ollama(prompt, model_name=model_name, timeout=45)
    except Exception:
        return None

    candidate_name = _extract_candidate_name(raw_text)
    if candidate_name and not _is_ec_like(candidate_name):
        return candidate_name
    return None


def _format_candidate_display(candidate: dict[str, Any]) -> str:
    ec_number = candidate.get("ec_number") or "N/A"
    candidate_label = candidate.get("candidate_label") or "Node"
    match_priority = int(candidate.get("match_priority", 99))
    hint = f"命中优先级 {match_priority}"

    if candidate_label == "Protein":
        protein_full_name = candidate.get("protein_names")
        entry_name = candidate.get("entry_name")
        gene_primary = candidate.get("gene_primary")
        title = _build_short_protein_name(
            str(protein_full_name) if protein_full_name else None,
            ec_number,
            gene_primary=gene_primary,
            entry_name=entry_name,
        )
        title = title or gene_primary or (_normalize_entry_name(entry_name) if entry_name else None)
        title = title or candidate.get("entry") or candidate.get("candidate_name") or f"Protein -> EC {ec_number}"
        return f"{title} | Protein -> EC {ec_number} | {hint}"

    enzyme_name = candidate.get("candidate_name")
    enzyme_id = candidate.get("enzyme_id")
    title = enzyme_name or enzyme_id or f"EC {ec_number}"
    return f"{title} | Enzyme | EC {ec_number} | {hint}"


def search_report_candidates(query_text: str, limit: int = 8) -> list[dict[str, Any]]:
    driver = get_driver()
    query = f"""
    MATCH (candidate)
    {CANDIDATE_WHERE}
    WITH candidate, {CANDIDATE_PRIORITY} AS match_priority
    ORDER BY match_priority, elementId(candidate)
    LIMIT $limit

    OPTIONAL MATCH (candidate)-[:HAS_EC]->(linked_enzyme:Enzyme)
    WITH candidate, CASE WHEN candidate:Enzyme THEN candidate ELSE linked_enzyme END AS enzyme, match_priority
    WHERE enzyme:Enzyme

    RETURN
        elementId(candidate) AS candidate_node_id,
        labels(candidate)[0] AS candidate_label,
        match_priority,
        coalesce(enzyme.id, enzyme.ec) AS enzyme_id,
        coalesce(enzyme.`EC number`, enzyme.ec, enzyme.id, "N/A") AS ec_number,
        candidate.name AS candidate_name,
        candidate.Entry AS entry,
        candidate.`Entry Name` AS entry_name,
        candidate.`Protein names` AS protein_names,
        candidate.`Gene Names (primary)` AS gene_primary,
        candidate.`Gene Names` AS gene_names
    """

    try:
        with driver.session() as session:
            rows = [record.data() for record in session.run(query, name=query_text, limit=int(limit))]
    finally:
        driver.close()

    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (
            row.get("candidate_node_id"),
            row.get("enzyme_id"),
            row.get("candidate_label"),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        row["display"] = _format_candidate_display(row)
        candidates.append(row)
    return candidates


def _fetch_report_record(
    *,
    query_text: str | None = None,
    candidate_node_id: str | None = None,
) -> dict[str, Any] | None:
    if candidate_node_id is not None:
        match_clause = "MATCH (candidate) WHERE elementId(candidate) = $candidate_node_id AND (candidate:Protein OR candidate:Enzyme)"
    else:
        match_clause = f"""
        MATCH (candidate)
        {CANDIDATE_WHERE}
        WITH candidate, {CANDIDATE_PRIORITY} AS match_priority
        ORDER BY match_priority, elementId(candidate)
        LIMIT 1
        """

    query = f"""
    {match_clause}

    OPTIONAL MATCH (candidate)-[:HAS_EC]->(matched_enzyme:Enzyme)
    WITH candidate, CASE WHEN candidate:Enzyme THEN candidate ELSE matched_enzyme END AS enzyme
    WHERE enzyme:Enzyme

    OPTIONAL MATCH (protein:Protein)-[:HAS_EC]->(enzyme)
    WITH
        candidate,
        enzyme,
        collect(DISTINCT protein.name) AS protein_names,
        collect(DISTINCT protein.`Protein names`) AS protein_full_names,
        collect(DISTINCT protein.`Entry Name`) AS protein_entry_names,
        collect(DISTINCT protein.`Gene Names`) AS protein_gene_names

    OPTIONAL MATCH (enzyme)-[r:MENTIONS_EC]-(p:Publication)
    WITH candidate, enzyme, protein_names, protein_full_names, protein_entry_names, protein_gene_names, p, r
    ORDER BY p.pmid DESC

    OPTIONAL MATCH (enzyme)--(linked)
    RETURN
        coalesce(enzyme.id, enzyme.ec) AS enzyme_id,
        enzyme.name AS enzyme_name,
        coalesce(enzyme.`EC number`, enzyme.ec, enzyme.id, "N/A") AS ec_number,
        candidate.name AS matched_candidate_name,
        candidate.`Protein names` AS matched_candidate_protein_name,
        candidate.`Entry Name` AS matched_candidate_entry_name,
        candidate.`Gene Names (primary)` AS matched_candidate_gene_primary,
        protein_names,
        protein_full_names,
        protein_entry_names,
        protein_gene_names,
        collect(DISTINCT CASE WHEN 'Pathway' IN labels(linked) THEN linked.name END) AS pathways,
        collect(DISTINCT CASE WHEN 'Compound' IN labels(linked) THEN linked.name END) AS compounds,
        collect(DISTINCT {{pmid: p.pmid, abstract: p.abstract, method: r.method}})[0..3] AS lit_evidence
    """

    driver = get_driver()
    params = {"name": query_text, "candidate_node_id": candidate_node_id}
    try:
        with driver.session() as session:
            record = session.run(query, params).single()
            return record.data() if record else None
    finally:
        driver.close()


def get_knowledge_context(enzyme_name, model_name="deepseek-r1:7b", candidate_node_id: str | None = None):
    try:
        record = _fetch_report_record(query_text=enzyme_name, candidate_node_id=candidate_node_id)
        if not record:
            return f"抱歉，当前图谱中尚未找到与 '{enzyme_name}' 相关的数据。"

        enzyme_id = record["enzyme_id"]
        enzyme_graph_name = record["enzyme_name"]
        ec_num = record["ec_number"]
        matched_candidate_name = record["matched_candidate_name"]
        matched_candidate_protein_name = record["matched_candidate_protein_name"]
        matched_candidate_entry_name = record["matched_candidate_entry_name"]
        matched_candidate_gene_primary = record["matched_candidate_gene_primary"]
        pathways = _clean_values(record["pathways"])
        compounds = _clean_values(record["compounds"])
        evidence = record["lit_evidence"] or []
        protein_full_names = _clean_values(record["protein_full_names"])
        protein_names = _clean_values(record["protein_names"])
        protein_entry_names = _clean_values(record["protein_entry_names"])
        protein_gene_names = _clean_values(record["protein_gene_names"])
        summarized_protein_names = _summarize_protein_names(protein_full_names, ec_num)

        report_name, name_source = _choose_report_name(
            enzyme_name=enzyme_graph_name,
            enzyme_id=enzyme_id,
            ec_number=ec_num,
            matched_protein_full_name=matched_candidate_protein_name,
            matched_protein_name=matched_candidate_name,
            matched_protein_entry_name=matched_candidate_entry_name,
            matched_protein_gene_primary=matched_candidate_gene_primary,
            protein_full_names=protein_full_names,
            protein_names=protein_names,
            protein_entry_names=protein_entry_names,
            protein_gene_names=protein_gene_names,
        )

        if name_source == "EC 编号":
            inferred_name = _infer_candidate_enzyme_name(
                ec_number=ec_num,
                pathways=pathways,
                protein_full_names=protein_full_names,
                protein_names=protein_names,
                model_name=model_name,
            )
            if inferred_name:
                report_name = inferred_name
                name_source = "LLM 推断"

        display_name = report_name or ec_num or enzyme_name
        if name_source == "LLM 推断":
            target_line = f"目标实体：{display_name} [候选名] (EC: {ec_num})"
        elif ec_num and display_name != ec_num:
            target_line = f"目标实体：{display_name} (EC: {ec_num})"
        else:
            target_line = f"目标实体：EC {ec_num}"

        prompt_lines = ["### [BioKG 专家系统检索报告] ###", "", target_line]
        if name_source == "关联 Enzyme 节点" and display_name:
            prompt_lines.append(f"标准名称（Enzyme 节点）：{display_name}")
        elif name_source == "命中 Protein 节点" and display_name:
            prompt_lines.append(f"参考名称（命中 Protein 节点）：{display_name}")
        elif name_source == "关联 Protein 节点" and display_name:
            prompt_lines.append(f"参考名称（关联 Protein 节点）：{display_name}")
        elif name_source == "LLM 推断" and display_name:
            prompt_lines.append(f"候选酶名（LLM 推断，非图谱标准字段）：{display_name}")

        if enzyme_id and enzyme_id != display_name:
            prompt_lines.append(f"Enzyme 节点标识：{enzyme_id}")

        if summarized_protein_names:
            prompt_lines.append(f"关联 Protein：{', '.join(summarized_protein_names[:5])}")
        elif protein_full_names:
            prompt_lines.append(f"关联 Protein：{', '.join(protein_full_names[:5])}")
        elif protein_names:
            prompt_lines.append(f"关联 Protein 名称：{', '.join(protein_names[:5])}")

        if pathways:
            prompt_lines.append(f"涉及代谢通路：{', '.join(pathways)}")
        if compounds:
            prompt_lines.append(f"相关化学物质：{', '.join(compounds[:10])}")

        prompt_lines.append("")
        prompt_lines.append("以下是从 PubMed 检索到的最新科研证据：")

        context_lines: list[str] = []
        for index, paper in enumerate(evidence, start=1):
            pmid = paper.get("pmid")
            abstract = (paper.get("abstract") or "").replace("\n", " ").strip()
            method = paper.get("method") or "Unknown"
            if not pmid or not abstract:
                continue
            context_lines.append(
                f"\n证据 {index} [PMID: {pmid}] (匹配方法: {method}):\n{abstract[:600]}...\n"
            )

        if not context_lines:
            return f"找到了 '{display_name or ec_num}' 的静态信息，但暂无关联文献。请运行 --update 获取更多背景。"

        prompt_lines.extend(context_lines)
        prompt_lines.append("")
        prompt_lines.append("--- 任务要求 ---")
        prompt_lines.append("1. 请严格基于提供的证据进行总结。")
        prompt_lines.append("2. 在描述关键发现时，必须在括号内标注 PMID，例如 [PMID: xxxxx]。")
        prompt_lines.append("3. 如果给出了通路信息，请优先说明该酶在这些通路中的作用。")
        prompt_lines.append("4. 如果名称被标记为“参考名称”或“候选酶名”，请保留该限定，不要将其表述为图谱中已确认的 Enzyme 标准名称。")

        return "\n".join(prompt_lines)
    except Exception as exc:
        return f"数据库检索失败: {exc}"
