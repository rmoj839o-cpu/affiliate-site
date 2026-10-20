"""取得 → ランキング → 解説生成 → 静的HTML出力 までを行う。

使い方:
  python -m autosite.build          # 本番（楽天APIから取得）
  python -m autosite.build --demo   # サンプルデータでローカル確認
"""
import argparse
import json
import os
import shutil
import tomllib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import links, rakuten, rank, social, writer
from .writer import JST

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


POPULAR_REVIEWS = 1000  # 「定番」ページに載せるレビュー件数の下限
MIN_SUBPAGE_ITEMS = 5   # これ未満しか集まらない条件のページは作らない（中身の薄いページを増やさない）


def load_items(category, cfg, demo, max_price=None):
    if demo:
        fixtures = json.loads((ROOT / "fixtures" / "sample_items.json").read_text(encoding="utf-8"))
        items = [dict(i) for i in fixtures.get(category["slug"], [])]
        return [i for i in items if not max_price or i["price"] <= max_price]
    return rakuten.search(
        category["keyword"],
        site_url=cfg["site"]["url"],
        hits=cfg["build"]["fetch_hits"],
        ng_keyword=category.get("ng", ""),
        min_price=category.get("min_price"),
        max_price=max_price,
    )


def mark_points(items):
    """各商品の「推しポイント」を、ほかの商品より優れている点から1つだけ選ぶ。"""
    for i in items:
        i["point"] = ""
    candidates = [
        ("レビュー数No.1", max(items, key=lambda i: i["review_count"])),
        ("上位でいちばん手頃", min(items, key=lambda i: i["price"])),
        ("評価がいちばん高い", max(items, key=lambda i: i["review_avg"])),
    ]
    for label, item in candidates:
        if not item["point"]:
            item["point"] = label


def prepare(items, cfg):
    if items:
        mark_points(items)
    for i in items:
        i["links"] = links.store_links(i, cfg.get("affiliate", {}))
        i["short_name"] = links.search_query(i["name"], max_words=5)
    return items


def build_subpages(cat, pool, cfg, demo):
    """価格帯別（〇円以下）と、レビューの多い定番だけを集めたページを作る。"""
    bcfg = cfg["build"]
    min_reviews = cat.get("min_reviews", bcfg["min_review_count"])
    subpages = []
    for band in cat.get("bands", []):
        try:
            found = load_items(cat, cfg, demo, max_price=band)
        except Exception as e:
            print(f"  ! {band}円以下の取得に失敗: {e}")
            continue
        found = filter_items(found, {**cat, "max_price": min(band, cat.get("max_price", band))})
        ranked = rank.rank(found, limit=bcfg["items_per_page"], min_reviews=min_reviews)
        if len(ranked) < MIN_SUBPAGE_ITEMS:
            continue
        lo, hi = min(i["price"] for i in ranked), max(i["price"] for i in ranked)
        subpages.append({
            "slug": f"under-{band}", "title": f"{band:,}円以下の{cat['title']}", "items": prepare(ranked, cfg),
            "description": f"{band:,}円以下で買える{cat['title']}を、楽天市場のレビュー件数と評価で比較したランキングです。",
            "intro": (f"楽天市場で販売されている{band:,}円以下の{cat['title']}から、レビューの多い人気商品を、"
                      f"評価と件数のバランスでランキングにしました。今回の{len(ranked)}商品の価格は"
                      f"{lo:,}円〜{hi:,}円です。予算を決めてから選びたい人は参考にしてください。"),
        })
    popular = [dict(i) for i in pool if i["review_count"] >= POPULAR_REVIEWS]
    ranked = rank.rank(popular, limit=bcfg["items_per_page"], min_reviews=POPULAR_REVIEWS)
    if len(ranked) >= MIN_SUBPAGE_ITEMS:
        subpages.append({
            "slug": "popular", "title": f"レビュー{POPULAR_REVIEWS:,}件以上の定番{cat['title']}",
            "items": prepare(ranked, cfg),
            "description": f"楽天市場でレビューが{POPULAR_REVIEWS:,}件以上ついている定番の{cat['title']}だけを集めたランキングです。",
            "intro": (f"楽天市場の{cat['title']}のうち、レビューが{POPULAR_REVIEWS:,}件以上ついている、"
                      "たくさんの人に選ばれてきた定番商品だけを集めてランキングにしました。"
                      "はじめて買うので失敗したくない、という人は参考にしてください。"),
        })
    return subpages


def active_categories(categories, now):
    """季節もの（months を指定したカテゴリ）は、その月だけ表示する。

    タイトルや検索語の {new_year} は「次に迎える正月の年」に置き換える
    （9〜12月なら翌年、1〜8月ならその年）。おせちの年号を毎年書き換えなくて済むように。
    """
    new_year = now.year + 1 if now.month >= 9 else now.year
    active = []
    for c in categories:
        if c.get("months") and now.month not in c["months"]:
            print(f"[{c['title']}] 季節外のためお休み")
            continue
        active.append({k: v.replace("{new_year}", str(new_year)) if isinstance(v, str) else v for k, v in c.items()})
    return active


def filter_items(items, category):
    # 検索語だけだと関係ない商品（炊飯器で検索したお米など）が混ざるので、商品名と価格でふるい落とす
    must = category.get("must", "").split()
    min_price = category.get("min_price", 0)
    max_price = category.get("max_price", float("inf"))
    # 名前の後ろのほうに検索よけの言葉を並べた商品もあるので、宣伝文句を除いた名前の先頭付近だけを見る
    kept = [i for i in items
            if (not must or any(w in links.clean_name(i["name"])[:40] for w in must))
            and min_price <= i["price"] <= max_price]
    if len(kept) < len(items):
        print(f"  関係なさそうな商品を{len(items) - len(kept)}件除外しました")
    return kept


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="楽天APIを使わずサンプルデータで生成")
    args = parser.parse_args()

    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    site, bcfg = cfg["site"], cfg["build"]
    now = datetime.now(JST)
    cfg["categories"] = active_categories(cfg["categories"], now)

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape())
    env.globals.update(site=site, updated=now.strftime("%Y年%m月%d日"), year=now.year,
                       categories=cfg["categories"], demo=args.demo,
                       base="" if args.demo else urlparse(site["url"]).path.rstrip("/"))

    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "static", DIST / "static")

    # 管理人のコラムは新しい順に並べる（date: "YYYY-MM-DD"）
    columns = sorted((json.loads(f.read_text(encoding="utf-8")) for f in (ROOT / "columns").glob("*.json")),
                     key=lambda c: c.get("date", ""), reverse=True)
    history = {} if args.demo else social.load_history()
    pages = []
    built = []
    for cat in cfg["categories"]:
        print(f"[{cat['title']}]")
        try:
            items = load_items(cat, cfg, args.demo)
        except Exception as e:  # 1カテゴリの失敗でサイト全体を止めない
            print(f"  ! 取得失敗: {e}")
            if os.environ.get("GITHUB_ACTIONS"):  # Actions画面の注釈にも出して、原因を見つけやすくする
                print(f"::error title={cat['title']}::{type(e).__name__}: {e}")
            continue
        items = filter_items(items, cat)
        pool = [dict(i) for i in items]  # rank() が順位を書き込むので、条件別ページ用に元の状態を残す
        ranked = rank.rank(items, limit=bcfg["items_per_page"], min_reviews=cat.get("min_reviews", bcfg["min_review_count"]))
        if not ranked:
            print("  ! 条件を満たす商品がありません")
            continue
        prepare(ranked, cfg)
        content = writer.write(cat, ranked, refresh_days=bcfg["ai_refresh_days"], demo=args.demo)
        notes = {c["code"]: c for c in content["items"]}
        hl = rank.highlights(ranked, history.get(cat["slug"], {}))

        subpages = build_subpages(cat, pool, cfg, args.demo)
        out = DIST / cat["slug"] / "index.html"
        out.parent.mkdir(parents=True)
        out.write_text(env.get_template("category.html").render(
            cat=cat, items=ranked, notes=notes, content=content, hl=hl, subpages=subpages,
            columns=[c for c in columns if c["category"] == cat["slug"]],
            path=f"/{cat['slug']}/",
        ), encoding="utf-8")
        pages.append(f"/{cat['slug']}/")
        for sp in subpages:
            sp_notes = {**{c["code"]: c for c in writer.item_notes(cat, sp["items"])}, **notes}
            sp_out = DIST / cat["slug"] / sp["slug"] / "index.html"
            sp_out.parent.mkdir(parents=True)
            sp_out.write_text(env.get_template("subpage.html").render(
                cat=cat, sp=sp, items=sp["items"], notes=sp_notes,
                siblings=[o for o in subpages if o is not sp], path=f"/{cat['slug']}/{sp['slug']}/",
            ), encoding="utf-8")
            pages.append(f"/{cat['slug']}/{sp['slug']}/")
        cat_subpages = [{"slug": sp["slug"], "title": sp["title"], "count": len(sp["items"])} for sp in subpages]
        built.append({**cat, "subpages_summary": cat_subpages, "group_key": cat.get("group", "kaden"), "top": ranked[0], "count": len(ranked), "items": ranked, "highlights": hl,
                      "tips": content["how_to_choose"], "intro": content["intro"]})
        print(f"  {len(ranked)}件で生成しました（条件別ページ {len(subpages)}件）")

    if not args.demo:
        # 毎日のランキングを記録に残す（変な商品が混ざっていないか後から確認できるように）
        snapshot = {c["slug"]: [{k: i[k] for k in ("rank", "name", "price", "review_avg", "review_count", "shop")}
                                for i in c["items"]] for c in built}
        (ROOT / "data" / "ranking.json").write_text(
            json.dumps({"date": now.strftime("%Y-%m-%d"), "ranking": snapshot,
                        "subpages": {c["slug"]: c["subpages_summary"] for c in built}}, ensure_ascii=False, indent=1),
            encoding="utf-8")

    if not built:
        # 全カテゴリ失敗（APIキー未設定など）のときは、空のサイトで上書き公開しないよう止める
        raise SystemExit("どのカテゴリも生成できませんでした。楽天APIの設定を確認してください。")
    # 季節外れなどでカテゴリが出ていないコラムは、リンク切れにならないよう載せない
    by_slug = {c["slug"]: c for c in built}
    columns = [c for c in columns if c["category"] in by_slug]

    # トップページは毎日ちがう特集カテゴリを出して、値下がり・急上昇もまとめる
    featured = built[now.toordinal() % len(built)]
    tip = featured["tips"][(now.toordinal() // len(built)) % len(featured["tips"])] if featured["tips"] else None
    drops = [(c, i, old) for c in built for i, old in c["highlights"]["drops"]]
    trending = sorted(((c, *c["highlights"]["trending"]) for c in built if c["highlights"]["trending"]),
                      key=lambda t: t[2], reverse=True)
    (DIST / "index.html").write_text(
        env.get_template("index.html").render(built=built, featured=featured, tip=tip, columns=columns, drops=drops[:8],
                                              trending=trending[:5], path="/"), encoding="utf-8")
    # まとめページ：全ジャンルの1位と予算重視の1品を1ページで見比べられるように
    season = {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春", 6: "夏", 7: "夏", 8: "夏"}.get(now.month, "秋冬")
    for c in built:
        c["summary"] = c["intro"].split("。")[0] + "。" if c.get("intro") else ""
    (DIST / "matome").mkdir()
    (DIST / "matome" / "index.html").write_text(
        env.get_template("matome.html").render(
            built=built, season=f"{now.year}年{season}", path="/matome/",
            groups=[("kaden", "便利家電・グッズ"), ("outdoor", "アウトドア"), ("food", "季節の食べ物")]), encoding="utf-8")
    pages.append("/matome/")

    # 管理人のコラム（体験談）。該当カテゴリの今の上位3商品もあわせて載せる
    for col in columns:
        cat = by_slug[col["category"]]
        out = DIST / "column" / col["slug"] / "index.html"
        out.parent.mkdir(parents=True)
        out.write_text(env.get_template("column.html").render(
            col=col, cat=cat, items=cat["items"], path=f"/column/{col['slug']}/"), encoding="utf-8")
        pages.append(f"/column/{col['slug']}/")
    if columns:
        (DIST / "column" / "index.html").write_text(
            env.get_template("column_index.html").render(columns=columns, by_slug=by_slug, path="/column/"),
            encoding="utf-8")
        pages.append("/column/")

    (DIST / "about").mkdir()
    (DIST / "about" / "index.html").write_text(
        env.get_template("about.html").render(path="/about/"), encoding="utf-8")
    pages += ["/", "/about/"]

    lastmod = now.strftime("%Y-%m-%d")
    urls = "".join(f"<url><loc>{site['url']}{p}</loc><lastmod>{lastmod}</lastmod></url>" for p in pages)
    (DIST / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', encoding="utf-8")
    robots = "User-agent: *\nDisallow: /\n" if args.demo else f"User-agent: *\nAllow: /\nSitemap: {site['url']}/sitemap.xml\n"
    (DIST / "robots.txt").write_text(robots, encoding="utf-8")
    (DIST / ".nojekyll").write_text("")
    social.run(built, site, site["url"], ROOT / "drafts.md", DIST, demo=args.demo)
    print(f"完了: {DIST}")


if __name__ == "__main__":
    main()
