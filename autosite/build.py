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


def load_items(category, cfg, demo):
    if demo:
        fixtures = json.loads((ROOT / "fixtures" / "sample_items.json").read_text(encoding="utf-8"))
        return [dict(i) for i in fixtures.get(category["slug"], [])]
    return rakuten.search(
        category["keyword"],
        site_url=cfg["site"]["url"],
        hits=cfg["build"]["fetch_hits"],
        ng_keyword=category.get("ng", ""),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="楽天APIを使わずサンプルデータで生成")
    args = parser.parse_args()

    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    site, bcfg = cfg["site"], cfg["build"]
    now = datetime.now(JST)

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape())
    env.globals.update(site=site, updated=now.strftime("%Y年%m月%d日"), year=now.year,
                       categories=cfg["categories"], demo=args.demo,
                       base="" if args.demo else urlparse(site["url"]).path.rstrip("/"))

    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "static", DIST / "static")

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
        ranked = rank.rank(items, limit=bcfg["items_per_page"], min_reviews=bcfg["min_review_count"])
        if not ranked:
            print("  ! 条件を満たす商品がありません")
            continue
        for i in ranked:
            i["links"] = links.store_links(i, cfg.get("affiliate", {}))
        content = writer.write(cat, ranked, refresh_days=bcfg["ai_refresh_days"], demo=args.demo)
        notes = {c["code"]: c for c in content["items"]}

        out = DIST / cat["slug"] / "index.html"
        out.parent.mkdir(parents=True)
        out.write_text(env.get_template("category.html").render(
            cat=cat, items=ranked, notes=notes, content=content,
            path=f"/{cat['slug']}/",
        ), encoding="utf-8")
        pages.append(f"/{cat['slug']}/")
        built.append({**cat, "top": ranked[0], "count": len(ranked), "items": ranked})
        print(f"  {len(ranked)}件で生成しました")

    if not built:
        # 全カテゴリ失敗（APIキー未設定など）のときは、空のサイトで上書き公開しないよう止める
        raise SystemExit("どのカテゴリも生成できませんでした。楽天APIの設定を確認してください。")

    (DIST / "index.html").write_text(
        env.get_template("index.html").render(built=built, path="/"), encoding="utf-8")
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
