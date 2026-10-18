"""Instagram 用の紹介画像（1080×1080 の文字カード）を作る。

楽天の商品写真を SNS に転載すると著作権・規約上の問題になりうるので、
写真は使わず、ランキングの数字だけを載せたオリジナル画像にしている。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 1080
BG = (250, 248, 242)
ACCENT = (191, 0, 0)
TEXT = (31, 35, 40)
MUTED = (95, 102, 112)
SOFT = (238, 234, 222)

# GitHub Actions では fonts-noto-cjk を入れる。ローカルでは見つかった日本語フォントを使う
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

LABELS = {"price_drop": "値下がり情報", "new_top": "ランキング1位が交代", "pickup": "今日のおすすめ"}


def _font(size):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise RuntimeError("日本語フォントが見つかりません（fonts-noto-cjk をインストールしてください）")


def _fit(draw, text, size, width):
    # 枠に収まるまで文字を小さくする
    while size > 20 and draw.textlength(text, font=_font(size)) > width:
        size -= 2
    return _font(size)


def _wrap(draw, text, font, width):
    lines, line = [], ""
    for ch in text:
        if draw.textlength(line + ch, font=font) > width:
            lines.append(line)
            line = ch
        else:
            line += ch
    return lines + [line] if line else lines


def make_card(topic, product_name, site_name, today, path):
    item, cat = topic["item"], topic["cat"]
    img = Image.new("RGB", (SIZE, SIZE), BG)
    d = ImageDraw.Draw(img)
    pad = 80

    # 上の帯：話題の種類
    d.rectangle([0, 0, SIZE, 170], fill=ACCENT)
    d.text((pad, 85), LABELS[topic["kind"]], font=_font(64), fill="white", anchor="lm")
    d.text((SIZE - pad, 85), "#PR", font=_font(40), fill="white", anchor="rm")

    y = 240
    title = cat["title"] if "暮らし" in cat["title"] else f"ひとり暮らしの{cat['title']}"
    d.text((pad, y), title, font=_fit(d, title, 46, SIZE - pad * 2), fill=MUTED)
    y += 90
    d.text((pad, y), f"ランキング {item['rank']}位", font=_font(84), fill=TEXT)
    y += 140

    name_font = _font(52)
    lines = _wrap(d, product_name, name_font, SIZE - pad * 2)
    if len(lines) > 2:
        lines = [lines[0], lines[1][:-1] + "…"]
    for line in lines:
        d.text((pad, y), line, font=name_font, fill=TEXT)
        y += 72
    y += 40

    # 数字のボックス
    d.rounded_rectangle([pad, y, SIZE - pad, y + 210], radius=28, fill=SOFT)
    cols = [
        (f"★{item['review_avg']:.2f}", "レビュー平均"),
        (f"{item['review_count']:,}件", "レビュー数"),
        (f"{item['price']:,}円", f"{today.month}/{today.day}時点"),
    ]
    if topic["kind"] == "price_drop":
        cols[2] = (f"{item['price']:,}円", f"前回 {topic['old_price']:,}円")
    col_w = (SIZE - pad * 2) / 3
    for n, (value, label) in enumerate(cols):
        cx = pad + col_w * n + col_w / 2
        big, small = _fit(d, value, 60, col_w - 40), _fit(d, label, 32, col_w - 40)
        d.text((cx, y + 85), value, font=big, fill=ACCENT if n == 2 else TEXT, anchor="mm")
        d.text((cx, y + 160), label, font=small, fill=MUTED, anchor="mm")

    # 下の案内
    d.line([pad, SIZE - 190, SIZE - pad, SIZE - 190], fill=SOFT, width=3)
    d.text((SIZE / 2, SIZE - 130), "くわしい比較はプロフィールのリンクから", font=_font(40), fill=TEXT, anchor="mm")
    d.text((SIZE / 2, SIZE - 70), site_name, font=_font(34), fill=MUTED, anchor="mm")

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
