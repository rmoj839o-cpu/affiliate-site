"""楽天市場 商品検索API（2026年刷新後の openapi.rakuten.co.jp 版）クライアント。

必要な環境変数:
  RAKUTEN_APP_ID      … Rakuten Developers で発行した applicationId
  RAKUTEN_ACCESS_KEY  … 同じく accessKey（新APIで必須）
  RAKUTEN_AFFILIATE_ID… 楽天アフィリエイトID（affiliateUrl を返してもらうため）
"""
import os
import time
from urllib.parse import urlparse

import requests

BASE = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/"
# 2026年の刷新でバージョンが変わっているため、新しい順に試して通ったものを使い続ける
VERSIONS = ["20260401", "20220601"]
ENDPOINTS = [os.environ["RAKUTEN_ENDPOINT"]] if os.environ.get("RAKUTEN_ENDPOINT") else [BASE + v for v in VERSIONS]
_last_call = 0.0


def _wait_rate_limit():
    # 楽天APIは1アプリあたり概ね1リクエスト/秒
    global _last_call
    delta = time.time() - _last_call
    if delta < 1.1:
        time.sleep(1.1 - delta)
    _last_call = time.time()


def search(keyword, *, site_url, hits=30, ng_keyword="", sort="-reviewCount"):
    params = {
        "applicationId": os.environ["RAKUTEN_APP_ID"],
        "accessKey": os.environ["RAKUTEN_ACCESS_KEY"],
        "affiliateId": os.environ.get("RAKUTEN_AFFILIATE_ID", ""),
        "keyword": keyword,
        "hits": hits,
        "sort": sort,
        "availability": 1,
        "imageFlag": 1,
        "formatVersion": 2,
        "format": "json",
    }
    if ng_keyword:
        params["NGKeyword"] = ng_keyword
    # 新APIはサーバーからの呼び出しでも Referer が必要（登録済みドメインと照合される）
    # REQUEST_CONTEXT_BODY_HTTP_REFERRER_MISSING を避けるため Origin も送る（値は許可ドメインと一致させる）
    origin = "{0.scheme}://{0.netloc}".format(urlparse(site_url))
    headers = {"Referer": site_url + "/", "Origin": origin, "User-Agent": "autosite/1.0"}

    for attempt in range(4 + len(VERSIONS)):
        _wait_rate_limit()
        res = requests.get(ENDPOINTS[0], params=params, headers=headers, timeout=20)
        if res.status_code == 400 and "API Configuration not found" in res.text and len(ENDPOINTS) > 1:
            print(f"  {ENDPOINTS[0]} は使えないため次のバージョンを試します")
            ENDPOINTS.pop(0)
            continue
        if res.status_code == 429:
            time.sleep(2 ** attempt * 2)
            continue
        if res.status_code == 403:
            raise RuntimeError(
                "楽天APIが403を返しました。accessKey と、楽天アプリに登録した許可ドメインが "
                f"config.toml の site.url（{site_url}）と一致しているか確認してください。"
                f" 応答: {" ".join(res.text.split())[:400]}"
            )
        if not res.ok:
            raise RuntimeError(f"楽天APIエラー HTTP {res.status_code}: {" ".join(res.text.split())[:400]}")
        return [_normalize(i) for i in res.json().get("Items", [])]
    raise RuntimeError("楽天APIのレート制限が解除されませんでした")


def _normalize(raw):
    item = raw.get("Item", raw)  # formatVersion=1 / 2 の両方に対応
    images = item.get("mediumImageUrls") or []
    images = [i["imageUrl"] if isinstance(i, dict) else i for i in images]
    return {
        "code": item["itemCode"],
        "name": item["itemName"],
        "price": int(item["itemPrice"]),
        "url": item.get("affiliateUrl") or item["itemUrl"],
        "image": images[0].replace("?_ex=128x128", "?_ex=300x300") if images else "",
        "shop": item.get("shopName", ""),
        "caption": item.get("itemCaption", ""),
        "review_avg": float(item.get("reviewAverage") or 0),
        "review_count": int(item.get("reviewCount") or 0),
        "point_rate": int(item.get("pointRate") or 1),
    }
