# -*- coding: utf-8 -*-
# main.py
import argparse
import sys
from pipeline.update_pipeline import run_pipeline
from neo4j_utils.neo4j_conn import get_driver
# 导入 RAG 引擎中的两个核心函数
from RAG.rag_engine import get_knowledge_context, generate_answer_with_ollama

def main():
    parser = argparse.ArgumentParser(description="BioKG 知识图谱管理系统")
    parser.add_argument("--update", action="store_true", help="运行 PubMed 增量更新管道")
    parser.add_argument("--stats", action="store_true", help="查看数据库节点分布统计")
    parser.add_argument("--ask", type=str, help="查询特定酶的深度综述 (例如: --ask LDHA)")
    parser.add_argument("--model", type=str, default="deepseek-r1:7b", help="指定本地 Ollama 模型名称 (默认: deepseek-r1:7b)")
    
    args = parser.parse_args()

    # --- 1. 图谱统计功能 ---
    if args.stats:
        driver = get_driver()
        try:
            with driver.session() as session:
                result = session.run("""
                    MATCH (n) 
                    RETURN labels(n)[0] as label, count(n) as count
                """)
                print("\n📊 --- BioKG 当前图谱统计 ---")
                print("-" * 40)
                total = 0
                for record in result:
                    label = record['label'] if record['label'] else "Unlabeled"
                    count = record['count']
                    total += count
                    print(f"标签: {label:<15} | 数量: {count}")
                print("-" * 40)
                print(f"总节点数: {total}")
        except Exception as e:
            print(f"❌ 获取统计信息失败: {e}")
        finally:
            driver.close()

    # --- 2. 文献更新功能 ---
    elif args.update:
        print("\n🚀 [任务开始] 连接到 PubMed 并获取增量文献...")
        run_pipeline()
        print("\n🎉 [任务完成] 图谱已用最新文献更新。")

    # --- 3. 智能问答功能 (RAG 全链路) ---
    elif args.ask:
        print(f"\n🔍 [1/2 检索阶段] 从 Neo4j 中为 '{args.ask}' 提取多跳相关证据...")
        
        # 步骤 A: 检索图谱并构建上下文 Prompt
        prompt = get_knowledge_context(args.ask)
        
        # Check if valid content was retrieved (if it starts with ❌ or ⚠️, it is considered a failure)
        if prompt.startswith("❌") or prompt.startswith("⚠️"):
            print(prompt)
            sys.exit()

        print("✅ 检索完成。正在调用本地大模型进行分析...")
        print(f"🤖 [2/2 生成阶段] 模型: {args.model}")
        print("-" * 60)

        # 步骤 B: 调用本地 Ollama 获取答案
        # Note: This will enter inference, which may take 10-30 seconds, depending on your hardware
        final_answer = generate_answer_with_ollama(prompt, model_name=args.model)
        
        print("\n" + "✨ BioKG 智能分析报告 " + "✨")
        print("=" * 60)
        print(final_answer)
        print("=" * 60)
        print(f"\n💡 此答案是根据图谱中相关通路和 {args.ask} 的最新 PubMed 文献自动生成的。")

    # --- 4. 默认显示帮助 ---
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
