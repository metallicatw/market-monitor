# -*- coding: utf-8 -*-
"""
密西根大學消費者信心指數 (UMCSENT) 資料抓取模組
改用 FRED (Federal Reserve Economic Data) API，取代原先規劃的 investing.com 爬蟲，
因為 investing.com 頁面預設僅顯示約 10 筆月資料（需分頁載入），FRED 可一次性取得完整歷史。

FRED Series ID: UMCSENT (University of Michigan: Consumer Sentiment, monthly, NSA)
官方注意事項：FRED 資料依來源要求延遲 1 個月發布（即本月看到的是上個月數據）。

需要 FRED API Key（免費申請）: https://fred.stlouisfed.org/docs/api/api_key.html
建議存為 GitHub Actions Secret: FRED_API_KEY
"""

import os
import json
import urllib.request
import urllib.parse


FRED_SERIES_ID = "UMCSENT"
FRED_API_BASE = "https://api.stlouisfed.org/fred/series/observations"


def fetch_michigan_sentiment(api_key=None, start_date="2020-01-01"):
    """
    抓取密大消費者信心指數完整歷史（月資料）。
    回傳: list of dict [{"date": "YYYY-MM-DD", "value": float}, ...]
    缺失值 (FRED 以 "." 表示) 會被跳過，不補值。

    若 api_key 未提供，嘗試從環境變數 FRED_API_KEY 讀取。
    若仍無 API Key，回傳空 list 並印出警告（前端須標示為無資料）。
    """
    if api_key is None:
        api_key = os.environ.get("FRED_API_KEY")

    if not api_key:
        print("⚠️ 未設定 FRED_API_KEY，無法抓取密大消費者信心指數。")
        print("   請至 https://fred.stlouisfed.org/docs/api/api_key.html 申請免費 API Key，")
        print("   並在 GitHub repo Settings > Secrets and variables > Actions 新增 FRED_API_KEY。")
        return []

    params = {
        "series_id": FRED_SERIES_ID,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
    }
    url = f"{FRED_API_BASE}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"⚠️ FRED API 請求失敗: {e}")
        return []

    observations = data.get("observations", [])
    records = []
    for obs in observations:
        val_str = obs.get("value", ".")
        if val_str == "." or val_str is None:
            continue  # FRED 用 "." 標示缺失值，直接跳過，不補值
        try:
            records.append({"date": obs["date"], "value": float(val_str)})
        except (ValueError, KeyError):
            continue

    return records


def get_latest_reading(records):
    """取得最新一筆數值，若無資料則回傳 None"""
    if not records:
        return None
    return records[-1]["value"]


if __name__ == "__main__":
    # 本地測試用：export FRED_API_KEY=你的金鑰 後執行
    data = fetch_michigan_sentiment(start_date="2020-01-01")
    print(f"取得 {len(data)} 筆月資料")
    if data:
        print("最新:", data[-1])
        print("最舊:", data[0])
