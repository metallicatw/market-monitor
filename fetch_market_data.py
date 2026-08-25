# -*- coding: utf-8 -*-
"""
fetch_market_data.py
真實歷史數據抓取腳本 —— 與 generate_report.py 分離。

這支腳本只做一件事：向官方/公開來源抓「真實」歷史數據，
存成 data/*.json 快取檔。絕不捏造、絕不補插值、絕不用亂數模擬。

目前完整實作：
1. fetch_taiex()  — 台股加權指數，來源 TWSE 官方 FMTQIK API
2. fetch_vix()    — VIX 恐慌指數，來源 CBOE 官方公開 CSV
3. fetch_nikkei() — 日經225，來源 Yahoo Finance Chart API

其餘資料源 (密大信心指數 / 村田B/B / 日股個股) 說明請見檔案底部，
架構已留擴充點，每個函式的產出格式都跟 fetch_taiex() 一致：
    {"dates": [...], "close": [...], ...}
generate_report.py 只讀這些 JSON，不會再自己編數字。
"""

import csv
import io
import json
import os
import ssl
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta, timezone

from config_loader import load_jp_stocks

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MarketMonitorBot/1.0)"
}

# --- SSL 相容性修正 -----------------------------------------------------
# Python 3.13 起，預設 SSL context 會啟用更嚴格的 X.509 檢查
# (要求憑證鏈上每張憑證都要有 Subject Key Identifier 欄位)。
# TWSE 官方網站的憑證鏈缺了這個欄位（瀏覽器/舊版 Python 都不會擋），
# 導致 Python 3.13 直接判定 CERTIFICATE_VERIFY_FAILED。
# 這裡只關掉這一條「額外嚴格」規則，其餘憑證驗證（防偽造網站、防竊聽）
# 完全維持正常，不是整個關掉 SSL 驗證。
def _build_ssl_context():
    ctx = ssl.create_default_context()
    try:
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    except AttributeError:
        pass  # Python < 3.13 沒有這個嚴格模式，本來就不會遇到此問題
    return ctx


SSL_CONTEXT = _build_ssl_context()


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
        return resp.read()


def _fetch_json_with_retry(url, max_retries=3, backoff_sec=3):
    """
    帶重試機制的 JSON 抓取。TWSE 官方 API 在短時間內被打太多次時，
    會回傳 307 重導向（不是真的沒資料，是流量被判定異常），
    所以遇到失敗時，先等一下再重試，而不是直接放棄該筆資料。
    """
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            raw = _http_get(url)
            return json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(backoff_sec * attempt)  # 越晚重試，等越久
    raise last_err


def _load_cache(filename):
    """讀取既有的 data/*.json 快取檔，沒有就回傳 None。"""
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _merge_series(existing, new_dates, new_fields):
    """
    把新抓到的資料合併進既有快取，依日期去重、排序。
    existing: 舊的 dict（含 "dates" 及其他平行陣列欄位），可以是 None（沒有快取）
    new_dates: 這次新抓到的 ISO 日期字串清單
    new_fields: {"close": [...], "volume": [...], ...} 跟 new_dates 等長的平行陣列

    同一天如果新舊都有資料，新抓到的會覆蓋舊的（官方資料偶爾會校正修正），
    不同天的資料則保留。回傳合併後、依日期排序好的 dict。
    """
    field_names = list(new_fields.keys())
    combined = {}

    if existing and existing.get("dates"):
        old_dates = existing["dates"]
        for name in field_names:
            old_vals = existing.get(name, [None] * len(old_dates))
            for i, d in enumerate(old_dates):
                combined.setdefault(d, {})[name] = old_vals[i] if i < len(old_vals) else None

    for i, d in enumerate(new_dates):
        for name in field_names:
            combined.setdefault(d, {})[name] = new_fields[name][i]

    sorted_dates = sorted(combined.keys())
    merged = {"dates": sorted_dates}
    for name in field_names:
        merged[name] = [combined[d].get(name) for d in sorted_dates]
    return merged


def _yahoo_range_for_incremental(existing, years_back=5, buffer_days=3):
    """
    根據既有快取的最後日期，決定這次 Yahoo API 該用多短的 range 參數。
    buffer_days 是小幅重疊緩衝（預設3天），只是為了涵蓋假日/資料校正的
    邊界情況，不能設太大，否則「每天執行一次」這種最常見情境反而永遠
    命中不到最小的 5d 級距，白白多抓資料。
    沒有快取（第一次跑）就回傳完整 years_back 年份。
    """
    if not existing or not existing.get("dates"):
        return f"{years_back}y", None
    try:
        last_date = date.fromisoformat(existing["dates"][-1])
    except ValueError:
        return f"{years_back}y", None

    days_gap = (date.today() - last_date).days + buffer_days
    if days_gap <= 7:
        return "5d", last_date
    elif days_gap <= 30:
        return "1mo", last_date
    elif days_gap <= 95:
        return "3mo", last_date
    elif days_gap <= 370:
        return "1y", last_date
    else:
        return f"{years_back}y", last_date  # 缺口太大，乾脆整段重抓保險


def _month_range(years_back=5):
    """回傳從 years_back 年前到今天，逐月的 (yyyymmdd) 起始日清單。"""
    today = date.today()
    start = date(today.year - years_back, today.month, 1)
    months = []
    cur = date(start.year, start.month, 1)
    while cur <= today:
        months.append(cur.strftime("%Y%m01"))
        # 下一個月
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return months


def fetch_taiex(years_back=5, sleep_sec=1.5, incremental=True):
    """
    抓台股加權指數 (TAIEX) 真實每日資料。
    來源: TWSE 官方 FMTQIK API (每日市場成交資訊，含大盤指數/成交金額/成交量)
    文件對應網頁: https://www.twse.com.tw/zh/trading/historical/fmtqik.html

    增量模式 (incremental=True，預設)：如果 data/taiex.json 已經存在，
    只重抓「最後一筆資料所在月份」到「現在」這幾個月，其餘舊資料
    直接沿用快取，不重新打 API。這樣日常執行通常只需要打 1-2 次
    TWSE API，而不是每次都掃過 5 年 60 個月，速度快很多，也比較
    不會被 TWSE 判定異常流量。

    回傳格式 (100% 真實逐日資料，缺交易日就是沒有該筆，不補值):
    {
      "dates": ["2021-08-02", "2021-08-03", ...],   # ISO 日期，只含真實有開盤的交易日
      "close": [17381.62, 17301.55, ...],            # 加權指數收盤
      "volume_shares": [...],                          # 成交股數
      "value_twd": [...]                                # 成交金額 (元)
    }
    """
    existing = _load_cache("taiex.json") if incremental else None

    if existing and existing.get("dates"):
        last_date = datetime.strptime(existing["dates"][-1], "%Y-%m-%d").date()
        start_month = date(last_date.year, last_date.month, 1)  # 從最後資料當月開始重抓，該月可能還沒收完
        print(f"📂 偵測到既有快取，最後資料到 {existing['dates'][-1]}，"
              f"本次只重抓 {start_month.strftime('%Y-%m')} 之後的月份（增量模式）")
    else:
        start_month = date.today().replace(year=date.today().year - years_back, day=1)
        print("📂 沒有偵測到既有快取，執行完整 5 年回補（第一次執行才會這麼慢）")

    months = []
    cur = start_month
    today = date.today()
    while cur <= today:
        months.append(cur.strftime("%Y%m01"))
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)

    out_dates, out_close, out_vol, out_val = [], [], [], []
    failed_months = []

    for ym in months:
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json&date={ym}"
        try:
            payload = _fetch_json_with_retry(url, max_retries=3, backoff_sec=3)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            print(f"⚠️ {ym} 重試 3 次仍失敗，略過（不補假資料）: {e}")
            failed_months.append(ym)
            time.sleep(sleep_sec)
            continue

        rows = payload.get("data", [])
        # FMTQIK 欄位: 日期, 成交股數, 成交金額, 成交筆數, 發行量加權股價指數, 漲跌點數
        for row in rows:
            try:
                roc_date = row[0].strip()  # 民國年，例如 "115/08/14"
                y, m, d = roc_date.split("/")
                iso_date = f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"
                vol_shares = float(row[1].replace(",", ""))
                value_twd = float(row[2].replace(",", ""))
                closing_index = float(row[4].replace(",", ""))
            except (ValueError, IndexError):
                continue  # 該筆格式異常就跳過，不用假數字填補

            out_dates.append(iso_date)
            out_close.append(closing_index)
            out_vol.append(vol_shares)
            out_val.append(value_twd)

        time.sleep(sleep_sec)  # 對官方 API 客氣一點，避免被判定異常流量

    # 收尾重試：如果有月份失敗，通常是一整批被限流，等久一點後單獨再試一次
    if failed_months:
        print(f"⏳ 有 {len(failed_months)} 個月份失敗，休息 15 秒後再單獨重試一次...")
        time.sleep(15)
        still_failed = []
        for ym in failed_months:
            url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json&date={ym}"
            try:
                payload = _fetch_json_with_retry(url, max_retries=3, backoff_sec=4)
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
                still_failed.append(ym)
                time.sleep(sleep_sec)
                continue
            rows = payload.get("data", [])
            for row in rows:
                try:
                    roc_date = row[0].strip()
                    y, m, d = roc_date.split("/")
                    iso_date = f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"
                    vol_shares = float(row[1].replace(",", ""))
                    value_twd = float(row[2].replace(",", ""))
                    closing_index = float(row[4].replace(",", ""))
                except (ValueError, IndexError):
                    continue
                out_dates.append(iso_date)
                out_close.append(closing_index)
                out_vol.append(vol_shares)
                out_val.append(value_twd)
            time.sleep(sleep_sec)
        failed_months = still_failed

    # 跟既有快取合併（增量模式下，這步會把新抓的這幾個月接到舊資料後面）
    merged = _merge_series(existing, out_dates, {
        "close": out_close, "volume_shares": out_vol, "value_twd": out_val,
    })

    result = {
        "source": "TWSE FMTQIK (https://www.twse.com.tw/zh/trading/historical/fmtqik.html)",
        "fetched_at": date.today().isoformat(),
        "failed_months": failed_months,
        "dates": merged["dates"],
        "close": merged["close"],
        "volume_shares": merged["volume_shares"],
        "value_twd": merged["value_twd"],
    }

    out_path = os.path.join(DATA_DIR, "taiex.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    print(f"✅ TAIEX 資料更新完成：本次新抓 {len(out_dates)} 筆，快取總計 {len(merged['dates'])} 個真實交易日，寫入 {out_path}")
    if failed_months:
        print(f"⚠️ 有 {len(failed_months)} 個月份抓取失敗（清單: {failed_months}），"
              f"這些月份的資料就是缺，不會用假數字填補。可稍後重跑補齊。")
    return result


def fetch_vix(incremental=True):
    """
    抓 VIX 恐慌指數真實每日資料。
    來源: CBOE 官方公開 CSV (1990 年至今，每日更新，免金鑰)
    https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv

    只保留最近 5 年，跟其他圖表週期一致。CSV 欄位為 DATE, OPEN, HIGH, LOW, CLOSE。
    這個來源官方只給「整份 CSV」下載，沒辦法只要求某個日期區間，所以每次還是
    得抓整份檔案 —— 但抓回來之後會跟既有快取合併去重，不會重複儲存，
    也方便你看出這次到底新增了幾筆真實資料。
    """
    existing = _load_cache("vix.json") if incremental else None

    url = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    raw_bytes = None
    last_err = None
    for attempt in range(1, 4):
        try:
            raw_bytes = _http_get(url)
            break
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < 3:
                time.sleep(3 * attempt)
    if raw_bytes is None:
        print(f"⚠️ VIX 重試 3 次仍失敗，未寫入任何檔案（不補假資料）: {last_err}")
        return None
    raw = raw_bytes.decode("utf-8-sig")

    cutoff = date.today().replace(year=date.today().year - 5)
    out_dates, out_close = [], []
    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        raw_date = (row.get("DATE") or "").strip()
        raw_close = (row.get("CLOSE") or "").strip()
        if not raw_date or not raw_close:
            continue
        parsed = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw_date, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None or parsed < cutoff:
            continue
        try:
            close_val = float(raw_close)
        except ValueError:
            continue
        out_dates.append(parsed.isoformat())
        out_close.append(close_val)

    merged = _merge_series(existing, out_dates, {"close": out_close})
    new_count = len(merged["dates"]) - len(existing["dates"]) if existing and existing.get("dates") else len(merged["dates"])

    result = {
        "source": "CBOE 官方 VIX 歷史資料 (https://www.cboe.com/tradable_products/vix/vix_historical_data/)",
        "fetched_at": date.today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
    }
    out_path = os.path.join(DATA_DIR, "vix.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"✅ VIX 資料更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實交易日，寫入 {out_path}")
    return result


def fetch_nikkei(years_back=5, incremental=True):
    """
    抓日經225指數真實每日資料。
    來源: Yahoo Finance Chart API (^N225)，公開端點、免金鑰。

    增量模式：如果已經有快取，只跟 Yahoo 要「最近幾天/幾個月」的資料
    （用 range 參數動態縮小），而不是每次都要 5 年份，回應資料量小很多。
    """
    existing = _load_cache("nikkei.json") if incremental else None
    range_param, last_cached = _yahoo_range_for_incremental(existing, years_back)
    if last_cached:
        print(f"📂 日經225 既有快取到 {last_cached.isoformat()}，本次只跟 Yahoo 要 range={range_param}（增量模式）")

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/%5EN225?range={range_param}&interval=1d"
    try:
        payload = _fetch_json_with_retry(url, max_retries=3, backoff_sec=3)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"⚠️ 日經225 重試 3 次仍失敗，未寫入任何檔案（不補假資料）: {e}")
        return None

    try:
        result_block = payload["chart"]["result"][0]
        timestamps = result_block["timestamp"]
        closes = result_block["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as e:
        print(f"⚠️ 日經225 回傳格式異常，未寫入任何檔案: {e}")
        return None

    out_dates, out_close = [], []
    for ts, c in zip(timestamps, closes):
        if c is None:
            continue  # 該筆缺值就跳過，不補
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        out_dates.append(d.isoformat())
        out_close.append(round(float(c), 2))

    merged = _merge_series(existing, out_dates, {"close": out_close})
    new_count = len(merged["dates"]) - len(existing["dates"]) if existing and existing.get("dates") else len(merged["dates"])

    result = {
        "source": "Yahoo Finance Chart API (^N225)",
        "fetched_at": date.today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
    }
    out_path = os.path.join(DATA_DIR, "nikkei.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"✅ 日經225 資料更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實交易日，寫入 {out_path}")
    return result


def fetch_michigan_sentiment(incremental=True):
    """
    抓密西根大學消費者信心指數真實月度資料。
    來源: FRED (聖路易聯邦準備銀行) 官方 CSV，免金鑰、免登入。
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=UMCSENT
    注意：官方本身就規定資料會延遲一個月公布，這是資料源的正常特性，
    不是我們抓取的問題。這個來源同樣只能整份下載，抓回來後跟既有
    快取合併去重。
    """
    existing = _load_cache("michigan.json") if incremental else None

    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UMCSENT"
    try:
        raw = _http_get(url).decode("utf-8-sig")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"⚠️ 密大信心指數 抓取失敗，未寫入任何檔案（不補假資料）: {e}")
        return None

    cutoff = date.today().replace(year=date.today().year - 5)
    out_dates, out_close = [], []
    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        raw_date = (row.get("observation_date") or "").strip()
        raw_val = (row.get("UMCSENT") or "").strip()
        if not raw_date or not raw_val or raw_val == ".":
            continue
        try:
            parsed = datetime.strptime(raw_date, "%Y-%m-%d").date()
            val = float(raw_val)
        except ValueError:
            continue
        if parsed < cutoff:
            continue
        out_dates.append(parsed.isoformat())
        out_close.append(val)

    merged = _merge_series(existing, out_dates, {"close": out_close})
    new_count = len(merged["dates"]) - len(existing["dates"]) if existing and existing.get("dates") else len(merged["dates"])

    result = {
        "source": "FRED / University of Michigan Surveys of Consumers (UMCSENT)",
        "fetched_at": date.today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
    }
    out_path = os.path.join(DATA_DIR, "michigan.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"✅ 密大信心指數 資料更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實月份，寫入 {out_path}")
    return result


def fetch_jp_stock(code, key, name="", years_back=5, incremental=True):
    """
    抓日股個股真實股價資料（跟 fetch_nikkei 同樣邏輯，換成個股代碼）。
    來源: Yahoo Finance Chart API，免金鑰公開端點。
    code 例如 "2802.T"（味之素）、"6981.T"（村田製作所）。
    key 是存檔用的檔名代號，例如 "ajinomoto" -> data/stock_ajinomoto.json

    增量模式：同 fetch_nikkei，已有快取時只跟 Yahoo 要近期資料。
    """
    existing = _load_cache(f"stock_{key}.json") if incremental else None
    range_param, last_cached = _yahoo_range_for_incremental(existing, years_back)
    if last_cached:
        print(f"📂 {name or code} 既有快取到 {last_cached.isoformat()}，本次只跟 Yahoo 要 range={range_param}（增量模式）")

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}?range={range_param}&interval=1d"
    try:
        payload = _fetch_json_with_retry(url, max_retries=3, backoff_sec=3)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"⚠️ {name or code} 重試 3 次仍失敗，未寫入任何檔案（不補假資料）: {e}")
        return None

    try:
        result_block = payload["chart"]["result"][0]
        timestamps = result_block["timestamp"]
        quote = result_block["indicators"]["quote"][0]
        closes = quote["close"]
        volumes = quote.get("volume", [None] * len(closes))
    except (KeyError, IndexError, TypeError) as e:
        print(f"⚠️ {name or code} 回傳格式異常，未寫入任何檔案: {e}")
        return None

    out_dates, out_close, out_volume = [], [], []
    for ts, c, v in zip(timestamps, closes, volumes):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        out_dates.append(d.isoformat())
        out_close.append(round(float(c), 2))
        out_volume.append(int(v) if v is not None else None)

    merged = _merge_series(existing, out_dates, {"close": out_close, "volume": out_volume})
    new_count = len(merged["dates"]) - len(existing["dates"]) if existing and existing.get("dates") else len(merged["dates"])

    result = {
        "source": f"Yahoo Finance Chart API ({code})",
        "code": code,
        "name": name or code,
        "fetched_at": date.today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
        "volume": merged["volume"],
    }
    out_path = os.path.join(DATA_DIR, f"stock_{key}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"✅ {name or code} 資料更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實交易日，寫入 {out_path}")
    return result


# ---------------------------------------------------------------------------
# 待補的其他資料源 — 架構已留擴充點，之後逐一實作，格式比照 fetch_taiex()
# ---------------------------------------------------------------------------
#
# fetch_murata_bb_ratio():
#   村田 B/B Ratio 官方只在法說會 PDF/PPT 裡揭露，沒有結構化資料源，
#   必須人工從 IR 資料下載 PDF 後手動填入 data/murata_bb.json，
#   建議每季法說會後更新一次，而不是每天嘗試自動抓 PDF。
#
# 日股個股財務指標 (PER/EPS/PBR/營益率)：
#   股價本身用 fetch_jp_stock() 可以每天自動抓，但 PER/EPS/PBR/營益率
#   沒有免費結構化 API，做法比照村田 B/B Ratio：從公司官方 IR 頁面/
#   財報人工讀取登錄，存進 data/stock_<key>_financials.json，
#   每季財報公布後更新一次。


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="抓取市場資料。個股清單讀自 config.json，改設定檔即可增刪個股，不用動這支程式。"
    )
    parser.add_argument("--include-hidden", action="store_true",
                        help="連 config.json 中 enabled=false 的隱藏個股也一併更新股價快取")
    args = parser.parse_args()

    fetch_taiex(years_back=5)
    fetch_vix()
    fetch_nikkei(years_back=5)
    fetch_michigan_sentiment()

    stocks = load_jp_stocks(include_disabled=args.include_hidden)
    if not stocks:
        print("⚠️ config.json 裡沒有任何啟用中的個股，本次不抓個股股價。")
    else:
        hidden_note = "（含隱藏個股）" if args.include_hidden else ""
        print(f"\n📋 依 config.json 設定，本次更新 {len(stocks)} 檔個股股價{hidden_note}")
        for s in stocks:
            fetch_jp_stock(s["code"], s["key"], name=s["name"])

    print("\n💡 提醒：本程式只更新『價格類』資料（指數、股價、成交量）。")
    print("   季度財報（營收/獲利/EPS/BVPS）與村田 B/B Ratio 不會自動更新，需人工登錄後才會變動。")
    print("   可執行 `python check_earnings_due.py` 查看目前有哪些個股進入財報公布窗口。")
