"""商品名・商品説明から消費電力（W）を読み取って、1時間あたりの電気代の目安を出す。

商品によって書き方がばらばらなので、読み取れたものだけに表示する。
「消費電力」の近くに書かれた数字を優先し、なければ商品名の中の「〇W」を使う。
"""
import re

YEN_PER_KWH = 31  # 全国家庭電気製品公正取引協議会の目安単価
WATT = r"([0-9０-９][0-9０-９,，]*)\s*[WＷ](?![a-zA-Zａ-ｚＡ-Ｚh])"
NEAR = re.compile(r"消費電力[^0-9０-９]{0,12}((?:[^。\n]{0,40}?" + WATT + r")+)")


def _num(s):
    return int(s.translate(str.maketrans("０１２３４５６７８９", "0123456789")).replace(",", "").replace("，", ""))


def watts(item, lo, hi):
    text = item.get("caption", "") or ""
    for m in NEAR.finditer(text):
        found = [w for w in (_num(x) for x in re.findall(WATT, m.group(1))) if lo <= w <= hi]
        if found:
            return max(found)
    found = [w for w in (_num(x) for x in re.findall(WATT, item["name"])) if lo <= w <= hi]
    return max(found) if found else None


def annotate(items, category):
    rng = category.get("power")
    if not rng:
        return
    for i in items:
        w = watts(i, *rng)
        if w:
            i["watts"] = w
            i["yen_per_hour"] = round(w / 1000 * YEN_PER_KWH, 1)
