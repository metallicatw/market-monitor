# -*- coding: utf-8 -*-
"""
即時市場歷史數據抓取模組
使用 yfinance 抓取真實每日歷史數據（5年），不進行任何平滑化或補值。
所有數據以 (date_str, value) 對呈現，缺失交易日則該日期不存在（不補點、不插值）。

⚠️ 重要：此模組需要網路存取 query1/query2.finance.yahoo.com
   GitHub Actions ubuntu-latest runner 預設可存取，但首次啟用後請務必手動觸發一次
   workflow_dispatch 確認抓取成功，避免排程執行時才發現問題。
"""

import datetime
import time

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("請先安裝 yfinance: pip install yfinance")


# ---- 標的代碼對照表 ----
TICKERS = {
    "taiex": "^TWII",          # 台股加權指數
    "vix": "^VIX",             # CBOE VIX
    "nikkei": "^N225",         # 日經 225
    "murata_price": "6981.T",  # 村田製作所股價（僅供參考，B/B Ratio 另有專用模組）
    "2802": "2802.T",          # 味の素 Ajinomoto
    "8411": "8411.T",          # みずほ Mizuho
    "6506": "6506.T",          # 安川電機 Yaskawa
    "5016": "5016.T",          # JX金属 JX Advanced Metals
    "5711": "5711.T",          # 三菱マテリアル Mitsubishi Materials
    "6501": "6501.T",          # 日立製作所 Hitachi
    "7012": "7012.T",          # 川崎重工業 Kawasaki Heavy Industries
}


def fetch_daily_history(ticker_symbol, period="5y", max_retries=3):
    """
    抓取單一標的的每日歷史數據（收盤價 + 成交量）。
    回傳: list of dict [{"date": "YYYY-MM-DD", "close": float, "volume": int}, ...]
    若抓取失敗，回傳空 list 並印出警告（呼叫端須自行標示「無資料」，不可補值）。
    """
    for attempt in range(max_retries):
        try:
            tk = yf.Ticker(ticker_symbol)
            hist = tk.history(period=period, interval="1d", auto_adjust=False)
            if hist.empty:
                print(f"⚠️ {ticker_symbol}: yfinance 回傳空資料 (嘗試 {attempt+1}/{max_retries})")
                time.sleep(2)
                continue

            records = []
            for idx, row in hist.iterrows():
                # 只保留真實存在的交易日資料，不補休市日、不插值
                if row["Close"] is None or (row["Close"] != row["Close"]):  # NaN check
                    continue
                records.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else None,
                })
            return records

        except Exception as e:
            print(f"⚠️ {ticker_symbol} 抓取失敗 (嘗試 {attempt+1}/{max_retries}): {e}")
            time.sleep(3)

    print(f"❌ {ticker_symbol}: 所有嘗試均失敗，回傳空資料（前端須標示為無資料，不可補值）")
    return []


def fetch_all(period="5y"):
    """
    抓取 TICKERS 中所有標的的歷史數據。
    回傳: {key: [records...]}
    """
    result = {}
    for key, symbol in TICKERS.items():
        print(f"抓取中: {key} ({symbol}) ...")
        result[key] = fetch_daily_history(symbol, period=period)
        print(f"  -> 取得 {len(result[key])} 筆真實交易日資料")
        time.sleep(1)  # 避免對 Yahoo Finance 造成過度請求
    return result


def get_latest_close(records):
    """取得最新一筆收盤價，若無資料則回傳 None（呼叫端須標示無資料）"""
    if not records:
        return None
    return records[-1]["close"]


def get_10day_avg_volume(records):
    """計算最近 10 個交易日平均成交量（億元換算需搭配收盤價，此處回傳原始成交量平均）"""
    if len(records) < 10:
        return None
    recent = records[-10:]
    vols = [r["volume"] for r in recent if r["volume"] is not None]
    if not vols:
        return None
    return sum(vols) / len(vols)


if __name__ == "__main__":
    # 本地測試用（需要網路存取 Yahoo Finance）
    data = fetch_all(period="5y")
    for key, records in data.items():
        print(f"{key}: {len(records)} 筆, 最新收盤 = {get_latest_close(records)}")
