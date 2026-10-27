"""商品ごとの値段を毎日記録して、「この〇日で一番安い」などを出す。

楽天の値段は日々変わるので、記録がたまるほど「今は安いのか」が分かるようになる。
記録は data/prices.json に、商品コードごとに {日付: 値段} で残す。
"""
import json
from datetime import date, timedelta
from pathlib import Path

KEEP_DAYS = 180  # これより古い記録は消す
MIN_DAYS = 3     # この日数分たまるまでは表示しない


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def record(db, items, today):
    for i in items:
        db.setdefault(i["code"], {})[today] = i["price"]


def prune(db, today):
    cutoff = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS)).isoformat()
    for code in list(db):
        db[code] = {d: p for d, p in db[code].items() if d >= cutoff}
        if not db[code]:
            del db[code]


def save(path: Path, db):
    path.write_text(json.dumps(db, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")


def summary(db, item):
    """商品ページに出す値段の動き。記録が少ないうちは None。"""
    hist = db.get(item["code"], {})
    if len(hist) < MIN_DAYS:
        return None
    low_day = min(sorted(hist), key=lambda d: hist[d])
    low, avg, price = hist[low_day], sum(hist.values()) / len(hist), item["price"]
    if price <= low:
        status = "記録した中でいちばん安い値段です"
    elif price >= avg * 1.05:
        status = "記録した平均より高めです"
    elif price <= avg * 0.95:
        status = "記録した平均より安めです"
    else:
        status = "いつもと同じくらいの値段です"
    first = min(hist)
    return {"days": len(hist), "since": f"{int(first[5:7])}/{int(first[8:])}", "low": low,
            "low_day": f"{int(low_day[5:7])}/{int(low_day[8:])}", "status": status}
