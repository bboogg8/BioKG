import requests
import json
from ..neo4j_utils.neo4j_conn import get_driver

def generate_answer_with_ollama(prompt, model_name="deepseek-r1:7b"):
    """
    调用本地 Ollama 服务生成最终回答，并对结果进行去重处理。
    """
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False  # 设置为 False 获取完整回复，而非流式输出
    }
    
    try:
        # 增加超时设置，因为大模型推理较慢
        response = requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        result = response.json()
        raw_response = result.get("response", " 模型未能返回任何内容")

        # 对生成的答案进行行级别去重
        lines = raw_response.split('\n')
        seen_lines = set()
        deduplicated_lines = []
        for line in lines:
            stripped_line = line.strip()
            if stripped_line and stripped_line not in seen_lines:
                deduplicated_lines.append(line)
                seen_lines.add(stripped_line)
            elif not stripped_line: # 保留空行以维持格式
                deduplicated_lines.append(line)
        
        return '\n'.join(deduplicated_lines)

    except requests.exceptions.ConnectionError:
        return " 无法连接到 Ollama，请确保已在后台运行 'ollama run deepseek-r1:7b'"
    except Exception as e:
        return f"?? LLM 调用异常: {str(e)}"

def get_knowledge_context(enzyme_name):
    """
    1. 从图谱中检索特定酶的【多跳关系】（涉及的通路、化合物及最新文献）
    2. 生成 RAG Prompt
    """
    driver = get_driver()
    
# 终极兼容版查询：处理属性名空格、类型转换及模糊匹配
    query = """
    MATCH (e)
    WHERE (e:Protein OR e:Enzyme) AND (
        // 1. 匹配官方名称 (忽略大小写)
        toUpper(e.name) = toUpper($name) OR 
        toUpper(e.`Entry Name`) = toUpper($name) OR
        
        // 2. 匹配 EC 编号：强制转换为字符串处理，防止存储格式为列表导致匹配失败
        toString(e.`EC number`) CONTAINS $name OR
        toString(e.ec) CONTAINS $name
    )
    
    WITH e LIMIT 1  // 找到一个锚点节点
    
    // 检索关联文献 (MENTIONS_EC 关系)
    OPTIONAL MATCH (e)-[r:MENTIONS_EC]-(p:Publication)
    WITH e, p, r ORDER BY p.pmid DESC
    
    // 检索关联节点 (Pathway/Compound)
    OPTIONAL MATCH (e)--(linked)
    
    RETURN 
        coalesce(e.name, e.`Entry Name`, "Unknown Enzyme") AS official_name,
        coalesce(e.`EC number`, e.ec, "N/A") AS ec_number,
        collect(distinct CASE WHEN 'Pathway' IN labels(linked) THEN linked.name END) AS pathways,
        collect(distinct CASE WHEN 'Compound' IN labels(linked) THEN linked.name END) AS compounds,
        collect(distinct {pmid: p.pmid, abstract: p.abstract, method: r.method})[0..3] AS lit_evidence
    """
    
    try:
        with driver.session() as session:
            result = session.run(query, name=enzyme_name)
            record = result.single()
            
            if not record or not record['official_name']:
                return f" 抱歉，目前的图谱中尚未找到关于 '{enzyme_name}' 的任何数据。"

            # 提取数据
            official_name = record['official_name']
            ec_num = record['ec_number']
            pathways = record['pathways']
            compounds = record['compounds']
            evidence = record['lit_evidence']

            # --- 组装结构化 Prompt ---
            prompt = f"### [BioKG 专家系统检索报告] ###\n\n"
            prompt += f"目标实体：{official_name} (EC: {ec_num})\n"
            
            if pathways:
                prompt += f"涉及代谢通路：{', '.join(pathways)}\n"
            if compounds:
                prompt += f"相关化学物质：{', '.join(compounds[:10])}\n"
            
            prompt += "\n以下是从 PubMed 检索到的最新科研证据：\n"
            
            context_text = ""
            for i, paper in enumerate(evidence, 1):
                if paper['pmid']:
                    clean_abs = paper['abstract'].replace('\n', ' ').strip()[:600]
                    context_text += f"\n证据 {i} [PMID: {paper['pmid']}] (匹配方法: {paper['method']}):\n{clean_abs}...\n"
            
            if not context_text:
                return f" 找到了酶 '{official_name}' 的静态信息，但暂无关联文献。请运行 --update 获取更多背景。"

            prompt += context_text
            prompt += "\n\n--- 任务要求 ---\n"
            prompt += "1. 请严格基于提供的证据进行总结。\n"
            prompt += "2. 在描述关键发现时，请务必在括号内标注证据来源的 PMID（例如：研究发现... [PMID: xxxxx]）。\n"
            prompt += "3. 如果图谱中提到了具体的 Pathway（通路），请重点描述该酶在其中的位置。"
            return prompt

    except Exception as e:
        return f" 数据库检索失败: {str(e)}"
    finally:
        driver.close()
