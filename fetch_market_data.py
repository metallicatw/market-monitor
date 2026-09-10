# -*- coding: utf-8 -*-
"""
fetch_market_data.py
真實歷史數據抓取腳本 —— 與 generate_report_local.py 分離。

這支腳本只做一件事：向官方/公開來源抓「真實」歷史數據，
存成 data/*.json 快取檔。絕不捏造、絕不補插值、絕不用亂數模擬。

目前完整實作：
1. fetch_taiex()  — 台股加權指數，來源 TWSE 官方 FMTQIK API
2. fetch_vix()    — VIX 恐慌指數，來源 CBOE 官方公開 CSV
3. fetch_nikkei() — 日經225，來源 Yahoo Finance Chart API

其餘資料源 (密大信心指數 / 村田B/B / 日股個股) 說明請見檔案底部，
架構已留擴充點，每個函式的產出格式都跟 fetch_taiex() 一致：
    {"dates": [...], "close": [...], ...}
generate_report_local.py 只讀這些 JSON，不會再自己編數字。
"""

import csv
import io
import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta, timezone

from config_loader import load_jp_stocks, load_fred_series, load_us_indices

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 「有既有快取可用，所以沒有寫壞任何東西，但這次確實沒抓到新資料」的來源。
# 這種情況最危險的不是當下，而是它會安靜地持續好幾週 —— 報告上的數字看起來
# 正常，只是永遠停在同一個月。所以照樣要在最後彙總時出聲。
SOFT_FAILURES = []

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


def _http_post(url, data, timeout=30):
    """表單 POST。獨立成一支是為了讓離線測試可以像 `_http_get` 一樣換掉它——
    直接呼叫 `urllib.request.urlopen` 的話，那一段就永遠測不到。"""
    req = urllib.request.Request(
        url, data=data,
        headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
    )
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


def _write_json(path, obj):
    """原子寫入：先寫同目錄的暫存檔，fsync，再 os.replace 換過去。

    為什麼不能直接 `open(path, "w")`：那一行一開啟就先把原檔清成 0 位元組，
    然後才一段一段寫。runner 在中間被砍（timeout、取消、OOM）——而排程的提交
    步驟是 `if: always()` ＋ `git add -A`——截斷的 JSON 就這樣被 commit 進 main。

    `os.replace` 在同一個檔案系統上是原子的：任何一個時間點去讀，讀到的不是
    完整的舊版就是完整的新版，沒有中間狀態。
    """
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # BaseException 而不是 Exception：KeyboardInterrupt 與 SystemExit
        # 正是「runner 被砍」的樣子，暫存檔一樣要清掉。
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class CacheUnreadable(Exception):
    """快取檔在那裡，但讀不出來。跟「檔案不存在」是完全不同的一件事。"""


def _load_cache(filename):
    """讀取既有的 data/*.json 快取檔。

    **「檔案不存在」與「檔案壞掉」必須走不同的路。** 原本兩種都回 None，
    而合併寫入的那幾支（市值、M1B、PMI、TAIEX）拿 None 當作「還沒有歷史」，
    於是「合併後有沒有變少」那個守門員拿 old_len=0 去比——一定過。結果一個
    壞掉的位元組，就讓整份 tw_market_cap.json 被來源那個 5 個月的滾動視窗
    重建，而那份歷史**只能靠本地逐月累積**，洗掉就是永久損失。

    所以壞掉要 raise。呼叫端（`_run`）會記成一次失敗、保留檔案不動，人看得到，
    也還救得回來——git 裡就有上一版。
    """
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise CacheUnreadable(
            f"{filename} 讀不出來（{exc}）。這不是「沒有快取」，是既有的歷史檔壞了；"
            f"不覆蓋它。請從 git 取回上一版：git checkout HEAD -- data/{filename}"
        ) from exc
    if not isinstance(data, dict):
        raise CacheUnreadable(
            f"{filename} 的最外層不是物件（拿到 {type(data).__name__}），不覆蓋它。"
        )
    return data


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
    _write_json(out_path, result)

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
    _write_json(out_path, result)
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
    _write_json(out_path, result)
    print(f"✅ 日經225 資料更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實交易日，寫入 {out_path}")
    return result


def fetch_michigan_sentiment(incremental=True):
    """
    抓密西根大學消費者信心指數真實月度資料。

    ⚠️ 已被 fetch_fred_series("UMCSENT", cache_name="michigan.json") 取代，
       __main__ 不再單獨呼叫它（config.json 的 us_fred_series 裡有 UMCSENT，
       而且指定寫回同一個 michigan.json，所以報告端不用改）。
       這支保留是為了向後相容既有的呼叫端。
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
    _write_json(out_path, result)
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
    _write_json(out_path, result)
    print(f"✅ {name or code} 資料更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實交易日，寫入 {out_path}")
    return result


# ---------------------------------------------------------------------------
# 共用：位元組層級的重試抓取
# ---------------------------------------------------------------------------
def _http_get_with_retry(url, max_retries=3, backoff_sec=3, timeout=30, label=""):
    """
    回傳 raw bytes 的重試版本。

    為什麼需要它：央行 (cbc.gov.tw) 幾乎每次第一發連線都會被對方直接 reset
    （`Recv failure: Connection reset by peer`），第二發就成功。沒有重試的話
    這個資料源會以「看起來像網路壞掉」的樣子隨機消失，而且每天都不一樣。
    """
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return _http_get(url, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(backoff_sec * attempt)
    raise last_err


# ---------------------------------------------------------------------------
# 美股：FRED 月/週/季頻經濟指標
# ---------------------------------------------------------------------------
def _parse_fred_csv(raw_text, series_id, cutoff):
    """
    解析 FRED 的 fredgraph.csv 回應。

    格式固定是兩欄：`observation_date,<SERIES_ID>`，缺值以 "." 表示。
    這裡不對缺值做任何補值 —— 沒有就是沒有。
    """
    out_dates, out_values = [], []
    reader = csv.DictReader(io.StringIO(raw_text))
    if not reader.fieldnames or len(reader.fieldnames) < 2:
        return out_dates, out_values
    date_col = reader.fieldnames[0]
    value_col = series_id if series_id in reader.fieldnames else reader.fieldnames[1]
    for row in reader:
        raw_date = (row.get(date_col) or "").strip()
        raw_val = (row.get(value_col) or "").strip()
        if not raw_date or not raw_val or raw_val == ".":
            continue
        try:
            parsed = datetime.strptime(raw_date, "%Y-%m-%d").date()
            val = float(raw_val)
        except ValueError:
            continue
        if cutoff and parsed < cutoff:
            continue
        out_dates.append(parsed.isoformat())
        out_values.append(val)
    return out_dates, out_values


def fetch_fred_series(series_id, name="", years_back=5, incremental=True, cache_name=None):
    """
    抓任一個 FRED 序列的真實歷史資料。
    來源: FRED (聖路易聯邦準備銀行) 官方 CSV，免金鑰、免登入。
        https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>

    這是 fetch_michigan_sentiment() 用了很久的那個端點的通用版本 ——
    同一個模式換 series id 就好，不需要 API key。

    存成 data/fred_<series_id>.json（可用 cache_name 覆寫檔名），
    格式跟其他抓取函式一致：{"dates": [...], "close": [...]}。
    月頻序列的 observation_date 一律是該月 1 號，這是 FRED 的慣例，
    不是我們自己指定的日期。
    """
    label = name or series_id
    cache_file = cache_name or f"fred_{series_id.lower()}.json"
    existing = _load_cache(cache_file) if incremental else None

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        raw = _http_get_with_retry(url, label=label).decode("utf-8-sig")
    except Exception as e:
        print(f"⚠️ {label} ({series_id}) 重試 3 次仍失敗，未寫入任何檔案（不補假資料）: {e}")
        return None

    cutoff = date.today().replace(year=date.today().year - years_back)
    out_dates, out_values = _parse_fred_csv(raw, series_id, cutoff)
    if not out_dates:
        print(f"⚠️ {label} ({series_id}) 回應解析不到任何資料列，未寫入任何檔案。"
              f"（回應前 120 字：{raw[:120]!r}）")
        return None

    merged = _merge_series(existing, out_dates, {"close": out_values})
    new_count = len(merged["dates"]) - len(existing["dates"]) if existing and existing.get("dates") else len(merged["dates"])

    result = {
        "source": f"FRED ({series_id}) https://fred.stlouisfed.org/series/{series_id}",
        "series_id": series_id,
        "name": label,
        "fetched_at": date.today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
    }
    out_path = os.path.join(DATA_DIR, cache_file)
    _write_json(out_path, result)
    print(f"✅ {label} ({series_id}) 更新完成：本次新增 {max(new_count,0)} 筆，"
          f"快取總計 {len(merged['dates'])} 筆，最新 {merged['dates'][-1]} = {merged['close'][-1]}")
    return result


# ---------------------------------------------------------------------------
# 台股：製造業 PMI（國發會）
# ---------------------------------------------------------------------------
# data.gov.tw nid=6100「臺灣採購經理人指數」。
#
# 怎麼找到這個網址的（下次要換源時照這條路走，不要猜端點）：
#   1. GET https://data.gov.tw/api/front/dataset/dropdown?list_type=published&qs=採購經理人
#      → 拿到 nid
#   2. GET https://data.gov.tw/api/front/dataset/detail?nid=6100
#      → 真正的下載網址在 payload.resources[].url
#
# ⚠️ POST /api/front/dataset/list 不能用來搜尋：body 不管放 qs / keyword / q /
#    search，JSON 或 form-urlencoded 都一樣，一律回 search_count=53128（全站
#    資料集總數），等於完全沒過濾；同一路徑改用 GET 則回 405。
#    這是典型的「HTTP 200 但其實是空殼」，照著寫 parser 會拿到一堆不相干資料。
#
# ⚠️ data.gov.tw metadata 上寫的「最後更新 2025-01-07」是錯的，實檔已到 202608。
#    不要拿 metadata 的日期判斷資料新鮮度，要看檔案本身最後一列。
TW_PMI_CSV_URL = (
    "https://ws.ndc.gov.tw/Download.ashx?"
    "u=LzAwMS9hZG1pbmlzdHJhdG9yLzEwL3JlbGZpbGUvNTc4MS82MzkxL2JmOGE0ZWI3LTEwZmUtNGZhMC1iNjQ2LTMwZTg5MGQwMjE4YS5jc3Y%3d"
    "&n=6Ie654Gj5o6h6LO857aT55CG5Lq65oyH5pW4KHBtaeWPim5taSkuY3N2&icon=.csv"
)


def _yyyymm_to_iso(text):
    """'202608' -> '2026-08-01'；格式不對回 None（不猜、不補）。"""
    t = (text or "").strip()
    if len(t) != 6 or not t.isdigit():
        return None
    year, month = int(t[:4]), int(t[4:])
    if not (1900 <= year <= 2999 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-01"


def _roc_period_to_iso(text):
    """央行的期間格式 '2026M07' -> '2026-07-01'；格式不對回 None。"""
    t = (text or "").strip().upper()
    if "M" not in t:
        return None
    year_part, _, month_part = t.partition("M")
    if not (year_part.isdigit() and month_part.isdigit()):
        return None
    year, month = int(year_part), int(month_part)
    if not (1900 <= year <= 2999 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-01"


def _roc_month_to_iso(text):
    """櫃買的月份格式 "115年8月 Aug  '26" -> '2026-08-01'。

    只認「N年M月」這個前綴；純年度列（"104年"、"Year"）回 None，因為那個檔
    1989～2015 是年列、2016 起才是月列，兩種混在同一張表裡。
    """
    import re

    m = re.match(r"\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月", text or "")
    if not m:
        return None
    year, month = int(m.group(1)) + 1911, int(m.group(2))
    if not (1900 <= year <= 2999 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-01"


def _ods_rows(raw):
    """把一份 .ods（OpenDocument 試算表）解成 list[list[str]]。

    為什麼是 ODS 不是 XLS：櫃買同一份月報有 `.xls` 與 `&isOds=Y` 兩種。xls 是
    BIFF8，要 `xlrd`——而這個 repo 到目前為止**一個第三方套件都沒有**，排程
    也因此不需要 pip install。ODS 是 zip + XML，`zipfile` 加 `ElementTree`
    就解得開，維持零依賴。

    `number-columns-repeated` 是 ODS 壓縮空白格的方式，一格可能宣告重複幾千次，
    所以要設上限，不然一列會展開成一個巨大的 list。
    """
    import xml.etree.ElementTree as ET
    import zipfile

    ns = {
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    }
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        root = ET.fromstring(z.read("content.xml"))

    def cell_text(cell):
        # office:value 是機器可讀的原始數字；text:p 是顯示用的（會有千分位、
        # 也可能是 "1,234"）。有原始值就用原始值。
        val = cell.get("{%s}value" % ns["office"])
        if val is not None:
            return val
        return "".join("".join(p.itertext()) for p in cell.findall("text:p", ns))

    table = root.find(".//table:table", ns)
    if table is None:
        return []
    rows = []
    for row in table.findall("table:table-row", ns):
        cells = []
        for cell in row.findall("table:table-cell", ns):
            repeat = int(cell.get("{%s}number-columns-repeated" % ns["table"], 1))
            cells.extend([cell_text(cell)] * min(repeat, 32))
        if any(c.strip() for c in cells):
            rows.append(cells)
    return rows


CBC_LISTED_MARKETCAP_URL = (
    "https://www.cbc.gov.tw/public/data/OpenData/"
    "%E7%B6%93%E7%A0%94%E8%99%95/EG27M01.csv"
)
CBC_LISTED_MARKETCAP_COL = "上市股票-總市值-原始值"
TPEX_MONTHLY_INDEX_URL = "https://www.tpex.org.tw/www/zh-tw/statistics/monthlyRptMkt"
TPEX_OTC_MARKETCAP_COL = "上櫃股票市值(百萬元)"


def fetch_tw_listed_marketcap():
    """上市總市值（月），中央銀行經研處 OpenData `EG27M01.csv`。

    回傳 {ISO月份: 百萬元}；失敗回 None（呼叫端自己決定要不要沿用快取）。

    這支的價值在於它**不是滾動視窗**：一個檔案就給 1987M05 起的 471 個月，
    而且只落後一到兩個月。金管會那支 t49 只給最近五個月、落後四個月——歷史
    要靠本地一個月一個月累積，一次抓壞就永遠補不回來。

    ⚠️ 央行的站台第一次連線常常被 reset，一定要重試（`_http_get_with_retry`）。
    """
    try:
        raw = _http_get_with_retry(
            CBC_LISTED_MARKETCAP_URL, label="上市總市值（央行）"
        ).decode("utf-8-sig")
    except Exception as e:
        print(f"⚠️ 上市總市值（央行）抓取失敗：{e}")
        return None

    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or CBC_LISTED_MARKETCAP_COL not in reader.fieldnames:
        print(f"⚠️ 上市總市值（央行）缺少「{CBC_LISTED_MARKETCAP_COL}」欄位。"
              f"實際欄位：{reader.fieldnames}")
        return None

    out = {}
    for row in reader:
        iso = _roc_period_to_iso(row.get("月"))
        if not iso:
            continue
        try:
            out[iso] = float((row.get(CBC_LISTED_MARKETCAP_COL) or "").replace(",", "").strip())
        except ValueError:
            continue
    return out or None


def fetch_tw_otc_marketcap():
    """上櫃總市值（月），櫃買中心「歷年上櫃股票統計」。

    回傳 {ISO月份: 百萬元}；失敗回 None。

    兩步：先 POST `monthlyRptMkt`（`type=2`）拿當期的下載連結，再抓那份 ODS。
    **doc id 每個月會換，不能寫死**——所以索引那一步是必要的，不是多餘的。

    這個檔 1989～2015 是年列、2016-01 起才是月列，兩種混在同一張表；
    `_roc_month_to_iso` 只認「N年M月」，年列自然被跳過。

    （櫃買的 startDate／endDate 過濾在伺服器端是壞的，六種格式都回同一份。
    不影響：最新那個檔本身就含 2016 年至今的完整月序列。）
    """
    try:
        index = json.loads(_http_post(TPEX_MONTHLY_INDEX_URL, b"type=2").decode("utf-8"))
        rows = index["tables"][0]["data"]
        # 每一列是 [民國年月, xls 路徑, ods 路徑]；第一列是最新的那個月。
        ods_path = rows[0][2]
    except Exception as e:
        print(f"⚠️ 上櫃總市值（櫃買）索引抓取失敗：{e}")
        return None

    try:
        raw = _http_get_with_retry(
            "https://www.tpex.org.tw/www" + ods_path, label="上櫃總市值（櫃買）"
        )
        table = _ods_rows(raw)
    except Exception as e:
        print(f"⚠️ 上櫃總市值（櫃買）ODS 抓取或解析失敗：{e}")
        return None

    # 表頭那一列在前幾列，欄位位置不保證固定，所以用欄名找而不是寫死索引。
    col = None
    for row in table[:10]:
        for i, cell in enumerate(row):
            if cell.replace(" ", "").strip() == TPEX_OTC_MARKETCAP_COL.replace(" ", ""):
                col = i
                break
        if col is not None:
            break
    if col is None:
        print(f"⚠️ 上櫃總市值（櫃買）找不到「{TPEX_OTC_MARKETCAP_COL}」欄。"
              f"前幾列：{table[:4]}")
        return None

    out = {}
    for row in table:
        if len(row) <= col:
            continue
        iso = _roc_month_to_iso(row[0])
        if not iso:
            continue          # 年列（1989～2015）跳過，只要月列
        try:
            out[iso] = float((row[col] or "").replace(",", "").strip())
        except ValueError:
            continue
    return out or None


def fetch_tw_pmi(years_back=20, incremental=True):
    """
    抓臺灣製造業採購經理人指數 (PMI) 與非製造業經理人指數 (NMI)。
    來源: 國家發展委員會，data.gov.tw nid=6100（政府資料開放授權條款第1版）。

    CSV 欄位固定三欄：Date,PMI,NMI；Date 是 YYYYMM，201207 起。
    早期只有 PMI，NMI 欄位是 "-"（不是 0，也不是空字串）—— 這裡把它當缺值跳過。

    回傳 {"dates": [...], "pmi": [...], "nmi": [...]}，日期為該月 1 號。

    years_back 預設 20 年（來源實際只有 201207 起共 170 個月，所以等於全拿）。
    原本是 5 年——但 PMI 看的是景氣循環，59 個月連兩個完整循環都不到，而且
    「50 榮枯線」的意義本來就要放在多年的擴張收縮交替裡才讀得出來。來源那份
    CSV 一次就給全部，截短它沒有省到任何一次請求。
    """
    existing = _load_cache("tw_pmi.json") if incremental else None

    try:
        raw = _http_get_with_retry(TW_PMI_CSV_URL, label="臺灣PMI").decode("utf-8-sig")
    except Exception as e:
        print(f"⚠️ 臺灣PMI 重試 3 次仍失敗，未寫入任何檔案（不補假資料）: {e}")
        return None

    cutoff = date.today().replace(year=date.today().year - years_back).isoformat()
    out_dates, out_pmi, out_nmi = [], [], []
    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        iso = _yyyymm_to_iso(row.get("Date"))
        if not iso or iso < cutoff:
            continue

        def _num(raw_val):
            v = (raw_val or "").strip()
            if not v or v in ("-", "--", "N/A"):
                return None
            try:
                return float(v)
            except ValueError:
                return None

        pmi = _num(row.get("PMI"))
        nmi = _num(row.get("NMI"))
        if pmi is None and nmi is None:
            continue
        out_dates.append(iso)
        out_pmi.append(pmi)
        out_nmi.append(nmi)

    if not out_dates:
        print(f"⚠️ 臺灣PMI 解析不到任何資料列，未寫入任何檔案。（回應前 120 字：{raw[:120]!r}）")
        return None

    merged = _merge_series(existing, out_dates, {"pmi": out_pmi, "nmi": out_nmi})
    result = {
        "source": "國家發展委員會 臺灣採購經理人指數 (data.gov.tw nid=6100)",
        "landing_page": "https://data.gov.tw/dataset/6100",
        "unit": "指數（50 為榮枯線）",
        "fetched_at": date.today().isoformat(),
        "dates": merged["dates"],
        "pmi": merged["pmi"],
        "nmi": merged["nmi"],
    }
    out_path = os.path.join(DATA_DIR, "tw_pmi.json")
    _write_json(out_path, result)
    print(f"✅ 臺灣PMI 更新完成：快取總計 {len(merged['dates'])} 個月，"
          f"最新 {merged['dates'][-1]} PMI={merged['pmi'][-1]} NMI={merged['nmi'][-1]}")
    return result


# ---------------------------------------------------------------------------
# 台股：M1B 貨幣總計數（中央銀行）
# ---------------------------------------------------------------------------
# ⚠️ 央行有兩個檔名很像、欄位名幾乎一模一樣的檔案，抓錯不會有任何錯誤訊息：
#
#   EF15M01.csv  貨幣總計數（日平均數，月資料）  欄位「貨幣總計數 -Ｍ１Ｂ-原始值」
#                → 這是 **餘額**，2026M07 = 30,530,948 百萬元　✅ 要的是這個
#
#   EF19M01.csv  M1B變動因素分析               欄位「貨幣總計數-Ｍ１Ｂ-原始值-百萬元」
#                → 這是 **當月變動額**，2026M07 = -96,069　❌ 抓錯只會畫出一條
#                  在零附近抖動的線，不會報錯
#
# 差別只在欄名中間有沒有空格、結尾有沒有「-百萬元」。所以下面用「必須包含
# Ｍ１Ｂ 且包含 原始值」來找欄位，並且對數值做合理性檢查（餘額必為正、且量級
# 在兆元等級），抓到變動額會直接示警而不是默默寫進去。
CBC_M1B_CSV_URL = "https://www.cbc.gov.tw/public/data/OpenData/%E7%B6%93%E7%A0%94%E8%99%95/EF15M01.csv"


def fetch_tw_m1b(years_back=11, incremental=True):
    """
    抓 M1B 貨幣總計數（日平均數，月資料）。
    來源: 中央銀行開放資料 EF15M01.csv，1987M05 起。

    單位：新臺幣百萬元。回傳 {"dates": [...], "m1b": [...], "yoy": [...]}。

    years_back 預設 11 年。市值貨幣比是拿來看「相對於歷史區間的高低」，所以
    分母的視窗不該比分子短——分子（上市＋上櫃總市值）受限於櫃買的月資料，
    從 2016-01 開始。11 年剛好蓋得住它，多的部分自然被交集切掉。
    來源本身有 1987M05 起的完整歷史，哪天分子往前延伸了，這裡跟著加就好。
    """
    existing = _load_cache("tw_m1b.json") if incremental else None

    try:
        raw = _http_get_with_retry(CBC_M1B_CSV_URL, label="M1B").decode("utf-8-sig")
    except Exception as e:
        print(f"⚠️ M1B 重試 3 次仍失敗，未寫入任何檔案（不補假資料）: {e}")
        return None

    reader = csv.reader(io.StringIO(raw))
    rows = [r for r in reader if r]
    if len(rows) < 2:
        print(f"⚠️ M1B 回應不是預期的 CSV，未寫入任何檔案。（回應前 120 字：{raw[:120]!r}）")
        return None

    header = [h.strip() for h in rows[0]]

    def _find_col(*must_contain, exclude=()):
        for i, h in enumerate(header):
            flat = h.replace(" ", "")
            if all(tok in flat for tok in must_contain) and not any(x in flat for x in exclude):
                return i
        return None

    # 「Ｍ１Ｂ」是全形，央行檔案裡就是這樣寫的，不要改成半形 M1B
    idx_val = _find_col("Ｍ１Ｂ", "原始值")
    idx_yoy = _find_col("Ｍ１Ｂ", "年增率")
    if idx_val is None:
        print(f"⚠️ M1B 在回應裡找不到「Ｍ１Ｂ-原始值」欄位，未寫入任何檔案。"
              f"欄位清單：{header[:5]}...（共 {len(header)} 欄）")
        return None

    cutoff = date.today().replace(year=date.today().year - years_back).isoformat()
    out_dates, out_val, out_yoy = [], [], []
    for r in rows[1:]:
        if idx_val >= len(r):
            continue
        iso = _roc_period_to_iso(r[0])
        if not iso or iso < cutoff:
            continue
        try:
            val = float(r[idx_val].replace(",", "").strip())
        except (ValueError, AttributeError):
            continue
        yoy = None
        if idx_yoy is not None and idx_yoy < len(r):
            try:
                yoy = float(r[idx_yoy].replace(",", "").strip())
            except (ValueError, AttributeError):
                yoy = None
        out_dates.append(iso)
        out_val.append(val)
        out_yoy.append(yoy)

    if not out_dates:
        print("⚠️ M1B 解析不到任何資料列，未寫入任何檔案。")
        return None

    # 抓錯檔案（EF19 變動額）的守門：餘額必為正，且應該在「兆元」等級
    # （百萬元為單位 → 至少七位數）。變動額會是有正有負的六位數以下。
    latest = out_val[-1]
    if latest <= 0 or latest < 1_000_000:
        print(f"⚠️ M1B 最新值 {latest:,.0f} 不像餘額（餘額應為正且在千萬百萬元等級）。"
              f"很可能抓到了 EF19M01「變動因素分析」而不是 EF15M01。未寫入任何檔案。")
        return None

    merged = _merge_series(existing, out_dates, {"m1b": out_val, "yoy": out_yoy})
    result = {
        "source": "中央銀行 貨幣總計數（日平均數，月資料）EF15M01",
        "landing_page": "https://data.gov.tw/dataset/6024",
        "unit": "新臺幣百萬元",
        "fetched_at": date.today().isoformat(),
        "dates": merged["dates"],
        "m1b": merged["m1b"],
        "yoy": merged["yoy"],
    }
    out_path = os.path.join(DATA_DIR, "tw_m1b.json")
    _write_json(out_path, result)
    print(f"✅ M1B 更新完成：快取總計 {len(merged['dates'])} 個月，"
          f"最新 {merged['dates'][-1]} = {merged['m1b'][-1]:,.0f} 百萬元（年增 {merged['yoy'][-1]}%）")
    return result


# ---------------------------------------------------------------------------
# 台股：上市櫃總市值（金管會證期局 t49）
# ---------------------------------------------------------------------------
# ⚠️ 這個端點只回「最近 5 個月」的滾動視窗，而且沒有分頁參數可以要更多 ——
#    試過 ?limit=1000、?page=1&size=1000、?year=，回傳位元組完全一樣。
#    所以歷史只能靠「每次跑就把新月份併進本地快取」慢慢累積，
#    而且必須是 merge 不是覆蓋：一次抓失敗或只抓到部分月份，
#    絕不能把已經累積好的歷史洗掉。
#
# ⚠️ 這個來源落後很多（證期局是「不定期更新」）。2026-09-09 抓到的最新資料
#    月份是 202605，公告日期 20260623。報告上要標「資料月份」，不能寫「最新」。
FSC_MARKET_CAP_URL = "https://stat.fsc.gov.tw/api/v1/public/datasets/11138/export"


def _fetch_fsc_market_cap():
    """t49 的上市＋上櫃合計市值，{ISO月份: (百萬元, 家數)}。抓不到回 None。

    這一支從「唯一的來源」降級成「對帳用的第二意見」。它只給最近五個月、
    落後四個月，但它是**獨立編製**的：央行＋櫃買加起來如果跟它對得上，
    那兩支的單位、口徑（期末而非月平均）、以及「一個只含上市、一個只含上櫃」
    這件事就同時被證明了。對不上就出聲——那是真的有東西變了。
    """
    try:
        raw = _http_get_with_retry(FSC_MARKET_CAP_URL, label="上市櫃總市值（t49 對帳）").decode("utf-8-sig")
    except Exception as e:
        print(f"　　（t49 對帳來源抓不到，跳過對帳：{e}）")
        return None
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "市值_十億元" not in reader.fieldnames:
        print(f"　　（t49 欄位變了，跳過對帳。實際欄位：{reader.fieldnames}）")
        return None
    out = {}
    for row in reader:
        iso = _yyyymm_to_iso(row.get("年月"))
        if not iso:
            continue
        try:
            cap = float((row.get("市值_十億元") or "").replace(",", "").strip()) * 1000.0
        except ValueError:
            continue
        try:
            count = int(float((row.get("上市櫃家數") or "").replace(",", "").strip()))
        except ValueError:
            count = None
        out[iso] = (cap, count)
    return out or None


def fetch_tw_market_cap(incremental=True):
    """上市＋上櫃總市值（月），單位新臺幣百萬元。

    **三個來源，兩種角色。**

    主來源（歷史）：
      上市　中央銀行經研處 `EG27M01.csv`　　1987M05 起 471 個月，落後 1～2 個月
      上櫃　櫃買中心「歷年上櫃股票統計」　　2016-01 起逐月，落後 1 個月

    對帳（第二意見）：
      金管會證期局 t49　　　　　　　　　　　最近 5 個月滾動視窗，落後約 4 個月

    原本只有 t49，於是歷史只能「每個月跑一次、慢慢累積」——而它是滾動視窗，
    一次抓壞就永遠補不回來，實際累積了半年也只有 5 個月。換成主來源之後，
    一次抓取就拿到十年，而且是可重跑的：任何一天重跑都會得到同一份歷史。

    t49 留著不是備份，是**測試**。它獨立編製，如果央行＋櫃買加起來跟它對得上
    （實測四個重疊月份逐位元相同），那就同時證明了單位、期末口徑、以及
    「一個只含上市、一個只含上櫃」這三件事。對不上就出聲。

    回傳 {"dates": [...], "market_cap": [...(百萬元)], "listed_count": [...]}。
    """
    existing = _load_cache("tw_market_cap.json") if incremental else None

    listed = fetch_tw_listed_marketcap()
    otc = fetch_tw_otc_marketcap()
    if not listed or not otc:
        missing = " / ".join(
            n for n, v in (("上市（央行）", listed), ("上櫃（櫃買）", otc)) if not v
        )
        print(f"⚠️ 上市櫃總市值：{missing} 沒抓到，保留既有快取不動（不覆蓋、不補假資料）。")
        SOFT_FAILURES.append(f"上市櫃總市值（{missing} 失敗，沿用既有快取）")
        return existing

    # 兩邊都有的月份才算數。上櫃只到 2016-01，上市可以回到 1987——但相加需要
    # 兩邊都在，缺一邊的月份寫進去就是一個少了三分之一的假總額。
    months = sorted(set(listed) & set(otc))
    if not months:
        print("⚠️ 上市櫃總市值：兩個來源沒有共同月份，保留既有快取不動。")
        SOFT_FAILURES.append("上市櫃總市值（兩來源無交集，沿用既有快取）")
        return existing

    out_dates = months
    out_cap = [listed[m] + otc[m] for m in months]

    # --- 對帳 ---------------------------------------------------------
    fsc = _fetch_fsc_market_cap()
    out_count = [None] * len(months)
    checked = mismatched = 0
    if fsc:
        for i, m in enumerate(months):
            if m not in fsc:
                continue
            ref, count = fsc[m]
            out_count[i] = count
            checked += 1
            # 千分之一的容差。兩邊實測是逐位元相同，這個容差留給日後可能的
            # 四捨五入位數變動，不是留給「口徑不一樣」——差到 0.1% 以上就是
            # 真的有東西變了。
            if ref and abs(out_cap[i] - ref) / ref > 0.001:
                mismatched += 1
                print(f"⚠️ 對帳不符 {m}：央行＋櫃買 {out_cap[i]:,.0f} vs t49 {ref:,.0f}"
                      f"（差 {abs(out_cap[i]-ref)/ref*100:.2f}%）")
        if mismatched:
            print(f"::warning::上市櫃總市值 對帳有 {mismatched}/{checked} 個月對不上，"
                  "請確認來源的口徑或單位是不是變了")
            SOFT_FAILURES.append(f"上市櫃總市值（對帳 {mismatched} 個月不符）")
        elif checked:
            print(f"　　t49 對帳：{checked} 個重疊月份全部相符 ✓")

    merged = _merge_series(existing, out_dates, {"market_cap": out_cap, "listed_count": out_count})
    old_len = len(existing["dates"]) if existing and existing.get("dates") else 0
    if len(merged["dates"]) < old_len:
        print(f"⚠️ 合併後月份數（{len(merged['dates'])}）比原本（{old_len}）還少，"
              f"這不該發生，為保險起見不寫檔。")
        return existing

    result = {
        "source": "上市：中央銀行經研處 EG27M01；上櫃：櫃買中心 歷年上櫃股票統計；"
                  "對帳：金管會證期局 t49 (data.gov.tw nid=11138)",
        "landing_page": "https://www.cbc.gov.tw/tw/lp-1114-1.html",
        "unit": "新臺幣百萬元",
        "scope": "上市＋上櫃合計",
        "note": "上市來自央行（1987M05 起，無滾動視窗）、上櫃來自櫃買（2016-01 起逐月），"
                "兩者相加；金管會 t49 只作對帳用。兩邊都有資料的月份才寫入。",
        "fetched_at": date.today().isoformat(),
        "latest_source_month": out_dates[-1],
        "reconciled_months": checked,
        "reconcile_mismatches": mismatched,
        "dates": merged["dates"],
        "market_cap": merged["market_cap"],
        "listed_count": merged["listed_count"],
    }
    out_path = os.path.join(DATA_DIR, "tw_market_cap.json")
    _write_json(out_path, result)
    print(f"✅ 上市櫃總市值 更新完成：上市 {len(listed)} 個月 × 上櫃 {len(otc)} 個月 "
          f"→ 交集 {len(months)} 個月，合併後快取總計 {len(merged['dates'])} 個月，"
          f"最新月份 {out_dates[-1]}（落後 {_months_behind(out_dates[-1])} 個月）")
    return result


def _months_behind(iso_month):
    """算某個資料月份落後現在幾個月，用來在報告上誠實標示新鮮度。"""
    try:
        y, m, _ = iso_month.split("-")
        today = date.today()
        return (today.year - int(y)) * 12 + (today.month - int(m))
    except (ValueError, AttributeError):
        return None


def compute_tw_marketcap_m1b_ratio():
    """
    算市值貨幣比 = 上市櫃總市值 ÷ M1B。

    兩邊都已經是新臺幣百萬元，直接相除即可。只輸出「兩邊都有資料」的月份 ——
    M1B 通常比市值新，多出來的月份不會拿舊市值去湊，那會畫出一段假的走勢。

    這支不打網路，只讀 data/tw_market_cap.json 與 data/tw_m1b.json，
    所以可以離線重算。
    """
    cap = _load_cache("tw_market_cap.json")
    m1b = _load_cache("tw_m1b.json")
    if not cap or not cap.get("dates"):
        print("⚠️ 市值貨幣比：缺 data/tw_market_cap.json，本次不計算。")
        return None
    if not m1b or not m1b.get("dates"):
        print("⚠️ 市值貨幣比：缺 data/tw_m1b.json，本次不計算。")
        return None

    m1b_by_month = dict(zip(m1b["dates"], m1b["m1b"]))
    out_dates, out_ratio, out_cap, out_m1b = [], [], [], []
    for d, c in zip(cap["dates"], cap["market_cap"]):
        mv = m1b_by_month.get(d)
        if c is None or mv in (None, 0):
            continue
        out_dates.append(d)
        out_ratio.append(round(c / mv, 4))
        out_cap.append(c)
        out_m1b.append(mv)

    if not out_dates:
        print("⚠️ 市值貨幣比：市值與 M1B 沒有任何共同月份（市值來源落後太多？），本次不計算。")
        return None

    result = {
        "source": "自行計算：上市櫃總市值(證期局t49) ÷ M1B(央行EF15M01)，兩者皆為新臺幣百萬元",
        "fetched_at": date.today().isoformat(),
        "latest_month": out_dates[-1],
        "months_behind": _months_behind(out_dates[-1]),
        "dates": out_dates,
        "ratio": out_ratio,
        "market_cap": out_cap,
        "m1b": out_m1b,
    }
    out_path = os.path.join(DATA_DIR, "tw_marketcap_m1b.json")
    _write_json(out_path, result)
    print(f"✅ 市值貨幣比 計算完成：{len(out_dates)} 個月，"
          f"最新 {out_dates[-1]} = {out_ratio[-1]}（資料落後 {result['months_behind']} 個月）")
    return result


# ---------------------------------------------------------------------------
# 美股：三大指數（跟台股/日經同一支 Yahoo Chart API）
# ---------------------------------------------------------------------------
def fetch_index(symbol, key, name="", years_back=5, incremental=True):
    """
    抓任一指數的真實每日收盤，來源 Yahoo Finance Chart API（免金鑰）。
    symbol 例如 "^DJI"（道瓊）、"^GSPC"（S&P 500）、"^IXIC"（NASDAQ）。
    key 是存檔代號 -> data/index_<key>.json

    跟 fetch_nikkei() 同一套增量邏輯，只是指數代碼可設定。
    """
    label = name or symbol
    existing = _load_cache(f"index_{key}.json") if incremental else None
    range_param, last_cached = _yahoo_range_for_incremental(existing, years_back)
    if last_cached:
        print(f"📂 {label} 既有快取到 {last_cached.isoformat()}，本次只跟 Yahoo 要 range={range_param}（增量模式）")

    quoted = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quoted}?range={range_param}&interval=1d"
    try:
        payload = _fetch_json_with_retry(url, max_retries=3, backoff_sec=3)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"⚠️ {label} 重試 3 次仍失敗，未寫入任何檔案（不補假資料）: {e}")
        return None

    try:
        result_block = payload["chart"]["result"][0]
        timestamps = result_block["timestamp"]
        closes = result_block["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as e:
        print(f"⚠️ {label} 回傳格式異常，未寫入任何檔案: {e}")
        return None

    out_dates, out_close = [], []
    for ts, c in zip(timestamps, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        out_dates.append(d.isoformat())
        out_close.append(round(float(c), 2))

    merged = _merge_series(existing, out_dates, {"close": out_close})
    new_count = len(merged["dates"]) - len(existing["dates"]) if existing and existing.get("dates") else len(merged["dates"])

    result = {
        "source": f"Yahoo Finance Chart API ({symbol})",
        "symbol": symbol,
        "name": label,
        "fetched_at": date.today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
    }
    out_path = os.path.join(DATA_DIR, f"index_{key}.json")
    _write_json(out_path, result)
    print(f"✅ {label} 更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實交易日")
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

    # 每個來源都記錄成功/失敗。失敗不是印一行就算了 —— 最後會彙總，
    # 而且整支程式會以非 0 結束碼退出，這樣排程/CI 才會真的出聲。
    # 靜靜失敗最糟的地方在於：市值那種「合併寫入」的資料，
    # 會默默累積出一個有洞的歷史檔，等到發現時已經補不回來。
    failures = []

    def _run(label, fn, *a, **kw):
        try:
            result = fn(*a, **kw)
        except CacheUnreadable as e:
            # 這一類跟「網路不通」完全不同：既有的歷史檔壞了，而歷史是累積出來
            # 的，重跑不會長回來。所以要用 GitHub 的 error annotation 叫出來，
            # 不要混在一堆 ❌ 裡面被滑過去。
            print(f"::error::{label} 的歷史快取毀損：{e}")
            print(f"❌ {label} 歷史快取毀損，已保留原檔不動：{e}")
            failures.append(f"{label}（歷史快取毀損）")
            return None
        except Exception as e:  # noqa: BLE001 - 單一來源爆掉不該讓其他來源跟著死
            print(f"❌ {label} 發生未預期例外：{e!r}")
            failures.append(label)
            return None
        if result is None:
            failures.append(label)
        return result

    print("=" * 60)
    print("【台股】")
    _run("台股加權指數", fetch_taiex, years_back=5)
    _run("臺灣PMI", fetch_tw_pmi)
    _run("M1B", fetch_tw_m1b)
    _run("上市櫃總市值", fetch_tw_market_cap)
    _run("市值貨幣比", compute_tw_marketcap_m1b_ratio)

    print("=" * 60)
    print("【美股】")
    _run("VIX", fetch_vix)
    for idx in load_us_indices():
        _run(idx["name"], fetch_index, idx["symbol"], idx["key"], name=idx["name"], years_back=5)
    for series in load_fred_series():
        # 視窗長度由 config_loader 依頻率決定（月／季 25 年、週 15 年），
        # 設定檔裡也可以逐筆用 years_back 覆寫。原本這裡寫死 5——對一組拿來
        # 判斷「現在在景氣循環哪個位置」的指標來說，那連一輪都蓋不住。
        _run(f"{series['name']}({series['id']})", fetch_fred_series,
             series["id"], name=series["name"],
             years_back=series.get("years_back", 25),
             cache_name=series.get("cache"))

    print("=" * 60)
    print("【日股】")
    _run("日經225", fetch_nikkei, years_back=5)

    stocks = load_jp_stocks(include_disabled=args.include_hidden)
    if not stocks:
        print("⚠️ config.json 裡沒有任何啟用中的個股，本次不抓個股股價。")
    else:
        hidden_note = "（含隱藏個股）" if args.include_hidden else ""
        print(f"\n📋 依 config.json 設定，本次更新 {len(stocks)} 檔個股股價{hidden_note}")
        for s in stocks:
            _run(s["name"], fetch_jp_stock, s["code"], s["key"], name=s["name"])

    print("\n💡 提醒：本程式只更新『價格類』與『總經指標』資料。")
    print("   季度財報（營收/獲利/EPS/BVPS）與村田 B/B Ratio 不會自動更新，需人工登錄後才會變動。")
    print("   可執行 `python check_earnings_due.py` 查看目前有哪些個股進入財報公布窗口。")
    print("   ISM 製造業/服務業 PMI 沒有免費官方源（FRED 的 NAPM 已於 2016 年下架，實測回 404），")
    print("   所以它不在 config.json 的 us_fred_series 裡，報告上也沒有這一格。")

    # 結束碼刻意分成三種，因為呼叫端（run.py update）需要分辨得出來：
    #   0 = 全部成功
    #   2 = 有來源失敗，但既有快取還在，報告照樣產得出來 → 不要中斷整天的流程
    #   1 = 連 argparse 之前就爆掉之類的致命錯誤（由未捕捉的例外自然產生）
    # 一開始這裡是失敗就 exit 1，結果會讓「一個端點抽風」變成「今天整份報告都沒有」，
    # 那比靜靜失敗更糟。要吵，但不要把當天已經抓好的東西一起丟掉。
    print("\n" + "=" * 60)
    if SOFT_FAILURES:
        print(f"⚠️ 有 {len(SOFT_FAILURES)} 個來源這次沒抓到新資料，但既有快取還在：")
        for item in SOFT_FAILURES:
            print(f"   - {item}")
        print("   報告仍然可以產生，但那格的資料月份不會前進 —— 連續幾天看到這行就要去查來源。")
    if failures:
        print(f"❌ 本次有 {len(failures)} 個資料源失敗：{', '.join(failures)}")
        print("   這些資料源的既有快取維持原狀，沒有被覆蓋，也沒有補任何假資料。")
        print("   請確認網路或來源端點是否變動後重跑。")
        print("   （結束碼 2：報告仍可用既有快取產生，不會因此中斷當天流程）")
        sys.exit(2)
    if SOFT_FAILURES:
        sys.exit(2)
    print("✅ 所有資料源都成功更新。")
