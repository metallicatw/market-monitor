# -*- coding: utf-8 -*-

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

SOFT_FAILURES = []

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MarketMonitorBot/1.0)"
}

def _build_ssl_context():
    ctx = ssl.create_default_context()
    try:
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    except AttributeError:
        pass
    return ctx


SSL_CONTEXT = _build_ssl_context()


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
        return resp.read()


def _http_post(url, data, timeout=30):
    req = urllib.request.Request(
        url, data=data,
        headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
        return resp.read()


def _fetch_json_with_retry(url, max_retries=3, backoff_sec=3):
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            raw = _http_get(url)
            return json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(backoff_sec * attempt)
    raise last_err



TAIPEI_TZ = timezone(timedelta(hours=8))


def _today():
    return datetime.now(TAIPEI_TZ).date()


def _years_ago(n):
    d = _today()
    return date(d.year - n, d.month, 1)


def _write_json(path, obj):
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class CacheUnreadable(Exception):
    pass


def _load_cache(filename):
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
            val = new_fields[name][i]
            if val is None and d in combined and combined[d].get(name) is not None:
                continue
            combined.setdefault(d, {})[name] = val

    sorted_dates = sorted(combined.keys())
    merged = {"dates": sorted_dates}
    for name in field_names:
        merged[name] = [combined[d].get(name) for d in sorted_dates]
    return merged



def _stalled(label, existing, merged):
    if not (existing and existing.get("dates")):
        return False
    if not merged.get("dates"):
        print(f"❌ {label}：合併之後一筆資料都沒有。既有快取原封不動保留，"
              "但這一支這次不算成功。")
        return True
    if merged["dates"][-1] > existing["dates"][-1]:
        return False
    if len(merged["dates"]) > len(existing["dates"]):
        return False
    print(f"⚠️ {label}：資料最後一天還停在 {existing['dates'][-1]}，一筆都沒有前進。"
          "多半是上游回了空的或格式變了——既有快取原封不動保留，"
          "但這一支這次不算成功。")
    return True


def _yahoo_range_for_incremental(existing, years_back=5, buffer_days=3):
    if not existing or not existing.get("dates"):
        return f"{years_back}y", None
    try:
        last_date = date.fromisoformat(existing["dates"][-1])
    except ValueError:
        return f"{years_back}y", None

    days_gap = (_today() - last_date).days + buffer_days
    if days_gap <= 7:
        return "5d", last_date
    elif days_gap <= 30:
        return "1mo", last_date
    elif days_gap <= 95:
        return "3mo", last_date
    elif days_gap <= 370:
        return "1y", last_date
    else:
        return f"{years_back}y", last_date


def _month_range(years_back=5):
    today = _today()
    start = date(today.year - years_back, today.month, 1)
    months = []
    cur = date(start.year, start.month, 1)
    while cur <= today:
        months.append(cur.strftime("%Y%m01"))
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return months


def fetch_taiex(years_back=5, sleep_sec=1.5, incremental=True):
    existing = _load_cache("taiex.json") if incremental else None

    if existing and existing.get("dates"):
        last_date = datetime.strptime(existing["dates"][-1], "%Y-%m-%d").date()
        start_month = date(last_date.year, last_date.month, 1)
        print(f"📂 偵測到既有快取，最後資料到 {existing['dates'][-1]}，"
              f"本次只重抓 {start_month.strftime('%Y-%m')} 之後的月份（增量模式）")
    else:
        start_month = _years_ago(years_back)
        print("📂 沒有偵測到既有快取，執行完整 5 年回補（第一次執行才會這麼慢）")

    months = []
    cur = start_month
    today = _today()
    while cur <= today:
        months.append(cur.strftime("%Y%m01"))
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)

    carried = [m for m in (existing or {}).get("failed_months", []) or []
               if isinstance(m, str) and m not in months]
    if carried:
        print(f"↩️ 上一次有 {len(carried)} 個月份沒抓到，這次一起補：{carried}")
        months = sorted(set(months) | set(carried))

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

    if failed_months and not out_dates:
        print(f"❌ TAIEX：{len(failed_months)} 個月份全部失敗（{failed_months}），"
              "一天新資料都沒拿到。既有快取原封不動保留，但這一支這次不算成功。")
        return None

    merged = _merge_series(existing, out_dates, {
        "close": out_close, "volume_shares": out_vol, "value_twd": out_val,
    })

    result = {
        "source": "TWSE FMTQIK (https://www.twse.com.tw/zh/trading/historical/fmtqik.html)",
        "fetched_at": _today().isoformat(),
        "failed_months": sorted(set(failed_months)),
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

    cutoff = _years_ago(5)
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

    if _stalled("VIX", existing, merged):
        return None

    result = {
        "source": "CBOE 官方 VIX 歷史資料 (https://www.cboe.com/tradable_products/vix/vix_historical_data/)",
        "fetched_at": _today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
    }
    out_path = os.path.join(DATA_DIR, "vix.json")
    _write_json(out_path, result)
    print(f"✅ VIX 資料更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實交易日，寫入 {out_path}")
    return result


def fetch_nikkei(years_back=5, incremental=True):
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
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        out_dates.append(d.isoformat())
        out_close.append(round(float(c), 2))

    merged = _merge_series(existing, out_dates, {"close": out_close})
    new_count = len(merged["dates"]) - len(existing["dates"]) if existing and existing.get("dates") else len(merged["dates"])

    if _stalled("日經225", existing, merged):
        return None

    result = {
        "source": "Yahoo Finance Chart API (^N225)",
        "fetched_at": _today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
    }
    out_path = os.path.join(DATA_DIR, "nikkei.json")
    _write_json(out_path, result)
    print(f"✅ 日經225 資料更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實交易日，寫入 {out_path}")
    return result


def fetch_michigan_sentiment(incremental=True):
    existing = _load_cache("michigan.json") if incremental else None

    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UMCSENT"
    try:
        raw = _http_get(url).decode("utf-8-sig")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"⚠️ 密大信心指數 抓取失敗，未寫入任何檔案（不補假資料）: {e}")
        return None

    cutoff = _years_ago(5)
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
        "fetched_at": _today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
    }
    out_path = os.path.join(DATA_DIR, "michigan.json")
    _write_json(out_path, result)
    print(f"✅ 密大信心指數 資料更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實月份，寫入 {out_path}")
    return result


def fetch_jp_stock(code, key, name="", years_back=5, incremental=True):
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

    if _stalled(f"{name or code}", existing, merged):
        return None

    result = {
        "source": f"Yahoo Finance Chart API ({code})",
        "code": code,
        "name": name or code,
        "fetched_at": _today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
        "volume": merged["volume"],
    }
    out_path = os.path.join(DATA_DIR, f"stock_{key}.json")
    _write_json(out_path, result)
    print(f"✅ {name or code} 資料更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實交易日，寫入 {out_path}")
    return result


def _http_get_with_retry(url, max_retries=3, backoff_sec=3, timeout=30, label=""):
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return _http_get(url, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(backoff_sec * attempt)
    raise last_err


def _parse_fred_csv(raw_text, series_id, cutoff):
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
    label = name or series_id
    cache_file = cache_name or f"fred_{series_id.lower()}.json"
    existing = _load_cache(cache_file) if incremental else None

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        raw = _http_get_with_retry(url, label=label).decode("utf-8-sig")
    except Exception as e:
        print(f"⚠️ {label} ({series_id}) 重試 3 次仍失敗，未寫入任何檔案（不補假資料）: {e}")
        return None

    cutoff = _years_ago(years_back)
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
        "fetched_at": _today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
    }
    if existing:
        for key in MICHIGAN_OFFICIAL_KEYS:
            if key in existing:
                result[key] = existing[key]
        if result.get("prelim"):
            have = set(out_dates)
            result["prelim"] = [d for d in result["prelim"] if d not in have]
    out_path = os.path.join(DATA_DIR, cache_file)
    _write_json(out_path, result)
    print(f"✅ {label} ({series_id}) 更新完成：本次新增 {max(new_count,0)} 筆，"
          f"快取總計 {len(merged['dates'])} 筆，最新 {merged['dates'][-1]} = {merged['close'][-1]}")
    return result


MICHIGAN_TABLE_URL = "https://www.sca.isr.umich.edu/files/tbmics.csv"
MICHIGAN_HOME_URL = "https://www.sca.isr.umich.edu/"
MICHIGAN_OFFICIAL_KEYS = ("prelim", "next_release", "official_source")

_EN_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"), start=1)}


def parse_michigan_table(raw):
    import csv
    import io

    text = raw.decode("utf-8-sig", "replace") if isinstance(raw, bytes) else raw
    dates, values = [], []
    for row in csv.DictReader(io.StringIO(text)):
        month = _EN_MONTHS.get((row.get("Month") or "").strip().lower())
        year = (row.get("YYYY") or "").strip()
        val = (row.get("ICS_ALL") or "").strip()
        if not month or not year.isdigit():
            continue
        try:
            v = float(val)
        except ValueError:
            continue
        dates.append(f"{int(year):04d}-{month:02d}-01")
        values.append(v)
    return dates, values


def parse_michigan_home(raw):
    import html as _html
    import re

    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text)

    head = re.search(r"(Preliminary|Final)\s+Results\s+for\s+([A-Za-z]+)\s+(\d{4})", text)
    if not head:
        return None
    month = _EN_MONTHS.get(head.group(2).lower())
    if not month:
        return None
    row = re.search(r"Index of Consumer Sentiment\s+(-?\d+(?:\.\d+)?)", text[head.end():])
    if not row:
        return None
    out = {
        "month": f"{int(head.group(3)):04d}-{month:02d}-01",
        "value": float(row.group(1)),
        "status": "preliminary" if head.group(1).lower() == "preliminary" else "final",
        "next_release": None,
    }
    nxt = re.search(r"Next data release:\s*[A-Za-z]+,\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})"
                    r"\s+for\s+(Preliminary|Final)\s+([A-Za-z]+)", text)
    if nxt and _EN_MONTHS.get(nxt.group(1).lower()) and _EN_MONTHS.get(nxt.group(5).lower()):
        out["next_release"] = {
            "date": f"{int(nxt.group(3)):04d}-{_EN_MONTHS[nxt.group(1).lower()]:02d}-{int(nxt.group(2)):02d}",
            "what": nxt.group(4).lower(),
            "month": _EN_MONTHS[nxt.group(5).lower()],
        }
    return out


def merge_michigan_official(existing, table, home):
    base = dict(existing or {})
    t_dates, t_vals = table if table else ([], [])
    if base.get("dates") and t_dates:
        first = base["dates"][0]
        keep = [i for i, d in enumerate(t_dates) if d >= first]
        t_dates = [t_dates[i] for i in keep]
        t_vals = [t_vals[i] for i in keep]
    merged = _merge_series(base if base.get("dates") else None, t_dates, {"close": t_vals})

    finals = set(t_dates)
    prelim = [d for d in (base.get("prelim") or []) if d not in finals]
    next_release = base.get("next_release")
    if home:
        next_release = home.get("next_release") or next_release
        if home["month"] not in finals:
            merged = _merge_series(merged, [home["month"]], {"close": [home["value"]]})
            if home["status"] == "preliminary":
                prelim = sorted(set(prelim) | {home["month"]})
            else:
                prelim = [d for d in prelim if d != home["month"]]
    have = set(merged["dates"])
    prelim = [d for d in prelim if d in have]

    base.update({
        "dates": merged["dates"],
        "close": merged["close"],
        "prelim": prelim,
        "next_release": next_release,
        "official_source": MICHIGAN_HOME_URL,
    })
    base.setdefault("series_id", "UMCSENT")
    base.setdefault("name", "密大消費者信心")
    return base


def fetch_michigan_official(cache_name="michigan.json"):
    existing = _load_cache(cache_name)
    try:
        table = parse_michigan_table(_http_get_with_retry(MICHIGAN_TABLE_URL, label="密大官網表格"))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 密大官網表格抓不到，michigan.json 維持 FRED 那一份：{e}")
        return None
    if not table[0]:
        print("⚠️ 密大官網表格解析不到任何資料列（格式變了？），michigan.json 維持原狀")
        return None
    try:
        home = parse_michigan_home(_http_get_with_retry(MICHIGAN_HOME_URL, label="密大官網首頁"))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 密大官網首頁抓不到，這次只有終值：{e}")
        home = None
    if home is None:
        print("⚠️ 密大官網首頁認不出當月數字，這次只有終值")

    result = merge_michigan_official(existing, table, home)
    result["fetched_at"] = _today().isoformat()
    _write_json(os.path.join(DATA_DIR, cache_name), result)
    tag = "（初值）" if result["dates"][-1] in result["prelim"] else ""
    print(f"✅ 密大消費者信心（官網）：最新 {result['dates'][-1][:7]} = "
          f"{result['close'][-1]}{tag}")
    return result


TW_PMI_CSV_URL = (
    "https://ws.ndc.gov.tw/Download.ashx?"
    "u=LzAwMS9hZG1pbmlzdHJhdG9yLzEwL3JlbGZpbGUvNTc4MS82MzkxL2JmOGE0ZWI3LTEwZmUtNGZhMC1iNjQ2LTMwZTg5MGQwMjE4YS5jc3Y%3d"
    "&n=6Ie654Gj5o6h6LO857aT55CG5Lq65oyH5pW4KHBtaeWPim5taSkuY3N2&icon=.csv"
)


def _yyyymm_to_iso(text):
    t = (text or "").strip()
    if len(t) != 6 or not t.isdigit():
        return None
    year, month = int(t[:4]), int(t[4:])
    if not (1900 <= year <= 2999 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-01"


def _roc_period_to_iso(text):
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
    import re

    m = re.match(r"\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月", text or "")
    if not m:
        return None
    year, month = int(m.group(1)) + 1911, int(m.group(2))
    if not (1900 <= year <= 2999 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-01"


def _ods_rows(raw):
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
    try:
        index = json.loads(_http_post(TPEX_MONTHLY_INDEX_URL, b"type=2").decode("utf-8"))
        rows = index["tables"][0]["data"]
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
            continue
        try:
            out[iso] = float((row[col] or "").replace(",", "").strip())
        except ValueError:
            continue
    return out or None


def fetch_tw_pmi(years_back=20, incremental=True):
    existing = _load_cache("tw_pmi.json") if incremental else None

    try:
        raw = _http_get_with_retry(TW_PMI_CSV_URL, label="臺灣PMI").decode("utf-8-sig")
    except Exception as e:
        print(f"⚠️ 臺灣PMI 重試 3 次仍失敗，未寫入任何檔案（不補假資料）: {e}")
        return None

    cutoff = _years_ago(years_back).isoformat()
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
        "fetched_at": _today().isoformat(),
        "dates": merged["dates"],
        "pmi": merged["pmi"],
        "nmi": merged["nmi"],
    }
    out_path = os.path.join(DATA_DIR, "tw_pmi.json")
    _write_json(out_path, result)
    print(f"✅ 臺灣PMI 更新完成：快取總計 {len(merged['dates'])} 個月，"
          f"最新 {merged['dates'][-1]} PMI={merged['pmi'][-1]} NMI={merged['nmi'][-1]}")
    return result


CBC_M1B_CSV_URL = "https://www.cbc.gov.tw/public/data/OpenData/%E7%B6%93%E7%A0%94%E8%99%95/EF15M01.csv"


def fetch_tw_m1b(years_back=11, incremental=True):
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

    idx_val = _find_col("Ｍ１Ｂ", "原始值")
    idx_yoy = _find_col("Ｍ１Ｂ", "年增率")
    if idx_val is None:
        print(f"⚠️ M1B 在回應裡找不到「Ｍ１Ｂ-原始值」欄位，未寫入任何檔案。"
              f"欄位清單：{header[:5]}...（共 {len(header)} 欄）")
        return None

    cutoff = _years_ago(years_back).isoformat()
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
        "fetched_at": _today().isoformat(),
        "dates": merged["dates"],
        "m1b": merged["m1b"],
        "yoy": merged["yoy"],
    }
    out_path = os.path.join(DATA_DIR, "tw_m1b.json")
    _write_json(out_path, result)
    print(f"✅ M1B 更新完成：快取總計 {len(merged['dates'])} 個月，"
          f"最新 {merged['dates'][-1]} = {merged['m1b'][-1]:,.0f} 百萬元（年增 {merged['yoy'][-1]}%）")
    return result


FSC_MARKET_CAP_URL = "https://stat.fsc.gov.tw/api/v1/public/datasets/11138/export"


def _fetch_fsc_market_cap():
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

    months = sorted(set(listed) & set(otc))
    if not months:
        print("⚠️ 上市櫃總市值：兩個來源沒有共同月份，保留既有快取不動。")
        SOFT_FAILURES.append("上市櫃總市值（兩來源無交集，沿用既有快取）")
        return existing

    out_dates = months
    out_cap = [listed[m] + otc[m] for m in months]

    if months:
        lo, hi = months[0], months[-1]
        skipped = sorted((set(listed) ^ set(otc)) & {
            m for m in (set(listed) | set(otc)) if lo <= m <= hi})
    else:
        skipped = []
    if skipped:
        print(f"⚠️ 上市櫃總市值：{len(skipped)} 個月只有單邊有資料，不計入合計："
              f"{skipped}（上市缺 {[m for m in skipped if m not in listed]}、"
              f"上櫃缺 {[m for m in skipped if m not in otc]}）")

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
        "fetched_at": _today().isoformat(),
        "latest_source_month": out_dates[-1],
        "skipped_months": skipped,
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
    try:
        y, m, _ = iso_month.split("-")
        today = _today()
        return (today.year - int(y)) * 12 + (today.month - int(m))
    except (ValueError, AttributeError):
        return None


def compute_tw_marketcap_m1b_ratio():
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
        "source": "自行計算：上市櫃總市值（上市 央行EG27M01＋上櫃 櫃買中心，證期局 t49 僅供對帳）÷ M1B（央行EF15M01），兩者皆為新臺幣百萬元",
        "fetched_at": _today().isoformat(),
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


def fetch_index(symbol, key, name="", years_back=5, incremental=True):
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

    if _stalled(f"{name or symbol}", existing, merged):
        return None

    result = {
        "source": f"Yahoo Finance Chart API ({symbol})",
        "symbol": symbol,
        "name": label,
        "fetched_at": _today().isoformat(),
        "dates": merged["dates"],
        "close": merged["close"],
    }
    out_path = os.path.join(DATA_DIR, f"index_{key}.json")
    _write_json(out_path, result)
    print(f"✅ {label} 更新完成：本次新增 {max(new_count,0)} 筆，快取總計 {len(merged['dates'])} 個真實交易日")
    return result




if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="抓取市場資料。個股清單讀自 config.json，改設定檔即可增刪個股，不用動這支程式。"
    )
    parser.add_argument("--include-hidden", action="store_true",
                        help="連 config.json 中 enabled=false 的隱藏個股也一併更新股價快取")
    parser.add_argument("--only", metavar="KEY", default="",
                        help="只更新這一檔個股的股價快取（檔名代號或股票代號），總經與指數全部略過")
    args = parser.parse_args()

    if args.only:
        target = args.only.strip()
        wanted = [s for s in load_jp_stocks(include_disabled=True)
                  if s["key"] == target or s["code"].upper() == target.upper()]
        if not wanted:
            print(f"❌ config.json 裡找不到「{target}」")
            sys.exit(1)
        s = wanted[0]
        print(f"只更新 {s['name']}（{s['code']}）的股價快取。")
        if fetch_jp_stock(s["code"], s["key"], name=s["name"]) is None:
            print(f"❌ {s['name']} 沒抓到，既有快取維持原狀。")
            sys.exit(2)
        print("✅ 完成。")
        sys.exit(0)

    failures = []

    def _run(label, fn, *a, **kw):
        try:
            result = fn(*a, **kw)
        except CacheUnreadable as e:
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
        _run(f"{series['name']}({series['id']})", fetch_fred_series,
             series["id"], name=series["name"],
             years_back=series.get("years_back", 25),
             cache_name=series.get("cache"))
    _run("密大消費者信心（官網）", fetch_michigan_official)

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
