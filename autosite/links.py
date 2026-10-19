"""各商品に「Amazon / 楽天市場 / Yahoo!ショッピング」のボタン用リンクを付ける。

楽天は商品ページへのアフィリエイトリンク。Amazon と Yahoo! は商品名での検索結果ページにリンクする。
config.toml の [affiliate] にIDを入れるとアフィリエイトリンクになり、空なら普通のリンクになる。
"""
import re
from urllib.parse import quote, quote_plus

# 楽天の商品名によく入る宣伝文句。検索語には不要なので取り除く
NOISE = re.compile(
    r"\+?P\d+(倍)?で?[\d,]*円?|[\d,]+円(OFF|引き|オフ)?|ポイント\d*倍|P\d+倍|"
    r"楽天\d*(位|冠)|ランキング\d*(位|冠)|\d+冠|送料無料|正規品|あす楽|即納|翌日配送|当日発送|"
    r"クーポン(利用)?で?|最大\d+%?(OFF|オフ)?|\d+%(OFF|オフ)|スーパーSALE|お買い物マラソン|"
    r"セール|SALE|新品|公式|期間限定|半額|\d+年保証|月間優良ショップ|レビュー特典"
)


def clean_name(name):
    # 括弧書きの宣伝・セール文句・記号を取り除いた商品名
    name = re.sub(r"[【\[（(＜<《「『].*?[】\]）)＞>》」』]", " ", name)
    name = NOISE.sub(" ", name)
    name = re.sub(r"[★☆◆◇■□●○※!！/／|｜＼\\]", " ", name)
    return " ".join(name.split())


def search_query(name, max_words=4):
    name = clean_name(name)
    words = [w for w in name.split() if len(w) > 1]
    return " ".join(words[:max_words]) or name.strip()[:30]


def store_links(item, aff):
    q = search_query(item["name"])
    amazon = "https://www.amazon.co.jp/s?k=" + quote_plus(q)
    if aff.get("amazon_tag"):
        amazon += "&tag=" + quote_plus(aff["amazon_tag"])
    yahoo = "https://shopping.yahoo.co.jp/search?p=" + quote_plus(q)
    yahoo_aff = bool(aff.get("valuecommerce_sid") and aff.get("valuecommerce_pid"))
    if yahoo_aff:  # Yahoo!ショッピングのアフィリエイトはバリューコマース経由
        yahoo = (
            "https://ck.jp.ap.valuecommerce.com/servlet/referral"
            f"?sid={aff['valuecommerce_sid']}&pid={aff['valuecommerce_pid']}&vc_url={quote(yahoo, safe='')}"
        )
    return [
        {"store": "amazon", "label": "Amazon", "url": amazon, "sponsored": bool(aff.get("amazon_tag"))},
        {"store": "rakuten", "label": "楽天市場", "url": item["url"], "sponsored": True},
        {"store": "yahoo", "label": "Yahoo!ショッピング", "url": yahoo, "sponsored": yahoo_aff},
    ]
