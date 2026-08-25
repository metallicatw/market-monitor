# -*- coding: utf-8 -*-
"""
財報公布窗口偵測器
================

日本沒有統一的財報發布日，只有交易所規則的「原則上各季結束後 45 日內」上限
（2024/4/1 起四半期報告書已廢止，第1・第3季一本化為四半期決算短信）。
所以無法寫死日期自動抓，只能推算窗口、提醒你去確認。

這支程式做的事：
1. 依每檔個股的結算月，推算目前是否落在財報公布窗口內
2. 比對資料庫裡已有的最新季度，判斷「這一季是否還沒更新」
3. 印出待辦清單與官方 IR 連結，讓你人工確認後登錄

為什麼不做全自動抓取寫入？
--------------------------
先前稽核抓到的川崎重工重大錯誤，根源正是自動抓第三方網站：
kabutan 對 IFRS 公司的「經常益」欄填的是稅前利益，不是本業的事業利益，
程式照抓就整條錯。而各家科目定義都不同（日立=調整後營業利益、
味之素=營業利益而非事業利益、瑞穗=經常利益），沒有一套通則可以安全套用。
所以這裡刻意只做「偵測與提醒」，資料正確性仍由人工把關。

用法：
    python check_earnings_due.py
"""
import json
import os
from datetime import date

from config_loader import load_jp_stocks

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 各檔結算月（一般日股為 3 月，例外在此標注）
FISCAL_YEAR_END_MONTH = {
    "kao": 12,      # 花王：12 月結算
    "yaskawa": 2,   # 安川電機：2 月結算
}
DEFAULT_FY_END_MONTH = 3

# 官方 IR 頁面，方便直接點過去查最新短信
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
}

# 各季結束後，實務上多半在這個天數區間內公布（法定上限 45 日）
WINDOW_START_DAYS = 25
WINDOW_END_DAYS = 50   # 稍微放寬到 50 天，涵蓋少數延後公布的情況


def _quarter_end_dates(fy_end_month, today):
    """回傳最近 5 個已結束的季別期末日，由新到舊。"""
    ends = []
    # 從結算月往回推，產生近兩年的季末
    year = today.year + 1
    while len(ends) < 12:
        for q in range(4):
            m = (fy_end_month - q * 3 - 1) % 12 + 1
            y = year if m <= fy_end_month else year - 1
            # 該月最後一天
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
    """找出今天之後最近的一個季末日（含今天）。"""
    import datetime as _dt
    # 季末月份為結算月 ± 3 的倍數
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
    # 只保留真正落在該公司季末月的日期
    valid_months = {(fy_end_month + k * 3 - 1) % 12 + 1 for k in range(4)}
    candidates = [d for d in candidates if d.month in valid_months]
    return min(candidates) if candidates else None


def _quarter_label(d, fy_end_month):
    """把期末日轉成 FYxxQn 標籤，與資料庫使用的標籤規則一致（以結束年度命名）。"""
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


def main():
    today = date.today()
    stocks = load_jp_stocks(include_disabled=True)

    print("=" * 72)
    print(f"財報公布窗口偵測　（今天：{today.isoformat()}）")
    print("=" * 72)
    print("規則：各季結束後原則 45 日內公布四半期決算短信（2024/4 起 Q1・Q3 已一本化為短信）")
    print()

    due, waiting = [], []

    for s in stocks:
        key, name = s["key"], s["name"]
        fy_end_month = FISCAL_YEAR_END_MONTH.get(key, DEFAULT_FY_END_MONTH)
        recorded_label, recorded_end = _latest_recorded_quarter(key)

        for qe in _quarter_end_dates(fy_end_month, today):
            days_since = (today - qe).days
            if days_since > WINDOW_END_DAYS:
                break  # 更早的季別就不用看了
            if days_since < WINDOW_START_DAYS:
                continue  # 還太早，公司通常還沒公布

            label = _quarter_label(qe, fy_end_month)
            # 資料庫已經有這一季就不用提醒
            if recorded_end and recorded_end >= qe.isoformat():
                continue

            item = (name, key, label, qe, days_since, recorded_label)
            if days_since <= WINDOW_END_DAYS:
                due.append(item)
            break  # 每檔只提醒最近一個待更新季別

        # 下一季窗口預告：找「今天之後最近的一個季末」，推算窗口何時開啟
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
    else:
        print("✅ 目前沒有任何個股處於「已公布但資料庫未更新」的狀態。\n")

    if waiting:
        print("-" * 72)
        print("📅 下一波公布窗口預告：")
        for name, label, qe, d in sorted(waiting, key=lambda x: x[3]):
            print(f"    {name:20s} {label}　季末 {qe.isoformat()}　約 {d} 天後進入公布窗口")

    print()
    print("💡 確認新財報後，請人工更新以下檔案（注意各家獲利科目定義不同，務必核對官方原始短信）：")
    print("     data/stock_<key>_quarterly_financials.json　（季度趨勢）")
    print("     data/stock_<key>_financials.json　　　　　　（最新季快照）")


if __name__ == "__main__":
    main()
