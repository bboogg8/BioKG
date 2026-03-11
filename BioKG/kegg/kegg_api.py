# kegg_api.py
import requests
from config.config import KEGG_BASE_URL, ORGANISM


def kegg_get(endpoint: str) -> str:
    """
    通用 KEGG REST API 请求
    """
    url = f"{KEGG_BASE_URL}/{endpoint}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def get_all_pathways():
    """
    获取某个物种的全部通路（包含 overview）
    """
    text = kegg_get(f"list/pathway/{ORGANISM}")
    pathways = []

    for line in text.strip().split("\n"):
        pid, name = line.split("\t")
        pathways.append({
            "id": pid.replace("path:", ""),  # 如 hsa00010
            "name": name
        })

    return pathways


def is_real_pathway(pathway_id: str) -> bool:
    """
    判断是否为“具体通路”，排除 overview 通路

    规则（KEGG 通用）：
    - overview 通路编号通常为 xx011xx
    - 具体通路一般为 xx00010 / xx04010 / xx05200 等
    """
    try:
        number = int(pathway_id[-5:])  # 取最后 5 位数字
    except ValueError:
        return False

    # overview 通路区间
    if 1100 <= number <= 1199:
        return False

    return True


def get_real_pathways():
    """
    过滤掉 overview 通路
    """
    return [
        p for p in get_all_pathways()
        if is_real_pathway(p["id"])
    ]


def get_pathway_detail(pathway_id: str) -> str:
    """
    获取单条通路的原始 KEGG 文本
    """
    return kegg_get(f"get/{pathway_id}")


# ===========================
# 测试
# ===========================
if __name__ == "__main__":
    real = get_real_pathways()
    print(f"【{ORGANISM}】可用具体通路数量：{len(real)}")
    print("前5条通路：")
    for p in real[:5]:
        print(p)
