from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run_step(script: str, *args: str) -> None:
    cmd = [sys.executable, str(ROOT / script), *args]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="一键运行第六章三组实验。")
    parser.add_argument("--model", type=str, default="deepseek-r1:7b")
    parser.add_argument("--qa-limit", type=int, default=None)
    args = parser.parse_args()

    run_step("generate_qa_testset.py")
    run_step("evaluate_qa_trustworthiness.py", "--model", args.model, *(["--limit", str(args.qa_limit)] if args.qa_limit else []))
    run_step("benchmark_graph_retrieval.py", "--model", args.model)
    run_step("generate_ner_annotation_template.py")
    run_step("evaluate_ner.py")


if __name__ == "__main__":
    main()
