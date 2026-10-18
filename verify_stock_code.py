# -*- coding: utf-8 -*-
import argparse
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from config_loader import load_jp_stocks

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{code}?range=5d&interval=1d"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketMonitorBot/1.0)"}


def normalize_code(raw):
    c = str(raw or "").strip().upper().replace(" ", "")
    if not c:
        return ""
    if re.fullmatch(r"\d{3}[0-9A-Z]", c):
        return c + ".T"
    return re.sub(r"\.(JP|JPN|TO|TYO|TSE)$", ".T", c)


def _ctx():
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


def lookup(code):
    url = CHART_API.format(code=urllib.parse.quote(code))
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20, context=_ctx()) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "Yahoo 查無此代號"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"連線失敗：{e}"

    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        return False, chart["error"].get("description", "Yahoo 回報錯誤")
    results = chart.get("result") or []
    if not results:
        return False, "Yahoo 沒有回傳資料"

    meta = results[0].get("meta") or {}
    long_name = meta.get("longName") or ""
    short_name = meta.get("shortName") or ""
    return True, {
        "symbol": meta.get("symbol", code),
        "name": long_name or short_name or "（Yahoo 未提供名稱）",
        "longName": long_name,
        "shortName": short_name,
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName", "?"),
        "currency": meta.get("currency", "?"),
        "price": meta.get("regularMarketPrice"),
    }


SEARCH_API = "https://query1.finance.yahoo.com/v1/finance/search?q={code}&quotesCount=6&newsCount=0"


def search_names(code):
    url = SEARCH_API.format(code=urllib.parse.quote(code))
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15, context=_ctx()) as r:
            payload = json.load(r)
    except Exception:
        return {}
    for q in (payload or {}).get("quotes") or []:
        if str(q.get("symbol", "")).upper() == code.upper():
            return {
                "longName": q.get("longname") or "",
                "shortName": q.get("shortname") or "",
            }
    return {}


def report(raw_code, expected_name=None):
    code = normalize_code(raw_code)
    if code != str(raw_code).strip():
        print(f"  代號已自動轉換：{raw_code} → {code}")

    ok, info = lookup(code)
    if not ok:
        print(f"  ❌ {code}：{info}")
        print(f"     請到 https://finance.yahoo.co.jp/quote/{code} 確認代號是否正確")
        return False

    price = info["price"]
    price_s = f"{price:,.0f} {info['currency']}" if isinstance(price, (int, float)) else "—"
    print(f"  ✅ {info['symbol']}　{info['name']}")
    print(f"     {info['exchange']}　最新價 {price_s}")
    if expected_name and expected_name not in info["name"] and info["name"] not in expected_name:
        print(f"     ⚠️ 設定檔寫的是「{expected_name}」，與 Yahoo 回報的名稱不同，請確認是不是抓錯公司")
    return True


def main():
    ap = argparse.ArgumentParser(description="查證股票代號對應的公司，避免把錯的代號寫進 config.json")
    ap.add_argument("codes", nargs="*", help="要查的代號，例如 4063 或 4063.T")
    ap.add_argument("--config", action="store_true", help="改為查 config.json 裡登記的所有個股")
    args = ap.parse_args()

    print("=" * 66)
    print("股票代號查證　（資料來源：Yahoo Finance）")
    print("=" * 66)

    if args.config:
        stocks = load_jp_stocks(include_disabled=True)
        if not stocks:
            print("config.json 裡沒有任何個股。")
            return
        bad = 0
        for s in stocks:
            state = "" if s["enabled"] else "（目前隱藏）"
            print(f"\n▸ {s['name']}{state}　key={s['key']}")
            if not report(s["code"], expected_name=s["name"]):
                bad += 1
        print("\n" + "-" * 66)
        print(f"共 {len(stocks)} 檔，{len(stocks)-bad} 檔正常" + (f"，{bad} 檔有問題" if bad else ""))
        return

    if not args.codes:
        ap.print_help()
        print("\n範例：python verify_stock_code.py 4063")
        return

    for c in args.codes:
        print(f"\n▸ 查詢 {c}")
        report(c)

    print("\n" + "-" * 66)
    print("確認無誤後，用控制台（python run.py）新增，或直接填進 config.json。")
    print("提醒：新個股只會有股價圖，季度財報要另外人工建立資料檔。")


if __name__ == "__main__":
    main()
