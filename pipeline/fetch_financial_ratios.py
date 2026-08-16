# -*- coding: utf-8 -*-
"""
個股財務比率抓取模組（PER / EPS / PBR / 營業利益率）
改用 yfinance .info，取代原先規劃對 buffett-code.com 的爬蟲構想。

⚠️ 重要說明：buffett-code.com 使用條款明確禁止「自動化或機械化存取（含但不限於爬蟲程式）」，
   未經該公司事前同意不得進行。因此財務比率改抓 yfinance，這是：
   - 合法、穩定的公開資料源
   - 但僅提供「當前即時值」（trailing PER/EPS/PBR），非 buffett-code 式的逐季歷史時間序列
   若需要逐季歷史財務比率，需使用者自行從 buffett-code 網站人工查閱，
   或未來另尋合法的財務數據 API（如 Financial Modeling Prep、Alpha Vantage 等付費/限額方案）。
"""

import time

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("請先安裝 yfinance: pip install yfinance")


def fetch_financial_ratios(ticker_symbol, max_retries=3):
    """
    抓取單一標的目前財務比率快照。
    回傳: dict {"per": float|None, "eps": float|None, "pbr": float|None, "operating_margin": float|None}
    任何欄位若無法取得則為 None（前端須標示無資料，不可捏造）。
    """
    for attempt in range(max_retries):
        try:
            tk = yf.Ticker(ticker_symbol)
            info = tk.info

            per = info.get("trailingPE")
            eps = info.get("trailingEps")
            pbr = info.get("priceToBook")
            op_margin = info.get("operatingMargins")
            if op_margin is not None:
                op_margin = round(op_margin * 100, 2)  # 轉換為百分比

            return {
                "per": round(per, 2) if per is not None else None,
                "eps": round(eps, 2) if eps is not None else None,
                "pbr": round(pbr, 2) if pbr is not None else None,
                "operating_margin": op_margin,
            }
        except Exception as e:
            print(f"⚠️ {ticker_symbol} 財務比率抓取失敗 (嘗試 {attempt+1}/{max_retries}): {e}")
            time.sleep(3)

    print(f"❌ {ticker_symbol}: 財務比率抓取全部失敗，回傳無資料")
    return {"per": None, "eps": None, "pbr": None, "operating_margin": None}


if __name__ == "__main__":
    for t in ["2802.T", "8411.T", "6981.T"]:
        print(t, fetch_financial_ratios(t))
        time.sleep(1)
