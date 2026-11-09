"""都道府県別の灯油価格（資源エネルギー庁「石油製品価格調査」）を取りこむ。

毎週月曜に調査、水曜に公表される「結果詳細版（Excel）」から、灯油の店頭・配達価格（18Lあたり）を読む。
取りこんだ値は data/kerosene.json に週ごとに残し、取得に失敗した日は記録の最新週を使う。
"""
import io
import json
import re
from datetime import datetime
from pathlib import Path

import requests

RESULTS_URL = "https://www.enecho.meti.go.jp/statistics/petroleum_and_lpgas/pl007/results.html"
BASE_URL = "https://www.enecho.meti.go.jp/statistics/petroleum_and_lpgas/pl007/"
# 短いUser-Agentだと弾かれるので、ふつうのブラウザと同じものを送る
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36", "Accept-Language": "ja"}
KEEP_WEEKS = 104

PREFS = ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
         "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
         "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県",
         "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
         "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県",
         "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"]
REGIONS = [("北海道・東北", 0, 7), ("関東", 7, 14), ("中部", 14, 23), ("近畿", 23, 30),
           ("中国・四国", 30, 39), ("九州・沖縄", 39, 47)]
FULL = {p if p == "北海道" else p[:-1]: p for p in PREFS}  # Excelでは「東京」「京都」のように書かれている


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"weeks": {}}


def save(path: Path, db):
    weeks = dict(sorted(db["weeks"].items())[-KEEP_WEEKS:])
    gas = dict(sorted(db.get("gas_weeks", {}).items())[-KEEP_WEEKS:])
    path.write_text(json.dumps({**db, "weeks": weeks, "gas_weeks": gas}, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")


def parse(data: bytes):
    """結果詳細版Excelの「都道府県別」シートから、前週と今週の2週分を返す。
    灯油は {調査日: {県名: [店頭, 配達]}}、ガソリンは {調査日: {県名: [レギュラー, ハイオク, 軽油]}}（1Lあたり）。"""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    ws = next(s for s in wb.worksheets if "都道府県" in s.title)
    dates, out, gas = None, {}, {}
    for row in ws.iter_rows(values_only=True):
        ds = [c for c in row if isinstance(c, datetime)]
        if len(ds) >= 10 and dates is None:
            # 列の並び：ハイオク・レギュラー・軽油・灯油店頭・灯油配達が、それぞれ前週・今週の順
            dates = [d.strftime("%Y-%m-%d") for d in ds[6:8]]
            out = {d: {} for d in dates}
            gas = {d: {} for d in dates}
            continue
        texts = [c for c in row if isinstance(c, str)]
        if not dates or not texts:
            continue
        name = re.sub(r"\s", "", texts[0])
        nums = [c for c in row if isinstance(c, (int, float))]
        if len(nums) < 10:
            continue
        if name == "全国":
            key = "全国"
        elif name in ("北海道局", "沖縄局"):
            key = FULL[name[:-1]]
        elif name.endswith("局"):
            continue  # 経済産業局ごとの平均は使わない
        else:
            key = FULL.get(name)
        if not key:
            continue
        for d, store, deliv in ((dates[0], nums[6], nums[8]), (dates[1], nums[7], nums[9])):
            out[d][key] = [round(store), round(deliv)]
        for d, i in ((dates[0], 0), (dates[1], 1)):
            gas[d][key] = [round(nums[2 + i], 1), round(nums[0 + i], 1), round(nums[4 + i], 1)]
    if not out or any(len(v) != len(PREFS) + 1 for v in out.values()):
        raise ValueError(f"都道府県の数が合いません: { {d: len(v) for d, v in out.items()} }")
    return out, gas


def update(db):
    """公表ページを見て、新しい週の結果が出ていれば取りこむ。失敗しても例外は外に出さない。"""
    try:
        html = requests.get(RESULTS_URL, headers=HEADERS, timeout=30).text
        # 「結果詳細版（EXCEL形式）」は xlsx/YYMMDD.xlsx（5週分などの別ファイルは末尾に文字がつく）
        m = re.search(r'href="[^"]*?(xlsx/(\d{6})\.xlsx)"', html)
        if not m:
            print("  ! 灯油価格: 結果詳細版のリンクが見つかりません")
            return False
        if db.get("file") == m.group(1) and db.get("gas_file") == m.group(1):
            return False
        r = requests.get(BASE_URL + m.group(1), headers=HEADERS, timeout=60)
        r.raise_for_status()
        kero, gas = parse(r.content)
        db["weeks"].update(kero)
        db.setdefault("gas_weeks", {}).update(gas)
        db["file"] = db["gas_file"] = m.group(1)
        print(f"  灯油価格: {m.group(1)} を取りこみました")
        return True
    except Exception as e:  # 灯油価格が取れなくても、サイトの更新は止めない
        print(f"  ! 灯油価格の取得に失敗: {type(e).__name__}: {e}")
        return False


def summary(db):
    """ページに出す形にまとめる。記録がなければ None。"""
    weeks = sorted(db.get("weeks", {}).items())
    if not weeks:
        return None
    day, cur = weeks[-1]
    prev = weeks[-2][1] if len(weeks) >= 2 else {}
    rows = []
    for p in PREFS:
        if p not in cur:
            continue
        store, deliv = cur[p]
        before = prev.get(p)
        rows.append({"pref": p, "store": store, "deliv": deliv, "liter": round(store / 18, 1),
                     "diff": store - before[0] if before else None})
    by_price = sorted(rows, key=lambda r: r["store"])
    for n, r in enumerate(by_price, 1):
        r["rank"] = n
    nat = cur.get("全国")
    nat_prev = prev.get("全国")
    d = datetime.strptime(day, "%Y-%m-%d")
    # 全国平均の動き（古い順）。記録がたまるほど長くなる
    trend = [{"day": k, "store": v["全国"][0]} for k, v in weeks if "全国" in v][-12:]
    return {
        "day": day, "day_jp": f"{d.year}年{d.month}月{d.day}日", "md": f"{d.month}/{d.day}",
        "rows": rows, "cheap": by_price[:5], "dear": by_price[::-1][:5],
        "regions": [(name, rows[a:b]) for name, a, b in REGIONS],
        "national": {"store": nat[0], "deliv": nat[1], "liter": round(nat[0] / 18, 1),
                     "diff": nat[0] - nat_prev[0] if nat_prev else None} if nat else None,
        "trend": trend,
        "trend_max": max(t["store"] for t in trend), "trend_min": min(t["store"] for t in trend),
    }


def fill(obj, k):
    """記事の中の {K_STORE} などの目印を、今週の灯油価格に置きかえる（毎週、自動で最新の数字になる）。"""
    nat = k["national"]
    diff = nat["deliv"] - nat["store"]
    d = datetime.strptime(k["day"], "%Y-%m-%d")
    tokens = {
        "{K_DAY}": f"{d.month}月{d.day}日",
        "{K_STORE}": f"{nat['store']:,}", "{K_DELIV}": f"{nat['deliv']:,}", "{K_DIFF}": f"{diff:,}",
        "{K_LITER}": f"{nat['liter']}", "{K_DLITER}": f"{round(nat['deliv'] / 18, 1)}",
        "{K_CHEAP_PREF}": k["cheap"][0]["pref"], "{K_CHEAP}": f"{k['cheap'][0]['store']:,}",
        "{K_DEAR_PREF}": k["dear"][0]["pref"], "{K_DEAR}": f"{k['dear'][0]['store']:,}",
        "{K_D75}": f"{round(diff * 7.5, -1):,.0f}", "{K_D10}": f"{diff * 10:,}", "{K_D15}": f"{diff * 15:,}",
    }
    text = json.dumps(obj, ensure_ascii=False)
    for key, value in tokens.items():
        text = text.replace(key, value)
    return json.loads(text)


def gas_summary(db):
    """ガソリン価格のページに出す形にまとめる。記録がなければ None。"""
    weeks = sorted(db.get("gas_weeks", {}).items())
    if not weeks:
        return None
    day, cur = weeks[-1]
    prev = weeks[-2][1] if len(weeks) >= 2 else {}
    rows = []
    for p in PREFS:
        if p not in cur:
            continue
        reg, hi, diesel = cur[p]
        before = prev.get(p)
        rows.append({"pref": p, "reg": reg, "hi": hi, "diesel": diesel,
                     "diff": round(reg - before[0], 1) if before else None})
    by_price = sorted(rows, key=lambda r: r["reg"])
    for n, r in enumerate(by_price, 1):
        r["rank"] = n
    nat = cur.get("全国")
    nat_prev = prev.get("全国")
    d = datetime.strptime(day, "%Y-%m-%d")
    trend = [{"day": k, "reg": v["全国"][0]} for k, v in weeks if "全国" in v][-12:]
    return {
        "day": day, "day_jp": f"{d.year}年{d.month}月{d.day}日", "md": f"{d.month}/{d.day}",
        "rows": rows, "cheap": by_price[:5], "dear": by_price[::-1][:5],
        "regions": [(name, rows[a:b]) for name, a, b in REGIONS],
        "national": {"reg": nat[0], "hi": nat[1], "diesel": nat[2],
                     "diff": round(nat[0] - nat_prev[0], 1) if nat_prev else None} if nat else None,
        "trend": trend,
        "trend_max": max(t["reg"] for t in trend), "trend_min": min(t["reg"] for t in trend),
    }
