"""レビュー件数と評価からランキングを作る。

単純な平均点だと「レビュー3件で★5.0」が上位に来てしまうので、
ベイズ平均（件数が少ない商品は全体平均に寄せる）でスコア化する。
"""
import re

PRIOR_WEIGHT = 50  # この件数ぶんの「全体平均レビュー」を仮に足して補正する


def _base_name(name):
    # 色違い・容量違いの同一商品を重複扱いにするための簡易キー
    name = re.sub(r"[【\[（(].*?[】\]）)]", "", name)
    name = re.sub(r"\s+", "", name)
    return name[:24]


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
        key = _base_name(i["name"])
        if key in seen:
            continue
        seen.add(key)
        ranked.append(i)
        if len(ranked) == limit:
            break
    for pos, i in enumerate(ranked, 1):
        i["rank"] = pos
    return ranked
