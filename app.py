# -*- coding: utf-8 -*-
import os
import re
import sys
from typing import Any

import pandas as pd
import streamlit as st
from neo4j import GraphDatabase

# 让 app.py 在项目根目录运行时可导入 BioKG 包
sys.path.append(os.path.dirname(__file__))

from BioKG.pipeline.update_pipeline import run_pipeline
from BioKG.RAG.rag_engine import get_knowledge_context, generate_answer_with_ollama


NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "12345678")

DISPLAY_KEYS = ["name", "ec", "Entry", "pmid", "identifier", "id", "title"]


@st.cache_resource
def get_driver():
    """创建并返回 Neo4j driver。"""
    try:
        driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
        )
        driver.verify_connectivity()
        return driver
    except Exception as exc:
        st.error(f"数据库连接失败: {exc}")
        return None


def run_query(driver, query: str, params: dict | None = None) -> pd.DataFrame:
    """通用 Cypher 查询。"""
    params = params or {}
    with driver.session() as session:
        result = session.run(query, params)
        return pd.DataFrame([record.data() for record in result])


def query_by_enzyme_gene(driver, keyword: str) -> pd.DataFrame:
    query = """
    MATCH (e:Enzyme)
    WHERE toLower(coalesce(e.ec, "")) CONTAINS toLower($keyword)
       OR toLower(coalesce(e.name, "")) CONTAINS toLower($keyword)
    OPTIONAL MATCH (pwy:Pathway)-[:HAS_ENZYME]->(e)
    OPTIONAL MATCH (pub:Publication)-[:MENTIONS]->(e)
    RETURN e.ec AS ec_number,
           collect(DISTINCT pwy.name) AS pathways,
           collect(DISTINCT pub.pmid) AS mentioned_in_pmids
    LIMIT 20
    """
    return run_query(driver, query, {"keyword": keyword})


def query_by_ec(driver, ec_number: str) -> pd.DataFrame:
    query = """
    MATCH (ec:Enzyme {ec: $ec_number})
    OPTIONAL MATCH (p:Protein)-[:HAS_EC]->(ec)
    OPTIONAL MATCH (pwy:Pathway)-[:HAS_ENZYME]->(ec)
    RETURN ec.ec AS ec_number,
           collect(DISTINCT p.Entry) AS proteins,
           collect(DISTINCT pwy.name) AS pathways
    """
    return run_query(driver, query, {"ec_number": ec_number})


def query_by_pathway(driver, keyword: str) -> pd.DataFrame:
    query = """
    MATCH (pwy:Pathway)
    WHERE toLower(coalesce(pwy.name, "")) CONTAINS toLower($keyword)
    OPTIONAL MATCH (pwy)-[:HAS_ENZYME]->(e:Enzyme)
    OPTIONAL MATCH (pub:Publication)-[:MENTIONS]->(e)
    RETURN pwy.name AS pathway,
           count(DISTINCT e) AS enzyme_count,
           collect(DISTINCT e.ec)[0..30] AS enzyme_list,
           count(DISTINCT pub) AS publication_count
    LIMIT 10
    """
    return run_query(driver, query, {"keyword": keyword})


def query_publications(driver, keyword: str) -> pd.DataFrame:
    query = """
    MATCH (pub:Publication)
    WHERE toLower(coalesce(pub.title, "")) CONTAINS toLower($keyword)
       OR toLower(coalesce(pub.abstract, "")) CONTAINS toLower($keyword)
    OPTIONAL MATCH (pub)-[:MENTIONS]->(entity)
    WHERE any(lbl IN labels(entity) WHERE lbl IN ["Enzyme", "Protein"])
    RETURN pub.pmid AS pmid,
           pub.title AS title,
           pub.abstract AS abstract,
           collect(DISTINCT coalesce(entity.name, entity.ec, entity.Entry, entity.id)) AS mentioned_entities
    LIMIT 25
    """
    return run_query(driver, query, {"keyword": keyword})


def pick_node_display_name(props: dict[str, Any] | None) -> str:
    if not props:
        return "(Unnamed)"

    for key in DISPLAY_KEYS:
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
        "display": pick_node_display_name(props),
    }


def find_node_candidates(driver, keyword: str, limit: int = 30) -> pd.DataFrame:
    query = """
    MATCH (n)
    WHERE any(k IN keys(n) WHERE toLower(toString(n[k])) CONTAINS toLower($keyword))
    RETURN id(n) AS node_id,
           labels(n) AS labels,
           properties(n) AS props
    LIMIT $limit
    """
    df = run_query(driver, query, {"keyword": keyword, "limit": limit})
    if df.empty:
        return df

    df["label"] = df["labels"].apply(lambda x: x[0] if isinstance(x, list) and x else "Node")
    df["display"] = df["props"].apply(pick_node_display_name)
    return df[["node_id", "label", "display", "props"]]


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


def build_two_hop_subgraph(
    driver,
    center_id: int,
    first_hop_limit: int = 8,
    second_hop_limit: int = 3,
) -> dict[str, Any] | None:
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
        if edge_key in edges:
            return
        edges[edge_key] = {"source": source_id, "target": target_id, "rel_type": rel_type}

    first_edges = get_neighbors(driver, center_id, first_hop_limit)
    for row in first_edges:
        upsert_node(row["source_id"], row["source_labels"], row["source_props"])
        upsert_node(row["target_id"], row["target_labels"], row["target_props"])
        first_hop_ids.add(int(row["target_id"]))
        add_edge(row)

    for node_id in list(first_hop_ids):
        second_edges = get_neighbors(driver, node_id, second_hop_limit, exclude_id=center_id)
        for row in second_edges:
            upsert_node(row["source_id"], row["source_labels"], row["source_props"])
            upsert_node(row["target_id"], row["target_labels"], row["target_props"])
            add_edge(row)

    return {
        "center_id": int(center_id),
        "first_hop_ids": first_hop_ids,
        "nodes": nodes,
        "edges": list(edges.values()),
    }


def dot_escape(text: Any) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()


def build_graphviz_dot(subgraph: dict[str, Any]) -> str:
    center_id = subgraph["center_id"]
    first_hop_ids = subgraph["first_hop_ids"]
    nodes = subgraph["nodes"]
    edges = subgraph["edges"]

    lines = [
        "graph G {",
        '  graph [overlap=false, splines=true, bgcolor="white"];',
        '  node [shape=ellipse, style="filled,rounded", fontname="Microsoft YaHei", fontsize=11, color="#444444"];',
        '  edge [fontname="Microsoft YaHei", fontsize=10, color="#777777"];',
    ]

    for node_id, node in nodes.items():
        if node_id == center_id:
            fill_color = "#FFB3B3"
        elif node_id in first_hop_ids:
            fill_color = "#FFE7A8"
        else:
            fill_color = "#CFE6FF"

        label = f"{node['display']}\\n[{node['primary_label']}]"
        lines.append(
            f'  "n{node_id}" [label="{dot_escape(label)}", fillcolor="{fill_color}"];'
        )

    for edge in edges:
        lines.append(
            f'  "n{edge["source"]}" -- "n{edge["target"]}" [label="{dot_escape(edge["rel_type"])}"];'
        )

    lines.append("}")
    return "\n".join(lines)


def render_home_page():
    st.title("BioKG 生物医学知识图谱问答系统")
    st.subheader("KEGG + UniProt + PubMed 多源融合")
    st.markdown("---")
    st.markdown(
        """
欢迎使用 BioKG 知识图谱系统。

- 知识查询：按实体关键词查询酶、通路等信息
- 文献检索：按关键词检索 PubMed 文献
- 智能问答（RAG）：结合图谱和文献生成综合分析
- 图谱统计：查看节点数量分布
- 数据更新：从 PubMed 做增量更新
"""
    )


def render_node_visualization_section(driver, keyword: str):
    st.subheader("节点两跳可视化")
    st.caption("先选中目标节点，再展示该节点及其 2 跳邻居（数量可调）。")

    candidates_df = find_node_candidates(driver, keyword)
    if candidates_df.empty:
        st.info("没有找到可用于可视化的节点。")
        return

    candidate_ids = candidates_df["node_id"].tolist()
    display_map = {
        int(row["node_id"]): f'{row["display"]} ({row["label"]}) | id={row["node_id"]}'
        for _, row in candidates_df.iterrows()
    }

    selected_node_id = st.selectbox(
        "选择节点",
        options=candidate_ids,
        format_func=lambda x: display_map[int(x)],
        key="graph_node_selector",
    )

    col1, col2 = st.columns(2)
    with col1:
        first_hop_limit = st.slider("1 跳邻居数", min_value=1, max_value=20, value=8, key="first_hop_limit")
    with col2:
        second_hop_limit = st.slider(
            "每个 1 跳节点展开的 2 跳邻居数",
            min_value=1,
            max_value=10,
            value=3,
            key="second_hop_limit",
        )

    with st.spinner("正在生成两跳子图..."):
        subgraph = build_two_hop_subgraph(
            driver,
            int(selected_node_id),
            first_hop_limit=first_hop_limit,
            second_hop_limit=second_hop_limit,
        )

    if not subgraph:
        st.warning("未能生成子图，请确认节点是否存在。")
        return

    dot = build_graphviz_dot(subgraph)
    st.graphviz_chart(dot, use_container_width=True)

    st.caption(
        f'中心节点 1 个，子图共 {len(subgraph["nodes"])} 个节点、{len(subgraph["edges"])} 条关系。'
    )
    st.caption("颜色说明：红色=中心节点，黄色=1 跳邻居，蓝色=2 跳邻居。")

    selected_row = candidates_df[candidates_df["node_id"] == selected_node_id]
    if not selected_row.empty:
        props = selected_row.iloc[0]["props"] or {}
        if props:
            prop_df = pd.DataFrame([{"属性": k, "值": str(v)} for k, v in props.items()])
            with st.expander("查看选中节点属性"):
                st.dataframe(prop_df, use_container_width=True, hide_index=True)


def render_query_page(driver):
    st.header("知识查询")
    keyword = st.text_input("输入关键词（例如：GAPDH, 1.1.1.27, glycolysis）", key="query_input")
    if not keyword:
        return

    keyword = keyword.strip()

    if re.match(r"^\d+(\.\d+){2,3}$", keyword):
        st.subheader(f"EC 编号查询结果：`{keyword}`")
        df_ec = query_by_ec(driver, keyword)
        if df_ec.empty:
            st.warning("未找到匹配的 EC 编号。")
        else:
            st.dataframe(df_ec, use_container_width=True)
    else:
        st.subheader(f"“{keyword}” 的综合查询结果")
        col1, col2 = st.columns(2)
        with col1:
            st.info("酶/基因相关信息")
            df_enzyme = query_by_enzyme_gene(driver, keyword)
            if df_enzyme.empty:
                st.write("未找到匹配的酶或基因。")
            else:
                st.dataframe(df_enzyme, use_container_width=True)
        with col2:
            st.info("通路相关信息")
            df_pathway = query_by_pathway(driver, keyword)
            if df_pathway.empty:
                st.write("未找到匹配的通路。")
            else:
                st.dataframe(df_pathway, use_container_width=True)

    st.markdown("---")
    render_node_visualization_section(driver, keyword)


def render_literature_page(driver):
    st.header("文献检索")
    keyword = st.text_input("输入文献关键词（例如：cancer, metabolism）", key="literature_input")
    if not keyword:
        return

    with st.spinner(f"正在检索与 “{keyword}” 相关的文献..."):
        df = query_publications(driver, keyword.strip())
        if df.empty:
            st.warning("未找到相关文献。")
            return

        st.success(f"找到 {len(df)} 篇相关文献。")
        for _, row in df.iterrows():
            with st.expander(f"PMID: {row['pmid']} | {row['title']}"):
                st.markdown("**摘要**")
                st.write(row["abstract"] or "无可用摘要。")
                st.markdown("**关联实体**")
                entities = [x for x in (row["mentioned_entities"] or []) if x]
                st.write(", ".join(map(str, entities)) if entities else "无")


def render_rag_page():
    st.header("智能问答（RAG）")
    st.info("输入一个酶/基因名称，系统将结合图谱和文献生成综合分析报告。")
    query = st.text_input("请输入酶/基因名称（例如：LDHA, GAPDH）", key="rag_input")

    if st.button("生成分析报告", disabled=not query):
        with st.spinner(f"[1/2] 正在从图谱中提取 “{query}” 的证据..."):
            try:
                prompt = get_knowledge_context(query.strip())
            except Exception as exc:
                st.error(f"检索阶段失败: {exc}")
                st.stop()

        if prompt and not (prompt.strip().startswith("抱歉") or prompt.strip().startswith("无法连接")):
            st.success("检索完成。")
            with st.spinner("[2/2] 正在调用本地大模型生成分析..."):
                try:
                    answer = generate_answer_with_ollama(prompt)
                    st.markdown("---")
                    st.subheader("BioKG 智能分析报告")
                    st.markdown(answer)
                except Exception as exc:
                    st.error(f"生成阶段失败: {exc}")
        elif prompt:
            st.warning(prompt)


def render_stats_page(driver):
    st.header("图谱统计")
    st.info("点击按钮获取当前知识图谱中各类节点数量。")

    if st.button("刷新统计数据"):
        with st.spinner("正在查询数据库..."):
            try:
                query = """
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS count
                ORDER BY count DESC
                """
                df = run_query(driver, query)
                if df.empty:
                    st.warning("数据库为空，或未查询到带标签节点。")
                    return

                df = df.rename(columns={"label": "节点标签", "count": "数量"})
                st.success("统计信息获取成功。")
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.metric(label="总节点数", value=f"{int(df['数量'].sum()):,}")
            except Exception as exc:
                st.error(f"获取统计失败: {exc}")


def render_update_page():
    st.header("数据更新")
    st.warning("该操作将从 PubMed 获取最新文献并更新图谱，可能耗时较长。")

    if st.button("开始增量更新"):
        with st.spinner("任务已开始，正在连接 PubMed 并抓取增量文献..."):
            try:
                run_pipeline()
                st.success("任务完成，图谱已用最新文献更新。")
            except Exception as exc:
                st.error(f"更新失败: {exc}")


def main():
    st.set_page_config(page_title="BioKG Q&A", layout="wide", initial_sidebar_state="expanded")

    st.sidebar.title("导航")
    page = st.sidebar.radio(
        "选择页面",
        [
            "首页",
            "知识查询",
            "文献检索",
            "智能问答",
            "图谱统计",
            "数据更新",
        ],
    )
    st.sidebar.markdown("---")
    st.sidebar.info("BioKG 项目演示界面")

    driver = get_driver()
    if not driver:
        st.stop()

    page_map = {
        "首页": render_home_page,
        "知识查询": lambda: render_query_page(driver),
        "文献检索": lambda: render_literature_page(driver),
        "智能问答": render_rag_page,
        "图谱统计": lambda: render_stats_page(driver),
        "数据更新": render_update_page,
    }
    page_map[page]()


if __name__ == "__main__":
    main()
