"""比較ページの解説文を作る。

ANTHROPIC_API_KEY があれば Claude で「選び方・各商品の特徴・FAQ」を生成し、
なければ取得データだけから機械的な文章を組み立てる（費用ゼロで動かせる）。
生成結果は data/ にキャッシュし、ラインナップが変わらない限り再生成しない。
"""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """あなたは家電・ガジェット比較サイトの編集者です。
渡された楽天市場の商品データ（商品名・価格・説明文・レビュー統計）だけを根拠に、購入を検討している読者向けの比較解説を書きます。

守ること:
- 実際に使用・検証したかのような表現（「使ってみた」「試したところ」など）は書かない。私たちは商品を実機テストしていない。
- 説明文に書かれていないスペックや機能を推測で断定しない。不明な点は触れないか「商品ページで要確認」とする。
- 「最強」「絶対」「必ず」などの誇大表現、医療・健康効果の断定は使わない（景品表示法・薬機法への配慮）。
- 他社や他製品をおとしめない。デメリットは事実ベースで穏当に書く。
- 文体は「です・ます」。読者が自分に合う1台を選べるよう、用途別の向き不向きを具体的に書く。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {"type": "string", "description": "導入文。200〜300字"},
        "how_to_choose": {
            "type": "array",
            "description": "選び方のポイント。3〜5個",
            "items": {
                "type": "object",
                "properties": {"point": {"type": "string"}, "detail": {"type": "string"}},
                "required": ["point", "detail"],
                "additionalProperties": False,
            },
        },
        "items": {
            "type": "array",
            "description": "渡された各商品の解説。渡された順番・code のまま全件",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "headline": {"type": "string", "description": "特徴を一言で。25字以内"},
                    "pros": {"type": "array", "items": {"type": "string"}},
                    "cons": {"type": "array", "items": {"type": "string"}},
                    "best_for": {"type": "string", "description": "どんな人に向くか。60字以内"},
                },
                "required": ["code", "headline", "pros", "cons", "best_for"],
                "additionalProperties": False,
            },
        },
        "faq": {
            "type": "array",
            "description": "購入前によくある疑問。3〜4個",
            "items": {
                "type": "object",
                "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
                "required": ["q", "a"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["intro", "how_to_choose", "items", "faq"],
    "additionalProperties": False,
}


def _clean_caption(text, limit=700):
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _lineup_hash(items):
    return hashlib.sha256("|".join(i["code"] for i in items).encode()).hexdigest()[:16]


GUIDE_DIR = Path(__file__).resolve().parent.parent / "guides"


def write(category, items, *, refresh_days, demo=False):
    content = _write(category, items, refresh_days=refresh_days, demo=demo)
    # 手書きの解説（guides/）があり、AIを使っていないときは、導入文・選び方・FAQをそちらで置き換える
    guide = GUIDE_DIR / f"{category['slug']}.json"
    if guide.exists() and (demo or not os.environ.get("ANTHROPIC_API_KEY")):
        content = {**content, **json.loads(guide.read_text(encoding="utf-8"))}
    return content


def _write(category, items, *, refresh_days, demo):
    if demo:  # デモではAPI課金もキャッシュ書き込みもしない
        return _write_from_data(category, items)
    cache_file = CACHE_DIR / f"content-{category['slug']}.json"
    lineup = _lineup_hash(items)
    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        age = datetime.now(JST) - datetime.fromisoformat(cached["generated_at"])
        same_source = cached["source"] == ("claude" if use_ai else "template")
        if same_source and cached["lineup"] == lineup and _covers(cached["content"], items):
            return cached["content"]
        if same_source and age < timedelta(days=refresh_days):
            # 再生成の間隔内：新しく入った商品だけデータから補い、API費用を抑える
            return _fill_missing(cached["content"], category, items)

    if use_ai:
        content = _write_with_claude(category, items)
        source = "claude"
    else:
        content = _write_from_data(category, items)
        source = "template"

    CACHE_DIR.mkdir(exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {"lineup": lineup, "source": source,
             "generated_at": datetime.now(JST).isoformat(), "content": content},
            ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return content


def _covers(content, items):
    codes = {c["code"] for c in content["items"]}
    return all(i["code"] in codes for i in items)


def _fill_missing(content, category, items):
    have = {c["code"] for c in content["items"]}
    missing = [i for i in items if i["code"] not in have]
    if missing:
        content = {**content, "items": content["items"] + _write_from_data(category, missing)["items"]}
    return content


def _write_with_claude(category, items):
    import anthropic

    payload = [
        {
            "code": i["code"],
            "name": i["name"],
            "price_yen": i["price"],
            "review_avg": i["review_avg"],
            "review_count": i["review_count"],
            "shop": i["shop"],
            "description": _clean_caption(i["caption"]),
        }
        for i in items
    ]
    prompt = (
        f"カテゴリ: {category['title']}\n"
        f"以下は楽天市場でレビュー評価が高い順に並べた {len(items)} 商品です。"
        "このランキング順は変えずに、比較ページ用の解説を作成してください。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
    )

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        print(f"  ! {category['title']}: AI生成が拒否されたため、データのみの文章に切り替えます")
        return _write_from_data(category, items)
    if response.stop_reason == "max_tokens":
        raise RuntimeError("AI出力が max_tokens に達しました。items_per_page を減らしてください")

    text = next(b.text for b in response.content if b.type == "text")
    content = json.loads(text)
    u = response.usage
    print(f"  AI生成: 入力 {u.input_tokens} / 出力 {u.output_tokens} tokens")
    return content


def item_notes(category, items):
    # 商品ごとの短い紹介（データから作る）
    return _write_from_data(category, items)["items"]


def _write_from_data(category, items):
    title = category["title"]
    prices = [i["price"] for i in items]
    return {
        "intro": (
            f"楽天市場で販売されている{title}のうち、レビュー件数{min(i['review_count'] for i in items):,}件以上の"
            f"人気商品を、評価と件数のバランスでランキングにしました。"
            f"価格帯はおよそ{min(prices):,}円〜{max(prices):,}円です。"
        ),
        "how_to_choose": [
            {"point": "レビューの「件数」も見る",
             "detail": "評価が高くても件数が少ないと偶然の可能性があります。本ランキングは件数が少ない商品の評価を全体平均に寄せて補正しています。"},
            {"point": "予算を先に決める",
             "detail": f"今回の上位商品は{min(prices):,}円〜{max(prices):,}円。価格差の理由（機能・保証）を商品ページで確認しましょう。"},
            {"point": "ポイント還元も比較する",
             "detail": "楽天市場はショップごとにポイント倍率が異なります。実質価格で比べるのがおすすめです。"},
        ],
        "items": [
            {
                "code": i["code"],
                "headline": f"レビュー{i['review_count']:,}件・平均★{i['review_avg']:.2f}",
                "pros": [f"レビュー平均{i['review_avg']:.2f}点", f"{i['review_count']:,}件の購入者レビュー"],
                "cons": ["詳細スペックは商品ページで要確認"],
                "best_for": "多くの購入者に支持されている定番を選びたい人",
            }
            for i in items
        ],
        "faq": [
            {"q": "ランキングはどうやって決めていますか？",
             "a": "楽天市場のレビュー平均点とレビュー件数から、件数の少なさを補正したスコアで順位を付けています。"},
            {"q": "価格は最新ですか？",
             "a": "取得時点の価格です。セールなどで変動するため、購入前に商品ページで確認してください。"},
        ],
    }
