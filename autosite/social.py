"""毎日のSNS投稿案（X / Threads 向け）を作る。

前日のランキングと比べて「1位が入れ替わった」「値下がりした」などの話題を拾い、
投稿文の下書きを drafts.md に書き出す。投稿は人が内容を確認してから手動で行う前提
（自動投稿はアカウント凍結や規約違反のリスクが高いため、あえて作らない）。
"""
import json
import os
from datetime import datetime

from .writer import CACHE_DIR, JST, MODEL

HISTORY_FILE = CACHE_DIR / "history.json"
MAX_DRAFTS = 3
PRICE_DROP = 0.10  # 10%以上の値下がりを話題にする

SYSTEM_PROMPT = """あなたは「ひとり暮らしの家電えらび」を手伝う比較サイトのSNS担当です。
渡された話題ごとに、X（旧Twitter）にそのまま貼れる投稿文を1つずつ書きます。

守ること:
- 全角110字以内（URLとハッシュタグは別に付けるので本文に含めない）。
- 親しみやすい口調。ただし「神」「最強」「絶対買い」などの誇大表現は使わない。
- 実際に使ったかのような体験談を作らない。数字（価格・レビュー件数・評価）は渡されたものだけを使う。
- 価格は変わることがあるので「今見たら」「〇日時点」のように時点が分かる書き方にする。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"topic_id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["topic_id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["posts"],
    "additionalProperties": False,
}


def _short(name, n=28):
    from .links import search_query
    q = search_query(name, max_words=5)
    return q if len(q) <= n else q[:n] + "…"


def find_topics(built, history, today):
    """前回の結果と比べて話題を拾う。話題が少ない日は、日替わりでカテゴリを紹介する。"""
    topics = []
    for cat in built:
        prev = history.get(cat["slug"], {})
        prev_prices = prev.get("prices", {})
        top = cat["items"][0]
        if prev and prev.get("top") != top["code"]:
            topics.append({"kind": "new_top", "cat": cat, "item": top,
                           "note": f"{cat['title']}ランキングの1位が入れ替わった"})
        for i in cat["items"][:5]:
            old = prev_prices.get(i["code"])
            if old and i["price"] <= old * (1 - PRICE_DROP):
                topics.append({"kind": "price_drop", "cat": cat, "item": i, "old_price": old,
                               "note": f"{old:,}円 → {i['price']:,}円に値下がり"})
    if len(topics) < MAX_DRAFTS and built:
        cat = built[today.toordinal() % len(built)]
        topics.append({"kind": "pickup", "cat": cat, "item": cat["items"][0],
                       "note": f"{cat['title']}の今日のおすすめ（ランキング1位）"})
    # 値下がりを優先し、同じ商品の重複は除く
    topics.sort(key=lambda t: {"price_drop": 0, "new_top": 1, "pickup": 2}[t["kind"]])
    seen, picked = set(), []
    for t in topics:
        if t["item"]["code"] not in seen:
            seen.add(t["item"]["code"])
            picked.append(t)
    return picked[:MAX_DRAFTS]


def _template_text(t, today):
    i, cat = t["item"], t["cat"]
    day = f"{today.month}/{today.day}"
    if t["kind"] == "price_drop":
        return (f"{day}時点で、{cat['title']}ランキング{i['rank']}位の「{_short(i['name'])}」が"
                f"{t['old_price']:,}円→{i['price']:,}円に値下がりしていました。"
                f"レビュー{i['review_count']:,}件・★{i['review_avg']:.2f}の人気モデルです。")
    if t["kind"] == "new_top":
        return (f"{cat['title']}ランキングの1位が入れ替わりました。"
                f"新1位は「{_short(i['name'])}」（★{i['review_avg']:.2f}・レビュー{i['review_count']:,}件）。"
                f"{day}時点で{i['price']:,}円です。")
    return (f"ひとり暮らしの{cat['title']}選び、迷ったらレビューの「件数」も見るのがおすすめ。"
            f"今いちばん評価が安定しているのは「{_short(i['name'])}」"
            f"（★{i['review_avg']:.2f}・{i['review_count']:,}件）でした。")


def _ai_texts(topics, today):
    import anthropic

    payload = [
        {"topic_id": n, "topic": t["note"], "category": t["cat"]["title"],
         "product": _short(t["item"]["name"], 40), "price_yen": t["item"]["price"],
         "review_avg": t["item"]["review_avg"], "review_count": t["item"]["review_count"]}
        for n, t in enumerate(topics)
    ]
    response = anthropic.Anthropic().beta.messages.create(
        model=MODEL,
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content":
                   f"今日は{today:%Y年%m月%d日}です。次の話題それぞれについて投稿文を書いてください。\n"
                   + json.dumps(payload, ensure_ascii=False, indent=1)}],
    )
    if response.stop_reason != "end_turn":
        return {}
    text = next(b.text for b in response.content if b.type == "text")
    return {p["topic_id"]: p["text"] for p in json.loads(text)["posts"]}


def run(built, site, base_url, out_path, demo=False):
    today = datetime.now(JST)
    history = {} if demo or not HISTORY_FILE.exists() else json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    topics = find_topics(built, history, today)

    ai = {}
    if topics and not demo and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            ai = _ai_texts(topics, today)
        except Exception as e:  # 投稿案の失敗でサイト更新を止めない
            print(f"  ! 投稿案のAI生成に失敗: {e}")

    lines = [f"# SNS投稿案 {today:%Y/%m/%d}", "",
             "内容を確認してから、コピーして投稿してください。",
             "**#PR は消さないでください**（アフィリエイトリンクを含む投稿には広告表記が必要です）。", ""]
    for n, t in enumerate(topics):
        body = ai.get(n) or _template_text(t, today)
        url = f"{base_url}/{t['cat']['slug']}/#rank{t['item']['rank']}"
        tag = "#" + t["cat"]["title"].split("（")[0].replace("・", "")
        lines += [f"## 案{n + 1}：{t['note']}", "", "```", f"{body}", "", f"{url}", f"#PR {tag} #一人暮らし", "```", ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")

    if not demo:
        CACHE_DIR.mkdir(exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(
            {c["slug"]: {"top": c["items"][0]["code"],
                         "prices": {i["code"]: i["price"] for i in c["items"]}} for c in built},
            ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"投稿案 {len(topics)}件: {out_path}")
