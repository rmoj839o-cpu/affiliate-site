"""おせちの「早割・注文の締め切り・冷凍か冷蔵か・何人前で何品か」を、商品名と説明文から読み取る。

楽天の商品名や説明文の書き方はお店ごとにばらばらなので、読み取れたものだけを表に出し、
読み取れないところは「―」にする（必ず商品ページで確認してもらう前提の目安）。
"""
import re

Z2H = str.maketrans("０１２３４５６７８９／～〜", "0123456789/~~")


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").translate(Z2H))


def _md(m, month_group=1, day_group=2):
    return f"{int(m.group(month_group))}/{int(m.group(day_group))}"


def early(text):
    """早割の締め切り（例 "11/30まで"）。"""
    for pat in (r"(?:早割|早期割引|早期予約割|早得)[^。\n]{0,20}?(\d{1,2})[/月](\d{1,2})日?\s*(?:迄|まで|23:59)",
                r"(\d{1,2})[/月](\d{1,2})日?\s*(?:迄|まで)[^。\n]{0,10}?(?:早割|早期割引|早得)"):
        m = re.search(pat, text)
        if m and 9 <= int(m.group(1)) <= 12:
            return _md(m) + "まで"
    m = re.search(r"(\d{1,2})[・,、](\d{1,2})月限定", text)
    if m and "早割" in text:
        return f"{int(m.group(2))}月末まで"
    return None


def deadline(text):
    """注文の締め切り（例 "12/25まで"）。"""
    for pat in (r"(?:申込|申し込み|お申込み|注文|ご注文|予約|受付)(?:の)?(?:締切|締め切り|〆切|〆|期限|終了)[^。\n]{0,15}?(\d{1,2})[/月](\d{1,2})",
                r"(\d{1,2})[/月](\d{1,2})日?[^。\n]{0,6}?(?:申込|注文|予約|受付)(?:締切|締め切り|〆切|終了|まで)",
                r"(?:ご注文|お申込み|ご予約)は[^。\n]{0,10}?(\d{1,2})[/月](\d{1,2})日?[^。\n]{0,12}?(?:まで|迄)",
                r"(?:締切|〆切)日?[:：\s]*(\d{1,2})[/月](\d{1,2})"):
        m = re.search(pat, text)
        if m and int(m.group(1)) in (11, 12):
            return _md(m) + "まで"
    return None


def temperature(name, caption):
    for text in (name, caption):
        for word, label in (("冷凍", "冷凍"), ("生おせち", "冷蔵"), ("冷蔵", "冷蔵"), ("常温", "常温")):
            if word in text:
                return label
    return None


def servings(text):
    m = re.search(r"(\d)\s*(?:~|-|～)\s*(\d)\s*人前", text) or re.search(r"(\d)\s*人前", text)
    if m:
        return f"{m.group(1)}〜{m.group(2)}人前" if m.lastindex == 2 else f"{m.group(1)}人前"
    m = re.search(r"([一二三])人前", text)  # 「一人前」のように漢数字で書かれているとき
    return f"{'一二三'.index(m.group(1)) + 1}人前" if m else None


def evidence(caption):
    """読み取りの確認用に、説明文の中の締め切りまわりの文を残す。"""
    m = re.search(r".{0,40}(?:締切|締め切り|〆切|受付終了|受付期間|ご注文は|早期割引).{0,40}", _norm(caption))
    return m.group(0) if m else ""


def dishes(text):
    m = re.search(r"(\d{1,2})\s*品(?!質|種)", text)
    return f"{int(m.group(1))}品" if m and 3 <= int(m.group(1)) <= 60 else None


def parse(item):
    name = _norm(item["name"])
    caption = _norm(item.get("caption", ""))
    return {
        "rank": item["rank"],
        "short_name": item["short_name"],
        "early": early(name) or early(caption),
        "deadline": deadline(caption) or deadline(name),
        "temp": temperature(name, caption),
        "servings": servings(name) or servings(caption),
        "dishes": dishes(name) or dishes(caption),
    }


def rows(items):
    return [parse(i) for i in items]
