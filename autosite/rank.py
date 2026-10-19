"""レビュー件数と評価からランキングを作る。

単純な平均点だと「レビュー3件で★5.0」が上位に来てしまうので、
ベイズ平均（件数が少ない商品は全体平均に寄せる）でスコア化する。
"""
from .links import search_query

PRIOR_WEIGHT = 50  # この件数ぶんの「全体平均レビュー」を仮に足して補正する


def _base_name(item):
    # 色違い・容量違いや、同じショップの出品違いを重複扱いにするための簡易キー
    return item["shop"] + "|" + search_query(item["name"], max_words=3)


def rank(items, *, limit, min_reviews):
    pool = [i for i in items if i["review_count"] >= min_reviews]
    if not pool:
        return []
    mean = sum(i["review_avg"] for i in pool) / len(pool)
    for i in pool:
        n = i["review_count"]
        i["score"] = round((PRIOR_WEIGHT * mean + n * i["review_avg"]) / (PRIOR_WEIGHT + n), 3)
    pool.sort(key=lambda i: i["score"], reverse=True)

    seen, ranked = set(), []
    for i in pool:
        key = _base_name(i)
        if key in seen:
            continue
        seen.add(key)
        ranked.append(i)
        if len(ranked) == limit:
            break
    for pos, i in enumerate(ranked, 1):
        i["rank"] = pos
    return ranked


TRENDING_MIN = 20  # 前回からこれ以上レビューが増えた商品を「急上昇」とする
PRICE_DROP = 0.10  # 10%以上の値下がりを話題にする


def highlights(items, prev):
    """毎日見せ方を変えるための「今日の注目」。順位そのものは変えず、データの切り口だけを変える。"""
    prev_prices = prev.get("prices", {})
    prev_reviews = prev.get("reviews", {})
    drops = [(i, prev_prices[i["code"]]) for i in items
             if prev_prices.get(i["code"]) and i["price"] <= prev_prices[i["code"]] * (1 - PRICE_DROP)]
    growth = [(i, i["review_count"] - prev_reviews[i["code"]]) for i in items if i["code"] in prev_reviews]
    growth = [g for g in growth if g[1] >= TRENDING_MIN]
    return {
        "budget": min(items, key=lambda i: i["price"]),
        "most_reviewed": max(items, key=lambda i: i["review_count"]),
        "drops": drops,
        "trending": max(growth, key=lambda g: g[1]) if growth else None,
    }
