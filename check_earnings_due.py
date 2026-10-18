# -*- coding: utf-8 -*-
import json
import os
from datetime import date

from config_loader import load_jp_stocks

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

FISCAL_YEAR_END_MONTH = {
    "kao": 12,
    "yaskawa": 2,
}
DEFAULT_FY_END_MONTH = 3

IR_URLS = {
    "kao": "https://www.kao.com/jp/corporate/investor-relations/library/results/",
    "towa": "https://www.towajapan.co.jp/ir/library/",
    "ajinomoto": "https://www.ajinomoto.co.jp/company/jp/ir/library/",
    "mizuho": "https://www.mizuhogroup.com/jp/ir/financial",
    "yaskawa": "https://www.yaskawa.co.jp/ir/library",
    "jxadvanced": "https://www.jx-nmm.com/ir/results.html",
    "mitsubishimaterials": "https://ir.mmc.co.jp/ja/ir/library/summary.html",
    "hitachi": "https://www.hitachi.co.jp/IR/library/fr/",
    "kawasakiheavy": "https://www.khi.co.jp/ir/library/financial_results/",
    "organo": "https://www.organo.co.jp/ir/result/",
    "shinetsu": "https://www.shinetsu.co.jp/jp/ir/library/",
    "fanuc": "https://www.fanuc.co.jp/ja/ir/library/index.html",
    "ibiden": "https://www.ibiden.co.jp/ir/library/",
    "advantest": "https://www.advantest.com/ja/investors/ir-library/",
    "marubeni": "https://www.marubeni.com/jp/ir/reports/",
    "tokyoelectron": "https://www.tel.co.jp/ir/library/",
}

WINDOW_START_DAYS = 25
WINDOW_END_DAYS = 50


def _quarter_end_dates(fy_end_month, today):
    ends = []
    year = today.year + 1
    while len(ends) < 12:
        for q in range(4):
            m = (fy_end_month - q * 3 - 1) % 12 + 1
            y = year if m <= fy_end_month else year - 1
            if m == 12:
                d = date(y, 12, 31)
            else:
                d = date(y, m + 1, 1) - __import__("datetime").timedelta(days=1)
            if d < today:
                ends.append(d)
        year -= 1
        if year < today.year - 3:
            break
    ends = sorted(set(ends), reverse=True)
    return ends[:5]


def _next_quarter_end(fy_end_month, today):
    import datetime as _dt
    candidates = []
    for offset in range(0, 15):
        m = (fy_end_month + offset * 3 - 1) % 12 + 1
        for y in (today.year, today.year + 1):
            if m == 12:
                d = _dt.date(y, 12, 31)
            else:
                d = _dt.date(y, m + 1, 1) - _dt.timedelta(days=1)
            if d >= today:
                candidates.append(d)
    valid_months = {(fy_end_month + k * 3 - 1) % 12 + 1 for k in range(4)}
    candidates = [d for d in candidates if d.month in valid_months]
    return min(candidates) if candidates else None


def _quarter_label(d, fy_end_month):
    months_after_fy_start = (d.month - fy_end_month - 1) % 12
    q = months_after_fy_start // 3 + 1
    fy = d.year + 1 if d.month > fy_end_month else d.year
    return f"FY{str(fy)[-2:]}Q{q}"


def _latest_recorded_quarter(key):
    path = os.path.join(DATA_DIR, f"stock_{key}_quarterly_financials.json")
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            q = json.load(f)
        fys = q.get("fiscal_years") or []
        ends = q.get("fiscal_year_end_dates") or []
        if not fys:
            return None, None
        return fys[-1], (ends[-1] if ends else None)
    except Exception:
        return None, None


def _murata_briefing_dates(year):
    import datetime as _dt
    out = []
    for m in (4, 7, 10):
        nxt = _dt.date(year, m + 1, 1)
        out.append(nxt - _dt.timedelta(days=1))
    out.append(_dt.date(year + 1, 2, 2))
    return sorted(out)


def check_murata(today, progress=print):
    path = os.path.join(DATA_DIR, "murata_bb.json")
    if not os.path.exists(path):
        progress("  ● 村田 B/B Ratio：找不到 data/murata_bb.json")
        return
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        progress(f"  ● 村田 B/B Ratio：檔案讀取失敗（{e}）")
        return

    quarters = d.get("quarters") or []
    last_q = quarters[-1] if quarters else "（無資料）"
    fetched = d.get("fetched_at") or ""

    candidates = sorted(_murata_briefing_dates(today.year - 1)
                        + _murata_briefing_dates(today.year))
    passed = [x for x in candidates if x <= today]
    nxt = [x for x in candidates if x > today]
    last_briefing = passed[-1] if passed else None
    next_briefing = nxt[0] if nxt else None

    progress(f"  ● 村田 B/B Ratio：目前資料截至 {last_q}（登錄日 {fetched or '未標註'}）")
    if last_briefing:
        stale = bool(fetched) and fetched < last_briefing.isoformat()
        if stale or not fetched:
            progress(f"      🔔 {last_briefing.isoformat()} 已有法說會，登錄日在那之前，可能還沒補上新數字")
        else:
            progress(f"      最近一場法說會 {last_briefing.isoformat()}，登錄日在那之後，看起來已更新")
    if next_briefing:
        progress(f"      下一場約在 {next_briefing.isoformat()}")


def main():
    today = date.today()
    stocks = load_jp_stocks(include_disabled=True)

    print("=" * 72)
    print(f"財報公布窗口偵測　（今天：{today.isoformat()}）")
    print("=" * 72)
    print("規則：各季結束後原則 45 日內公布四半期決算短信（2024/4 起 Q1・Q3 已一本化為短信）")
    print()

    due, overdue, waiting = [], [], []

    for s in stocks:
        key, name = s["key"], s["name"]
        fy_end_month = FISCAL_YEAR_END_MONTH.get(key, DEFAULT_FY_END_MONTH)
        recorded_label, recorded_end = _latest_recorded_quarter(key)

        for qe in _quarter_end_dates(fy_end_month, today):
            days_since = (today - qe).days
            if days_since < WINDOW_START_DAYS:
                continue

            label = _quarter_label(qe, fy_end_month)
            if recorded_end and recorded_end >= qe.isoformat():
                continue

            item = (name, key, label, qe, days_since, recorded_label)
            if days_since <= WINDOW_END_DAYS:
                due.append(item)
            else:
                overdue.append(item)
            break

        nxt = _next_quarter_end(fy_end_month, today)
        if nxt:
            days_to_window = (nxt - today).days + WINDOW_START_DAYS
            waiting.append((name, _quarter_label(nxt, fy_end_month), nxt, days_to_window))

    if due:
        print(f"🔔 有 {len(due)} 檔已進入公布窗口、但資料庫尚未更新：\n")
        for name, key, label, qe, days, recorded in due:
            status = "已逾 45 日上限，應該早就公布了" if days > 45 else f"距季末 {days} 天，多半已公布"
            print(f"  ● {name}（{label}，季末 {qe.isoformat()}）")
            print(f"      目前資料庫最新：{recorded or '無'}　｜　{status}")
            print(f"      官方 IR：{IR_URLS.get(key, '（未登錄連結）')}")
            print()
    if overdue:
        print(f"🚨 有 {len(overdue)} 檔**已經逾期**——窗口早就過了，資料庫還是舊的：\n")
        for name, key, label, qe, days, recorded in overdue:
            print(f"  ● {name}（{label}，季末 {qe.isoformat()}）")
            print(f"      目前資料庫最新：{recorded or '無'}　｜　"
                  f"距季末已 {days} 天（窗口上限 {WINDOW_END_DAYS} 天）")
            print(f"      官方 IR：{IR_URLS.get(key, '（未登錄連結）')}")
            print()
        if os.environ.get("GITHUB_ACTIONS"):
            names = "、".join(f"{n}({l})" for n, _k, l, _q, _d, _r in overdue)
            print(f"::warning title=有個股的財報逾期未更新::{names}")

    if not due and not overdue:
        print("✅ 目前沒有任何個股處於「已公布但資料庫未更新」的狀態。\n")

    if waiting:
        print("-" * 72)
        print("📅 下一波公布窗口預告：")
        for name, label, qe, d in sorted(waiting, key=lambda x: x[3]):
            print(f"    {name:20s} {label}　季末 {qe.isoformat()}　約 {d} 天後進入公布窗口")

    print()
    print("-" * 72)
    print("📊 季頻指標（只能人工登錄，沒有自動抓取的資料源）：")
    check_murata(today)

    print()
    print("💡 確認新財報後，請人工更新以下檔案（注意各家獲利科目定義不同，務必核對官方原始短信）：")
    print("     data/stock_<key>_quarterly_financials.json　（季度趨勢）")
    print("     data/stock_<key>_financials.json　　　　　　（最新季快照）")


if __name__ == "__main__":
    main()
