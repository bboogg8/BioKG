# -*- coding: utf-8 -*-
# Optional interactive graph support: pip install pyvis
# Optional PNG export support requires Graphviz command line tools on PATH.

import html
import os
import re
import shutil
import subprocess
import sys
from typing import Any

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from neo4j import GraphDatabase

BIOKG_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BIOKG_ROOT)
for path in (PROJECT_ROOT, BIOKG_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from pipeline.update_pipeline import run_pipeline
from RAG.rag_engine import (
    generate_answer_with_ollama,
    get_knowledge_context,
    search_report_candidates,
)


NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "12345678")
OLLAMA_TAGS_URL = os.getenv("OLLAMA_TAGS_URL", "http://localhost:11434/api/tags")
MENTION_REL_TYPES = ["MENTIONS", "MENTIONS_EC"]

DISPLAY_KEYS = ["name", "ec", "Entry", "EC number", "pmid", "identifier", "id", "title"]
SEARCHABLE_NODE_KEYS = [
    "name",
    "id",
    "ec",
    "Entry",
    "Entry Name",
    "Protein names",
    "Gene Names",
    "Gene Names (primary)",
    "EC number",
    "pmid",
    "identifier",
    "title",
]
LABEL_DISPLAY_KEYS = {
    "Enzyme": ["id", "ec", "name", "Entry", "identifier", "title", "pmid"],
    "Pathway": ["name", "id", "identifier", "title", "ec", "Entry", "pmid"],
    "Publication": ["title", "pmid", "id", "identifier", "name", "ec", "Entry"],
    "Protein": ["name", "Entry", "Entry Name", "Protein names", "Gene Names (primary)", "EC number", "id"],
}
NODE_COLORS = {
    "Pathway": "#1E88E5",
    "Enzyme": "#43A047",
    "Protein": "#FB8C00",
    "Publication": "#8E24AA",
    "Compound": "#00ACC1",
    "Node": "#78909C",
}

KNOWLEDGE_SUGGESTIONS = [
    "LDHA", "GAPDH", "1.1.1.27", "glycolysis",
    "human kinase", "lactate dehydrogenase", "HAO2", "pyruvate metabolism",
]
LITERATURE_SUGGESTIONS = [
    "LDHA cancer metabolism", "glycolysis enzyme human", "lactate dehydrogenase",
    "human kinase", "oxidative stress", "apoptosis", "pyruvate metabolism", "HAO2",
]
RAG_EXAMPLES = [
    "LDHA 参与哪些通路？",
    "GAPDH 有哪些 PubMed 证据？",
    "1.1.1.27 对应的酶在糖酵解中有什么作用？",
    "HAO2 的相关文献证据是什么？",
]


# --- 后端连接与查询函数：保留原有 Neo4j / RAG / PubMed 调用路径 ---
@st.cache_resource
def get_driver():
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        return driver
    except Exception as exc:
        st.error(f"数据库连接失败：{exc}")
        return None


def run_query(driver, query: str, params: dict | None = None) -> pd.DataFrame:
    with driver.session() as session:
        result = session.run(query, params or {})
        return pd.DataFrame([record.data() for record in result])


def query_by_enzyme_gene(driver, keyword: str) -> pd.DataFrame:
    query = """
    MATCH (candidate)
    WHERE (candidate:Enzyme OR candidate:Protein) AND (
        toLower(coalesce(candidate.id, "")) CONTAINS toLower($keyword)
        OR toLower(coalesce(candidate.ec, "")) CONTAINS toLower($keyword)
        OR toLower(coalesce(candidate.name, "")) CONTAINS toLower($keyword)
        OR toLower(coalesce(candidate.Entry, "")) CONTAINS toLower($keyword)
        OR toLower(coalesce(candidate.`Entry Name`, "")) CONTAINS toLower($keyword)
        OR toLower(coalesce(candidate.`Protein names`, "")) CONTAINS toLower($keyword)
        OR toLower(coalesce(candidate.`Gene Names`, "")) CONTAINS toLower($keyword)
        OR toLower(coalesce(candidate.`Gene Names (primary)`, "")) CONTAINS toLower($keyword)
    )
    WITH candidate,
         CASE
             WHEN candidate:Enzyme AND toLower(coalesce(candidate.id, "")) = toLower($keyword) THEN 0
             WHEN candidate:Enzyme AND toLower(coalesce(candidate.ec, "")) = toLower($keyword) THEN 1
             WHEN candidate:Enzyme AND toLower(coalesce(candidate.name, "")) = toLower($keyword) THEN 2
             WHEN candidate:Protein AND toLower(coalesce(candidate.`Gene Names (primary)`, "")) = toLower($keyword) THEN 3
             WHEN candidate:Protein AND toLower(coalesce(candidate.Entry, "")) = toLower($keyword) THEN 4
             WHEN candidate:Protein AND toLower(coalesce(candidate.`Entry Name`, "")) = toLower($keyword) THEN 5
             WHEN candidate:Protein AND toLower(coalesce(candidate.`Protein names`, "")) = toLower($keyword) THEN 6
             WHEN candidate:Protein AND toLower(coalesce(candidate.`Gene Names`, "")) CONTAINS toLower($keyword) THEN 7
             ELSE 20
         END AS match_priority
    ORDER BY match_priority
    LIMIT 20
    OPTIONAL MATCH (candidate)-[:HAS_EC]->(linked_enzyme:Enzyme)
    WITH candidate, CASE WHEN candidate:Enzyme THEN candidate ELSE linked_enzyme END AS e
    WHERE e:Enzyme
    OPTIONAL MATCH (p:Protein)-[:HAS_EC]->(e)
    OPTIONAL MATCH (pwy:Pathway)-[:HAS_ENZYME]->(e)
    OPTIONAL MATCH (pub:Publication)-[mr]->(e)
      WHERE type(mr) IN $mention_rel_types
    RETURN coalesce(e.id, e.ec) AS enzyme_id,
           e.ec AS ec_number,
           collect(DISTINCT coalesce(p.`Protein names`, p.name, p.`Gene Names (primary)`, p.`Entry Name`, p.Entry))[0..5] AS matched_proteins,
           collect(DISTINCT pwy.name) AS pathways,
           collect(DISTINCT pub.pmid) AS mentioned_in_pmids
    """
    return run_query(driver, query, {"keyword": keyword, "mention_rel_types": MENTION_REL_TYPES})


def query_by_ec(driver, ec_number: str) -> pd.DataFrame:
    query = """
    MATCH (ec:Enzyme {ec: $ec_number})
    OPTIONAL MATCH (p:Protein)-[:HAS_EC]->(ec)
    OPTIONAL MATCH (pwy:Pathway)-[:HAS_ENZYME]->(ec)
    RETURN coalesce(ec.id, ec.ec) AS enzyme_id,
           ec.ec AS ec_number,
           collect(DISTINCT p.Entry) AS proteins,
           collect(DISTINCT pwy.name) AS pathways
    """
    return run_query(driver, query, {"ec_number": ec_number})


def query_by_pathway(driver, keyword: str) -> pd.DataFrame:
    query = """
    MATCH (pwy:Pathway)
    WHERE toLower(coalesce(pwy.name, "")) CONTAINS toLower($keyword)
    OPTIONAL MATCH (pwy)-[:HAS_ENZYME]->(e:Enzyme)
    OPTIONAL MATCH (pub:Publication)-[mr]->(e)
      WHERE type(mr) IN $mention_rel_types
    RETURN pwy.name AS pathway,
           count(DISTINCT e) AS enzyme_count,
           collect(DISTINCT e.ec)[0..30] AS enzyme_list,
           count(DISTINCT pub) AS publication_count
    LIMIT 10
    """
    return run_query(driver, query, {"keyword": keyword, "mention_rel_types": MENTION_REL_TYPES})


def query_publications(driver, keyword: str) -> pd.DataFrame:
    query = """
    MATCH (pub:Publication)
    WHERE toLower(coalesce(pub.title, "")) CONTAINS toLower($keyword)
       OR toLower(coalesce(pub.abstract, "")) CONTAINS toLower($keyword)
    OPTIONAL MATCH (pub)-[mr]->(entity)
      WHERE type(mr) IN $mention_rel_types
        AND any(lbl IN labels(entity) WHERE lbl IN ["Enzyme", "Protein"])
    RETURN pub.pmid AS pmid,
           pub.title AS title,
           pub.abstract AS abstract,
           collect(
               DISTINCT CASE
                   WHEN "Enzyme" IN labels(entity) THEN coalesce(entity.id, entity.ec, entity.name, entity.Entry)
                   ELSE coalesce(entity.name, entity.Entry, entity.id, entity.ec)
               END
           ) AS mentioned_entities
    LIMIT 25
    """
    return run_query(driver, query, {"keyword": keyword, "mention_rel_types": MENTION_REL_TYPES})

def pick_node_display_name(props: dict[str, Any] | None, labels: list[str] | None = None) -> str:
    if not props:
        return "(Unnamed)"
    ordered_keys: list[str] = []
    for label in labels or []:
        ordered_keys.extend(LABEL_DISPLAY_KEYS.get(label, []))
    ordered_keys.extend(DISPLAY_KEYS)
    seen_keys: set[str] = set()
    for key in ordered_keys:
        if key in seen_keys:
            continue
        seen_keys.add(key)
        value = props.get(key)
        if value is not None and str(value).strip():
            return str(value)
    for value in props.values():
        if value is not None and str(value).strip():
            return str(value)
    return "(Unnamed)"


def normalize_node(node_id: int, labels: list[str] | None, props: dict[str, Any] | None) -> dict[str, Any]:
    labels = labels or []
    props = props or {}
    return {
        "id": int(node_id),
        "labels": labels,
        "primary_label": labels[0] if labels else "Node",
        "props": props,
        "display": pick_node_display_name(props, labels),
    }


def find_node_candidates(driver, keyword: str, limit: int = 30) -> pd.DataFrame:
    query = """
    MATCH (n)
    WITH n, toLower($keyword) AS keyword
    WITH n, keyword,
         [k IN $search_keys WHERE k IN keys(n) AND toLower(toString(n[k])) CONTAINS keyword] AS matched_keys
    WHERE size(matched_keys) > 0
    OPTIONAL MATCH (n)-[r]-()
    WITH n, matched_keys, count(r) AS degree,
         CASE
             WHEN any(k IN matched_keys WHERE toLower(toString(n[k])) = keyword) THEN 0
             WHEN any(k IN matched_keys WHERE toLower(toString(n[k])) STARTS WITH keyword) THEN 1
             ELSE 2
         END AS match_rank,
         CASE
             WHEN n:Protein THEN 0
             WHEN n:Enzyme THEN 1
             WHEN n:Pathway THEN 2
             WHEN n:Compound THEN 3
             WHEN n:Publication THEN 4
             ELSE 5
         END AS label_rank
    WHERE degree > 0
    RETURN id(n) AS node_id,
           labels(n) AS labels,
           properties(n) AS props,
           matched_keys,
           degree
    ORDER BY match_rank, degree DESC, label_rank, node_id
    LIMIT $limit
    """
    df = run_query(driver, query, {"keyword": keyword, "search_keys": SEARCHABLE_NODE_KEYS, "limit": limit})
    if df.empty:
        return df
    df["label"] = df["labels"].apply(lambda x: x[0] if isinstance(x, list) and x else "Node")
    df["display"] = df.apply(lambda row: pick_node_display_name(row["props"], row["labels"]), axis=1)
    return df[["node_id", "label", "display", "degree", "matched_keys", "props"]]


def get_node_by_id(driver, node_id: int) -> dict[str, Any] | None:
    query = """
    MATCH (n)
    WHERE id(n) = $node_id
    RETURN id(n) AS node_id, labels(n) AS labels, properties(n) AS props
    """
    with driver.session() as session:
        record = session.run(query, {"node_id": int(node_id)}).single()
        if record is None:
            return None
        data = record.data()
        return normalize_node(data["node_id"], data["labels"], data["props"])


def get_neighbors(driver, node_id: int, limit: int, exclude_id: int | None = None) -> list[dict[str, Any]]:
    query = """
    MATCH (n)-[r]-(m)
    WHERE id(n) = $node_id
      AND ($exclude_id IS NULL OR id(m) <> $exclude_id)
    RETURN id(n) AS source_id,
           labels(n) AS source_labels,
           properties(n) AS source_props,
           id(m) AS target_id,
           labels(m) AS target_labels,
           properties(m) AS target_props,
           type(r) AS rel_type,
           id(r) AS rel_id
    LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(
            query,
            {"node_id": int(node_id), "exclude_id": exclude_id, "limit": int(limit)},
        )
        return [record.data() for record in result]


def build_two_hop_subgraph(driver, center_id: int, first_hop_limit: int = 8, second_hop_limit: int = 3) -> dict[str, Any] | None:
    center = get_node_by_id(driver, center_id)
    if center is None:
        return None
    nodes: dict[int, dict[str, Any]] = {center["id"]: center}
    edges: dict[Any, dict[str, Any]] = {}
    first_hop_ids: set[int] = set()

    def upsert_node(node_id: int, labels: list[str], props: dict[str, Any]) -> None:
        if int(node_id) not in nodes:
            nodes[int(node_id)] = normalize_node(node_id, labels, props)

    def add_edge(row: dict[str, Any]) -> None:
        source_id = int(row["source_id"])
        target_id = int(row["target_id"])
        rel_type = row.get("rel_type") or "RELATED_TO"
        rel_id = row.get("rel_id")
        edge_key = rel_id if rel_id is not None else (min(source_id, target_id), max(source_id, target_id), rel_type)
        if edge_key not in edges:
            edges[edge_key] = {"source": source_id, "target": target_id, "rel_type": rel_type}

    for row in get_neighbors(driver, center_id, first_hop_limit):
        upsert_node(row["source_id"], row["source_labels"], row["source_props"])
        upsert_node(row["target_id"], row["target_labels"], row["target_props"])
        first_hop_ids.add(int(row["target_id"]))
        add_edge(row)

    for node_id in list(first_hop_ids):
        for row in get_neighbors(driver, node_id, second_hop_limit, exclude_id=center_id):
            upsert_node(row["source_id"], row["source_labels"], row["source_props"])
            upsert_node(row["target_id"], row["target_labels"], row["target_props"])
            add_edge(row)

    return {"center_id": int(center_id), "first_hop_ids": first_hop_ids, "nodes": nodes, "edges": list(edges.values())}


# --- UI 通用组件与状态管理 ---
def init_session_state() -> None:
    defaults = {
        "query_input": "",
        "literature_input": "",
        "graph_input": "LDHA",
        "rag_input_v2": "",
        "knowledge_history": [],
        "literature_history": [],
        "rag_history": [],
        "last_rag_answer": "",
        "last_rag_query": "",
        "query_input_autorun": False,
        "literature_input_autorun": False,
        "rag_input_v2_autorun": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def apply_global_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --blue:#1E88E5;
            --green:#43A047;
            --ink:#172033;
            --muted:#667085;
            --line:#D9E2EC;
            --line-strong:#B9C7D6;
            --paper:#FBFCF8;
            --panel:#FFFFFF;
            --panel-soft:#F4F8F5;
            --wash:#EEF5F9;
            --shadow:0 14px 34px rgba(23,32,51,.08);
        }
        html, body, [class*="css"] {
            font-family: Aptos, "Segoe UI", "Microsoft YaHei UI", sans-serif;
            color:var(--ink);
        }
        .stApp {
            background:
                linear-gradient(90deg, rgba(23,32,51,.035) 1px, transparent 1px),
                linear-gradient(180deg, rgba(23,32,51,.03) 1px, transparent 1px),
                linear-gradient(180deg, #F7FAF8 0%, #EEF4F7 48%, #F8FAF6 100%);
            background-size: 28px 28px, 28px 28px, auto;
        }
        .main .block-container {
            max-width:1280px;
            padding-top:1.1rem;
            padding-bottom:2.4rem;
        }
        section[data-testid="stSidebar"] {
            background:#F3F7F2;
            border-right:1px solid var(--line);
        }
        section[data-testid="stSidebar"] h1 {
            font-family: Georgia, "Times New Roman", serif;
            font-size:1.45rem;
            letter-spacing:.01em;
        }
        div[data-testid="stMetric"] {
            background:rgba(255,255,255,.92);
            border:1px solid var(--line);
            border-left:4px solid var(--green);
            border-radius:8px;
            padding:13px 15px;
            box-shadow:0 8px 20px rgba(23,32,51,.055);
        }
        div[data-testid="stMetric"] label {
            color:#4B5A6A;
            font-size:.82rem;
        }
        .hero {
            position:relative;
            border-radius:10px;
            padding:22px 24px 20px;
            background:
                linear-gradient(135deg, rgba(255,255,255,.95), rgba(244,248,245,.96)),
                var(--panel);
            border:1px solid var(--line);
            border-top:3px solid var(--blue);
            box-shadow:var(--shadow);
            margin-bottom:18px;
            overflow:hidden;
        }
        .hero::after {
            content:"";
            position:absolute;
            inset:auto 18px 16px auto;
            width:96px;
            height:18px;
            border-top:1px solid rgba(30,136,229,.32);
            border-bottom:1px solid rgba(67,160,71,.30);
            opacity:.8;
        }
        .hero-kicker {
            margin:0 0 9px;
            color:#3D6F50;
            font-size:.76rem;
            font-weight:700;
            letter-spacing:.12em;
            text-transform:uppercase;
        }
        .hero h1 {
            margin:0 0 7px;
            color:var(--ink);
            font-family: Georgia, "Times New Roman", "Microsoft YaHei UI", serif;
            font-size:clamp(1.55rem, 3.2vw, 2.35rem);
            line-height:1.14;
            letter-spacing:0;
        }
        .hero p {
            margin:0;
            max-width:780px;
            color:var(--muted);
            font-size:.98rem;
            line-height:1.65;
        }
        .section-card {
            border:1px solid var(--line);
            border-radius:9px;
            padding:17px 17px 12px;
            background:rgba(255,255,255,.94);
            box-shadow:0 10px 24px rgba(23,32,51,.055);
            margin:8px 0 18px;
        }
        .section-card h3 {
            font-family: Georgia, "Times New Roman", "Microsoft YaHei UI", serif;
            letter-spacing:0;
        }
        .stButton > button, .stDownloadButton > button {
            border-radius:7px;
            border:1px solid var(--line-strong);
            box-shadow:none;
            transition:transform .12s ease, border-color .12s ease, background .12s ease;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            transform:translateY(-1px);
            border-color:var(--blue);
        }
        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-baseweb="select"] {
            border-radius:7px;
        }
        .legend-item { display:flex; align-items:center; gap:8px; margin:7px 0; color:#334155; font-size:.92rem; }
        .legend-dot { width:12px; height:12px; border-radius:50%; display:inline-block; }
        .home-note {
            border-left:3px solid var(--blue);
            padding:10px 13px;
            background:rgba(238,245,249,.72);
            color:#405266;
            border-radius:0 8px 8px 0;
        }
        @media (max-width: 760px) {
            .main .block-container {
                padding-left:.85rem;
                padding-right:.85rem;
                padding-top:.7rem;
            }
            .hero {
                padding:17px 16px 15px;
                margin-bottom:12px;
            }
            .hero::after { display:none; }
            .hero h1 { font-size:1.45rem; }
            .hero p { font-size:.92rem; line-height:1.55; }
            .section-card {
                padding:13px 12px 9px;
                margin-bottom:13px;
                border-radius:8px;
            }
            div[data-testid="stMetric"] {
                padding:11px 12px;
                margin-bottom:8px;
            }
            .stButton > button, .stDownloadButton > button {
                min-height:2.35rem;
                white-space:normal;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_hero(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <section class="hero">
            <div class="hero-kicker">BioKG Workbench</div>
            <h1>{html.escape(title)}</h1>
            <p>{html.escape(subtitle)}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def card_start() -> None:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)


def card_end() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def add_history(history_key: str, value: str, max_items: int = 8) -> None:
    value = value.strip()
    if not value:
        return
    history = [item for item in st.session_state.get(history_key, []) if item != value]
    st.session_state[history_key] = [value, *history][:max_items]


def set_prompt(input_key: str, value: str, autorun_key: str | None = None) -> None:
    st.session_state[input_key] = value
    if autorun_key:
        st.session_state[autorun_key] = True


def render_prompt_buttons(options: list[str], input_key: str, autorun_key: str | None, key_prefix: str) -> None:
    st.caption("快捷提示词")
    cols = st.columns(4)
    for idx, option in enumerate(options):
        with cols[idx % 4]:
            st.button(option, key=f"{key_prefix}_{idx}", use_container_width=True, on_click=set_prompt, args=(input_key, option, autorun_key))


def render_history(history_key: str, input_key: str, autorun_key: str | None = None) -> None:
    history = st.session_state.get(history_key, [])
    if not history:
        return
    st.caption("最近查询")
    cols = st.columns(min(4, len(history)))
    for idx, item in enumerate(history[:8]):
        with cols[idx % len(cols)]:
            if st.button(item, key=f"{history_key}_{idx}", use_container_width=True):
                st.session_state[input_key] = item
                if autorun_key:
                    st.session_state[autorun_key] = True
                st.rerun()


def dataframe_download(df: pd.DataFrame, label: str, filename: str, key: str) -> None:
    if not df.empty:
        st.download_button(label, df.to_csv(index=False).encode("utf-8-sig"), filename, "text/csv", key=key)

def dot_escape(text: Any) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()


def node_color(label: str) -> str:
    return NODE_COLORS.get(label, NODE_COLORS["Node"])


def filter_subgraph(subgraph: dict[str, Any], selected_labels: list[str]) -> dict[str, Any]:
    if not selected_labels:
        return subgraph
    center_id = int(subgraph["center_id"])
    visible_nodes = {
        node_id: node
        for node_id, node in subgraph["nodes"].items()
        if node_id == center_id or node["primary_label"] in selected_labels
    }
    visible_edges = [e for e in subgraph["edges"] if e["source"] in visible_nodes and e["target"] in visible_nodes]
    return {
        **subgraph,
        "nodes": visible_nodes,
        "edges": visible_edges,
        "first_hop_ids": {node_id for node_id in subgraph["first_hop_ids"] if node_id in visible_nodes},
    }


def build_graphviz_dot(subgraph: dict[str, Any], graph_scale: float = 1.0) -> str:
    center_id = subgraph["center_id"]
    first_hop_ids = subgraph["first_hop_ids"]
    fontsize = int(10 + graph_scale * 2)
    lines = [
        "graph G {",
        '  graph [overlap=false, splines=true, bgcolor="white", pad="0.35"];',
        f'  node [shape=ellipse, style="filled,rounded", fontname="Arial", fontsize={fontsize}, color="#334155"];',
        '  edge [fontname="Arial", fontsize=10, color="#94A3B8"];',
    ]
    for node_id, node in subgraph["nodes"].items():
        label = node["primary_label"]
        fill_color = "#EF4444" if node_id == center_id else node_color(label)
        pen_width = "2.6" if node_id == center_id else "1.2"
        width = 1.2 * graph_scale if node_id in first_hop_ids else 0.95 * graph_scale
        display = f"{node['display']}\\n[{label}]"
        lines.append(
            f'  "n{node_id}" [label="{dot_escape(display)}", fillcolor="{fill_color}", '
            f'fontcolor="white", penwidth="{pen_width}", width="{width:.2f}"];'
        )
    for edge in subgraph["edges"]:
        lines.append(f'  "n{edge["source"]}" -- "n{edge["target"]}" [label="{dot_escape(edge["rel_type"])}"];')
    lines.append("}")
    return "\n".join(lines)


def build_graphviz_png(dot: str) -> bytes | None:
    dot_bin = shutil.which("dot")
    if not dot_bin:
        return None
    try:
        completed = subprocess.run(
            [dot_bin, "-Tpng"],
            input=dot.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=15,
        )
        return completed.stdout
    except Exception:
        return None


def render_pyvis_graph(subgraph: dict[str, Any], height: int = 620) -> bool:
    try:
        from pyvis.network import Network
    except Exception:
        return False

    net = Network(
        height=f"{height}px",
        width="100%",
        bgcolor="#FFFFFF",
        font_color="#1F2937",
        cdn_resources="in_line",
    )
    net.force_atlas_2based(gravity=-55, central_gravity=0.015, spring_length=145, spring_strength=0.08)
    net.set_options(
        """
        const options = {
          "interaction": {
            "hover": true, "dragNodes": true, "dragView": true,
            "zoomView": true, "navigationButtons": true, "keyboard": true
          },
          "physics": {"enabled": true, "stabilization": {"iterations": 120}},
          "edges": {"smooth": {"type": "dynamic"}, "font": {"size": 10, "align": "middle"}}
        }
        """
    )
    center_id = int(subgraph["center_id"])
    first_hop_ids = set(subgraph["first_hop_ids"])
    for node_id, node in subgraph["nodes"].items():
        label = node["primary_label"]
        props_preview = "<br>".join(
            f"<b>{html.escape(str(k))}</b>: {html.escape(str(v))[:120]}"
            for k, v in list((node.get("props") or {}).items())[:10]
            if v is not None
        )
        title = f"<b>{html.escape(node['display'])}</b><br>{html.escape(label)}<br>{props_preview}"
        size = 30 if node_id == center_id else 22 if node_id in first_hop_ids else 16
        color = "#EF4444" if node_id == center_id else node_color(label)
        net.add_node(int(node_id), label=f"{node['display']}\n[{label}]", title=title, color=color, size=size, borderWidth=3 if node_id == center_id else 1)
    for edge in subgraph["edges"]:
        net.add_edge(int(edge["source"]), int(edge["target"]), label=edge["rel_type"], title=edge["rel_type"], color="#94A3B8")
    components.html(net.generate_html(), height=height + 20, scrolling=False)
    return True


def render_graph_legend(labels: list[str]) -> None:
    st.markdown("**图例**")
    st.markdown('<div class="legend-item"><span class="legend-dot" style="background:#EF4444"></span>中心节点</div>', unsafe_allow_html=True)
    for label in labels:
        st.markdown(
            f'<div class="legend-item"><span class="legend-dot" style="background:{node_color(label)}"></span>{html.escape(label)}</div>',
            unsafe_allow_html=True,
        )


def is_ollama_available() -> bool:
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=3)
        return response.status_code < 500
    except requests.RequestException:
        return False


# --- 首页 ---
def render_home_page(driver) -> None:
    page_hero("BioKG 生物医学知识图谱工作台", "面向日常分析的图谱检索界面：先定位实体，再核对证据，最后生成可追溯的 Graph RAG 报告。")
    try:
        stats_df = run_query(driver, "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC")
        total_nodes = int(stats_df["count"].sum()) if not stats_df.empty else 0
        top_label = stats_df.iloc[0]["label"] if not stats_df.empty else "N/A"
    except Exception:
        total_nodes, top_label = 0, "N/A"
    cols = st.columns(4)
    cols[0].metric("图谱节点", f"{total_nodes:,}")
    cols[1].metric("工作区", "6")
    cols[2].metric("主要节点", top_label)
    cols[3].metric("RAG 模型", "Ollama")
    st.divider()
    st.markdown(
        """
        <div class="home-note">
        建议工作流：先在知识查询中确认实体与 EC 编号，再进入图谱可视化查看邻域，最后用 RAG 问答生成报告。
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### ")
    col1, col2, col3 = st.columns([1.05, 1, 1])
    with col1:
        card_start(); st.subheader("实体定位"); st.write("按基因、酶编号、通路名称检索 Neo4j 中的结构化关系，适合做第一轮证据确认。"); card_end()
    with col2:
        card_start(); st.subheader("邻域审查"); st.write("选择实体并查看两跳邻域，支持拖拽、缩放、类型筛选和图片导出。"); card_end()
    with col3:
        card_start(); st.subheader("报告生成"); st.write("基于图谱证据和 PubMed 摘要生成 Markdown 报告，保留可下载结果。"); card_end()

# --- 知识查询模块 ---
def render_query_page(driver) -> None:
    page_hero("知识查询", "检索酶、基因、EC 编号与通路关系，并保留最近查询记录。")
    card_start()
    keyword = st.text_input("输入关键词", placeholder="例如：LDHA、1.1.1.27、glycolysis、human kinase", key="query_input")
    render_prompt_buttons(KNOWLEDGE_SUGGESTIONS, "query_input", "query_input_autorun", "knowledge_prompt")
    col1, col2, col3 = st.columns([1.2, 1, 1])
    with col1:
        query_mode = st.selectbox("检索范围", ["自动识别", "酶 / 基因", "通路", "EC 编号"])
    with col2:
        show_raw = st.toggle("显示原始表格", value=True)
    with col3:
        run_search = st.button("搜索知识图谱", type="primary", use_container_width=True)
    card_end()

    render_history("knowledge_history", "query_input", "query_input_autorun")
    should_run = run_search or st.session_state.pop("query_input_autorun", False)
    if not should_run:
        return
    keyword = (keyword or st.session_state.get("query_input", "")).strip()
    if not keyword:
        st.warning("请输入关键词后再搜索。")
        return

    add_history("knowledge_history", keyword)
    is_ec = bool(re.match(r"^\d+(\.\d+){2,3}$", keyword))
    with st.spinner("正在检索知识图谱..."):
        try:
            results: dict[str, pd.DataFrame] = {}
            if query_mode == "EC 编号" or (query_mode == "自动识别" and is_ec):
                results["EC 编号"] = query_by_ec(driver, keyword)
            if query_mode in ["自动识别", "酶 / 基因"] and not (query_mode == "自动识别" and is_ec):
                results["酶 / 基因"] = query_by_enzyme_gene(driver, keyword)
            if query_mode in ["自动识别", "通路"] and not (query_mode == "自动识别" and is_ec):
                results["通路"] = query_by_pathway(driver, keyword)
        except Exception as exc:
            st.error(f"检索失败：{exc}")
            return

    st.success("检索完成。")
    st.divider()
    if not results or all(df.empty for df in results.values()):
        st.info("未找到匹配结果，可以尝试更短的基因名、EC 编号或英文通路名。")
        return

    result_cols = st.columns(len(results))
    for idx, (title, df) in enumerate(results.items()):
        with result_cols[idx]:
            card_start()
            st.subheader(title)
            st.metric("结果数", len(df))
            if df.empty:
                st.info("暂无匹配。")
            elif show_raw:
                st.dataframe(df, use_container_width=True, hide_index=True)
                dataframe_download(df, "下载 CSV", f"biokg_{title}_{keyword}.csv", f"download_{title}")
            else:
                for _, row in df.head(6).iterrows():
                    st.markdown(f"**{row.iloc[0]}**")
                    st.caption(" | ".join(f"{k}: {v}" for k, v in row.items() if v not in [None, ""]))
            card_end()


# --- 文献检索模块 ---
def render_literature_page(driver) -> None:
    page_hero("文献检索", "在 PubMed 文献节点中检索标题、摘要与已链接实体。")
    card_start()
    keyword = st.text_input("输入文献关键词", placeholder="例如：LDHA cancer metabolism、glycolysis enzyme human", key="literature_input")
    render_prompt_buttons(LITERATURE_SUGGESTIONS, "literature_input", "literature_input_autorun", "literature_prompt")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        entity_filter = st.text_input("实体过滤（可选）", placeholder="例如：LDHA")
    with col2:
        max_cards = st.slider("最多展示", 5, 25, 10)
    with col3:
        run_search = st.button("检索文献", type="primary", use_container_width=True)
    card_end()

    render_history("literature_history", "literature_input", "literature_input_autorun")
    should_run = run_search or st.session_state.pop("literature_input_autorun", False)
    if not should_run:
        return
    keyword = (keyword or st.session_state.get("literature_input", "")).strip()
    if not keyword:
        st.warning("请输入文献关键词后再检索。")
        return

    add_history("literature_history", keyword)
    with st.spinner("正在检索 PubMed 文献摘要..."):
        try:
            df = query_publications(driver, keyword)
        except Exception as exc:
            st.error(f"文献检索失败：{exc}")
            return

    if entity_filter.strip() and not df.empty:
        needle = entity_filter.strip().lower()
        df = df[df["mentioned_entities"].apply(lambda values: any(needle in str(item).lower() for item in (values or [])))]
    if df.empty:
        st.warning("未找到相关文献。")
        return

    st.success(f"共找到 {len(df)} 篇文献。")
    dataframe_download(df, "下载检索结果 CSV", f"pubmed_{keyword}.csv", "literature_download")
    for _, row in df.head(max_cards).iterrows():
        with st.expander(f"PMID: {row['pmid']} | {row['title']}", expanded=False):
            st.markdown("**摘要**")
            st.write(row["abstract"] or "无可用摘要。")
            entities = [str(x) for x in (row["mentioned_entities"] or []) if x]
            st.markdown("**提及实体**")
            st.write(", ".join(entities) if entities else "无")

# --- 图谱可视化模块 ---
def render_graph_page(driver) -> None:
    page_hero("图谱可视化", "构建两跳子图，支持节点类型筛选、拖拽缩放与 PNG 导出。")
    card_start()
    col1, col2 = st.columns([2, 1])
    with col1:
        keyword = st.text_input("输入中心节点关键词", placeholder="例如：LDHA、glycolysis", key="graph_input")
    with col2:
        search_nodes = st.button("查找节点", type="primary", use_container_width=True)
    card_end()
    if not keyword.strip() and not search_nodes:
        return

    with st.spinner("正在查找可视化候选节点..."):
        try:
            candidates_df = find_node_candidates(driver, keyword.strip())
        except Exception as exc:
            st.error(f"候选节点检索失败：{exc}")
            return
    if candidates_df.empty:
        st.info("没有找到可用于可视化的候选节点。")
        return

    candidate_ids = candidates_df["node_id"].tolist()
    display_map = {
        int(row["node_id"]): f'{row["display"]} ({row["label"]}) | degree={row["degree"]} | id={row["node_id"]}'
        for _, row in candidates_df.iterrows()
    }
    control_col, graph_col = st.columns([0.95, 2.4])
    with control_col:
        card_start()
        selected_node_id = st.selectbox("中心节点", options=candidate_ids, format_func=lambda x: display_map[int(x)], key="graph_node_selector")
        first_hop_limit = st.slider("一跳邻居数", 1, 25, 8, key="first_hop_limit")
        second_hop_limit = st.slider("每个一跳节点的二跳扩展数", 1, 12, 3, key="second_hop_limit")
        graph_height = st.slider("画布高度", 420, 900, 640, step=20)
        graph_scale = st.slider("导出缩放", 0.8, 1.8, 1.1, step=0.1)
        card_end()

    with st.spinner("正在构建两跳子图..."):
        subgraph = build_two_hop_subgraph(driver, int(selected_node_id), first_hop_limit, second_hop_limit)
    if not subgraph:
        st.warning("子图构建失败。")
        return
    if not subgraph["edges"]:
        st.warning("该节点没有可展示的关系，请选择其他候选节点。")
        return

    available_labels = sorted({node["primary_label"] for node in subgraph["nodes"].values()})
    selected_labels = st.multiselect("节点类型筛选", options=available_labels, default=available_labels, help="中心节点始终保留；边会随可见节点自动过滤。")
    visible_subgraph = filter_subgraph(subgraph, selected_labels)

    with control_col:
        card_start()
        render_graph_legend(available_labels)
        st.metric("节点数", len(visible_subgraph["nodes"]))
        st.metric("关系数", len(visible_subgraph["edges"]))
        dot = build_graphviz_dot(visible_subgraph, graph_scale=graph_scale)
        png = build_graphviz_png(dot)
        if png:
            st.download_button("导出图片 PNG", png, f"biokg_subgraph_{selected_node_id}.png", "image/png", use_container_width=True)
        else:
            st.download_button("导出 DOT", dot.encode("utf-8"), f"biokg_subgraph_{selected_node_id}.dot", "text/vnd.graphviz", use_container_width=True)
            st.caption("PNG 导出需要安装 Graphviz 并将 dot 加入 PATH。")
        card_end()

    with graph_col:
        card_start()
        used_pyvis = render_pyvis_graph(visible_subgraph, height=graph_height)
        if not used_pyvis:
            st.graphviz_chart(build_graphviz_dot(visible_subgraph, graph_scale=graph_scale), use_container_width=True)
            st.info("安装 pyvis 后可启用拖拽、滚轮缩放和导航按钮：pip install pyvis")
        card_end()

    selected_row = candidates_df[candidates_df["node_id"] == selected_node_id]
    if not selected_row.empty:
        props = selected_row.iloc[0]["props"] or {}
        if props:
            with st.expander("查看中心节点属性"):
                st.dataframe(pd.DataFrame([{"属性": k, "值": str(v)} for k, v in props.items()]), use_container_width=True, hide_index=True)


# --- RAG 问答模块 ---
def render_rag_page_v2() -> None:
    page_hero("RAG 问答", "先从图谱中定位候选实体，再调用本地 Ollama 生成证据驱动的分析报告。")
    card_start()
    query = st.text_area("输入实体或问题", placeholder="例如：LDHA 参与哪些通路？", key="rag_input_v2", height=90)
    render_prompt_buttons(RAG_EXAMPLES, "rag_input_v2", "rag_input_v2_autorun", "rag_prompt")
    col1, col2 = st.columns([1, 1])
    with col1:
        model_name = st.selectbox("Ollama 模型", ["deepseek-r1:7b", "llama3.1", "qwen2.5"], index=0)
    with col2:
        generate = st.button("生成分析报告", type="primary", use_container_width=True, disabled=not query.strip())
    card_end()

    render_history("rag_history", "rag_input_v2", "rag_input_v2_autorun")
    should_run = generate or st.session_state.pop("rag_input_v2_autorun", False)
    selected_candidate_id = None
    clean_query = (query or st.session_state.get("rag_input_v2", "")).strip()
    entity_query = re.sub(r"[？?].*$", "", clean_query).strip()
    entity_query = entity_query.split()[0] if entity_query and " " in entity_query else entity_query

    if clean_query:
        with st.spinner("正在匹配候选实体..."):
            try:
                candidates = search_report_candidates(entity_query or clean_query, limit=8)
            except Exception as exc:
                st.warning(f"候选检索失败：{exc}")
                candidates = []
        if len(candidates) > 1:
            candidate_ids = [str(item["candidate_node_id"]) for item in candidates]
            display_map = {str(item["candidate_node_id"]): item["display"] for item in candidates}
            selected_candidate_id = st.selectbox("选择候选实体", options=candidate_ids, format_func=lambda x: display_map[str(x)], key="rag_candidate_selector_v2")
        elif len(candidates) == 1:
            selected_candidate_id = str(candidates[0]["candidate_node_id"])
            st.caption(f"已自动选中：{candidates[0]['display']}")
        else:
            st.caption("未找到明确候选，将按输入内容直接尝试检索。")

    if not should_run:
        if st.session_state.get("last_rag_answer"):
            st.divider()
            st.subheader("最近一次报告")
            st.markdown(st.session_state["last_rag_answer"])
            st.download_button("下载报告 MD", st.session_state["last_rag_answer"].encode("utf-8"), "biokg_rag_report.md", "text/markdown")
        return
    if not clean_query:
        st.warning("请输入问题或实体名称。")
        return
    add_history("rag_history", clean_query)
    if not is_ollama_available():
        st.warning("请先启动本地 Ollama 服务！")
        return

    with st.spinner("[1/2] 正在检索图谱证据..."):
        try:
            prompt = get_knowledge_context(entity_query or clean_query, candidate_node_id=selected_candidate_id)
        except Exception as exc:
            st.error(f"图谱检索失败：{exc}")
            return
    if not prompt:
        st.warning("未能构建 RAG 上下文。")
        return
    if not prompt.strip().startswith("### [BioKG"):
        st.warning(prompt)
        return

    st.success("图谱证据检索完成。")
    with st.spinner("[2/2] 正在调用本地大模型生成回答..."):
        try:
            answer = generate_answer_with_ollama(prompt, model_name=model_name)
        except Exception as exc:
            st.error(f"生成失败：{exc}")
            return
    if "无法连接" in answer or ("Ollama" in answer and "启动" in answer):
        st.warning("请先启动本地 Ollama 服务！")
        st.caption(answer)
        return

    st.session_state["last_rag_answer"] = answer
    st.session_state["last_rag_query"] = clean_query
    st.divider()
    st.subheader("BioKG 分析报告")
    st.markdown(answer)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", clean_query)[:40]
    st.download_button("下载报告 MD", answer.encode("utf-8"), f"biokg_rag_{safe_name}.md", "text/markdown", type="primary")

# --- 数据统计模块 ---
def render_stats_page(driver) -> None:
    page_hero("数据统计", "用图表查看节点类型、关系类型与 PubMed 文献时间分布。")
    refresh = st.button("刷新统计", type="primary")
    if not refresh and "stats_node_df" not in st.session_state:
        refresh = True

    if refresh:
        with st.spinner("正在查询图谱统计..."):
            try:
                node_df = run_query(driver, "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC")
                rel_df = run_query(driver, "MATCH ()-[r]->() RETURN type(r) AS relationship, count(r) AS count ORDER BY count DESC LIMIT 20")
                pub_trend_df = run_query(
                    driver,
                    """
                    MATCH (p:Publication)
                    WITH toString(coalesce(p.last_updated, "Unknown")) AS raw_date
                    WITH CASE
                        WHEN raw_date =~ '\\d{4}-\\d{2}-\\d{2}T.*' THEN substring(raw_date, 0, 10)
                        WHEN raw_date =~ '\\d{4}-\\d{2}-\\d{2}.*' THEN substring(raw_date, 0, 10)
                        WHEN raw_date =~ '\\d{4}-\\d{2}.*' THEN substring(raw_date, 0, 7)
                        WHEN raw_date =~ '\\d{4}.*' THEN substring(raw_date, 0, 4)
                        ELSE 'Unknown'
                    END AS updated_at
                    RETURN updated_at AS year, count(*) AS count
                    ORDER BY year
                    """,
                )
                st.session_state["stats_node_df"] = node_df
                st.session_state["stats_rel_df"] = rel_df
                st.session_state["stats_pub_trend_df"] = pub_trend_df
                st.success("统计完成。")
            except Exception as exc:
                st.error(f"获取统计失败：{exc}")
                return

    node_df = st.session_state.get("stats_node_df", pd.DataFrame())
    rel_df = st.session_state.get("stats_rel_df", pd.DataFrame())
    pub_trend_df = st.session_state.get("stats_pub_trend_df", pd.DataFrame())
    if node_df.empty:
        st.warning("未查询到带标签节点。")
        return

    metric_cols = st.columns(4)
    metric_cols[0].metric("总节点数", f"{int(node_df['count'].sum()):,}")
    metric_cols[1].metric("节点类型", f"{len(node_df):,}")
    metric_cols[2].metric("总关系数", f"{int(rel_df['count'].sum()):,}" if not rel_df.empty else "0")
    pub_count = int(node_df.loc[node_df["label"] == "Publication", "count"].sum())
    metric_cols[3].metric("Publication", f"{pub_count:,}")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        card_start()
        st.subheader("节点类型分布")
        st.bar_chart(node_df.set_index("label")["count"])
        st.dataframe(node_df.rename(columns={"label": "节点类型", "count": "数量"}), use_container_width=True, hide_index=True)
        card_end()
    with col2:
        card_start()
        st.subheader("关系类型分布")
        if rel_df.empty:
            st.info("暂无关系统计。")
        else:
            st.bar_chart(rel_df.set_index("relationship")["count"])
            st.dataframe(rel_df.rename(columns={"relationship": "关系类型", "count": "数量"}), use_container_width=True, hide_index=True)
        card_end()

    card_start()
    st.subheader("文献增量趋势")
    trend = pub_trend_df[pub_trend_df["year"] != "Unknown"] if not pub_trend_df.empty else pd.DataFrame()
    if trend.empty:
        st.info("Publication 节点中没有可识别的年份字段，暂无法绘制趋势图。")
    else:
        st.line_chart(trend.set_index("year")["count"])
    card_end()


# --- 系统更新模块 ---
def render_update_page() -> None:
    page_hero("系统更新", "触发 PubMed 增量抓取、NER 解析与 Neo4j 写入流水线。")
    st.warning("该操作会访问 PubMed 并写入 Neo4j，耗时取决于网络、SciSpacy 模型和数据库状态。")
    card_start()
    st.markdown("**更新流程**")
    st.write("1. 从 Neo4j 动态加载 Protein/EC 同义词")
    st.write("2. 查询 PubMed 最新文献")
    st.write("3. 解析摘要并写入 Publication 与 MENTIONS_EC 关系")
    start_update = st.button("执行增量更新", type="primary", use_container_width=True)
    card_end()
    if not start_update:
        return

    progress = st.progress(0, text="准备执行更新...")
    try:
        progress.progress(12, text="检查本地配置与数据库连接...")
        driver = get_driver()
        if driver is None:
            st.error("更新失败，请检查 Neo4j 服务。")
            return
        progress.progress(28, text="启动 PubMed 增量更新流水线...")
        with st.spinner("正在从 PubMed 更新数据，后端日志会输出详细进度..."):
            run_pipeline()
        progress.progress(100, text="更新完成。")
        st.success("操作完成！")
    except Exception as exc:
        progress.progress(100, text="更新失败。")
        st.error(f"更新失败，请检查网络或本地服务：{exc}")


def render_sidebar() -> str:
    st.sidebar.title("BioKG")
    st.sidebar.caption("Graph evidence, literature, and local RAG")
    page = st.sidebar.radio(
        "导航",
        ["首页", "知识查询", "文献检索", "图谱可视化", "RAG 问答", "数据统计", "系统更新"],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    st.sidebar.markdown("**连接配置**")
    st.sidebar.caption(f"Neo4j: `{NEO4J_URI}`")
    st.sidebar.caption(f"Ollama: `{OLLAMA_TAGS_URL.replace('/api/tags', '')}`")
    st.sidebar.divider()
    if st.sidebar.button("清空查询历史", use_container_width=True):
        for key in ["knowledge_history", "literature_history", "rag_history", "last_rag_answer"]:
            st.session_state[key] = [] if key.endswith("_history") else ""
        st.rerun()
    return page


def main() -> None:
    st.set_page_config(
        page_title="BioKG Graph RAG",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_session_state()
    apply_global_style()

    page = render_sidebar()
    driver = get_driver()
    if not driver:
        st.stop()

    page_map = {
        "首页": lambda: render_home_page(driver),
        "知识查询": lambda: render_query_page(driver),
        "文献检索": lambda: render_literature_page(driver),
        "图谱可视化": lambda: render_graph_page(driver),
        "RAG 问答": render_rag_page_v2,
        "数据统计": lambda: render_stats_page(driver),
        "系统更新": render_update_page,
    }
    page_map[page]()


if __name__ == "__main__":
    main()
