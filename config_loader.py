# -*- coding: utf-8 -*-
import json
import os
import sys


def _setup_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_console_encoding()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_THRESHOLDS = {
    "taiex_buy": 38000,
    "taiex_volume_buy_bil": 8000,
    "nikkei_buy": 56000,
    "vix_warn": 20,
    "vix_panic": 30,
    "michigan_warn": 60,
    "murata_bb_warn": 1.2,
    "per_buy_default": 20,
    "pmi_neutral": 50,
    "tw_marketcap_m1b_pct_high": 80,
    "tw_marketcap_m1b_pct_low": 20,
    "tw_marketcap_m1b_high": 2.6,
    "tw_marketcap_m1b_low": 1.9,
}

DEFAULT_JP_STOCKS = [
    {"key": "kao", "code": "4452.T", "name": "花王", "enabled": True, "price_buy": 3200, "per_buy": None},
    {"key": "towa", "code": "6315.T", "name": "TOWA CORP", "enabled": True, "price_buy": 2500, "per_buy": None},
    {"key": "ajinomoto", "code": "2802.T", "name": "味之素", "enabled": True, "price_buy": 4700, "per_buy": None},
    {"key": "mizuho", "code": "8411.T", "name": "瑞穗金融集團", "enabled": True, "price_buy": 6000, "per_buy": None},
    {"key": "yaskawa", "code": "6506.T", "name": "安川電機", "enabled": True, "price_buy": 4500, "per_buy": None},
    {"key": "jxadvanced", "code": "5016.T", "name": "JX ADVANCED METALS", "enabled": True, "price_buy": 3500, "per_buy": None},
    {"key": "mitsubishimaterials", "code": "5711.T", "name": "三菱材料", "enabled": True, "price_buy": 4000, "per_buy": None},
    {"key": "hitachi", "code": "6501.T", "name": "日立製作所", "enabled": True, "price_buy": 4800, "per_buy": None},
    {"key": "kawasakiheavy", "code": "7012.T", "name": "川崎重工業", "enabled": True, "price_buy": 2500, "per_buy": None},
    {"key": "organo", "code": "6368.T", "name": "ORGANO CORP", "enabled": True, "price_buy": 15000, "per_buy": None},
]


class ConfigBroken(RuntimeError):
    pass


def _load_raw():
    if not os.path.exists(CONFIG_PATH):
        print(f"⚠️ 找不到 {CONFIG_PATH}，本次使用內建預設設定。")
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigBroken(
            f"config.json 格式錯誤（{e}）。\n"
            "   這次**不產生報告**——退回內建預設清單的話，你追蹤中的個股會從\n"
            "   報告上無聲消失，而頁面上不會有任何一個字說少了東西。\n"
            "   多半是逗號或括號寫錯了，修好再跑一次。"
        ) from e
    except OSError as e:
        raise ConfigBroken(
            f"讀不到 config.json（{e}）。這次不產生報告，理由同上。"
        ) from e


def _config_broken_excepthook(kind, value, tb):
    if not isinstance(value, ConfigBroken):
        return _PREVIOUS_EXCEPTHOOK(kind, value, tb)
    print(f"\n❌ {value}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        head = str(value).splitlines()[0]
        print(f"::error title=設定檔壞了::{head}", file=sys.stderr)
    raise SystemExit(1)


_PREVIOUS_EXCEPTHOOK = sys.excepthook
sys.excepthook = _config_broken_excepthook


def load_thresholds():
    raw = _load_raw().get("thresholds", {})
    result = dict(DEFAULT_THRESHOLDS)
    for k, v in raw.items():
        if k in result and isinstance(v, (int, float)):
            result[k] = v
        elif k in result:
            print(f"⚠️ thresholds.{k} 必須是數字（目前是 {v!r}），本項改用預設值 {result[k]}。")
    return result


def load_jp_stocks(include_disabled=False):
    raw = _load_raw().get("jp_stocks")
    if not isinstance(raw, list) or not raw:
        stocks = [dict(s) for s in DEFAULT_JP_STOCKS]
    else:
        stocks, seen_keys = [], set()
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                print(f"⚠️ jp_stocks 第 {i+1} 筆不是有效設定區塊，已略過。")
                continue
            key = item.get("key")
            code = item.get("code")
            if not key or not code:
                print(f"⚠️ jp_stocks 第 {i+1} 筆缺少 key 或 code，已略過。")
                continue
            if key in seen_keys:
                print(f"⚠️ jp_stocks 出現重複的 key「{key}」，只保留第一筆，後面的已略過。")
                continue
            seen_keys.add(key)
            stocks.append({
                "key": key,
                "code": code,
                "name": item.get("name") or key,
                "enabled": bool(item.get("enabled", True)),
                "price_buy": item.get("price_buy"),
                "per_buy": item.get("per_buy"),
            })

    if include_disabled:
        return stocks
    return [s for s in stocks if s["enabled"]]


DEFAULT_US_INDICES = [
    {"key": "dji", "symbol": "^DJI", "name": "道瓊工業指數", "enabled": True},
    {"key": "sp500", "symbol": "^GSPC", "name": "S&P 500", "enabled": True},
    {"key": "nasdaq", "symbol": "^IXIC", "name": "NASDAQ 綜合指數", "enabled": True},
]

DEFAULT_US_FRED_SERIES = [
    {"id": "GDPC1", "name": "實質GDP", "group": "growth"},
    {"id": "RSAFS", "name": "零售銷售", "group": "growth"},
    {"id": "PAYEMS", "name": "非農就業人數", "group": "labor"},
    {"id": "UNRATE", "name": "失業率", "group": "labor"},
    {"id": "ICSA", "name": "每週初請失業金", "group": "labor"},
    {"id": "CPIAUCSL", "name": "CPI", "group": "inflation"},
    {"id": "CPILFESL", "name": "核心CPI", "group": "inflation"},
    {"id": "PCEPILFE", "name": "核心PCE", "group": "inflation"},
    {"id": "PPIACO", "name": "PPI", "group": "inflation"},
    {"id": "HOUST", "name": "新屋開工", "group": "housing_sentiment"},
    {"id": "PERMIT", "name": "營建許可", "group": "housing_sentiment"},
    {"id": "UMCSENT", "name": "密大消費者信心", "group": "housing_sentiment",
     "cache": "michigan.json", "in_group": False},
]

DEFAULT_US_INDICATOR_GROUPS = [
    {"key": "growth", "label": "📈 經濟增長與整體產出"},
    {"key": "labor", "label": "💼 勞動力市場"},
    {"key": "inflation", "label": "🔍 通膨與物價"},
    {"key": "housing_sentiment", "label": "🏠 房地產與信心"},
]


def load_us_indices(include_disabled=False):
    raw = _load_raw().get("us_indices")
    if not isinstance(raw, list) or not raw:
        items = [dict(x) for x in DEFAULT_US_INDICES]
    else:
        items, seen = [], set()
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                print(f"⚠️ us_indices 第 {i+1} 筆不是有效設定區塊，已略過。")
                continue
            key, symbol = item.get("key"), item.get("symbol")
            if not key or not symbol:
                print(f"⚠️ us_indices 第 {i+1} 筆缺少 key 或 symbol，已略過。")
                continue
            if key in seen:
                print(f"⚠️ us_indices 出現重複的 key「{key}」，只保留第一筆。")
                continue
            seen.add(key)
            items.append({
                "key": key,
                "symbol": symbol,
                "name": item.get("name") or symbol,
                "enabled": bool(item.get("enabled", True)),
            })
    if include_disabled:
        return items
    return [x for x in items if x.get("enabled", True)]


def load_fred_series(include_disabled=False):
    raw = _load_raw().get("us_fred_series")
    if not isinstance(raw, list) or not raw:
        items = [dict(x) for x in DEFAULT_US_FRED_SERIES]
    else:
        items, seen = [], set()
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                print(f"⚠️ us_fred_series 第 {i+1} 筆不是有效設定區塊，已略過。")
                continue
            sid = (item.get("id") or "").strip()
            if not sid:
                print(f"⚠️ us_fred_series 第 {i+1} 筆缺少 id（FRED 序列代號），已略過。")
                continue
            if sid in seen:
                print(f"⚠️ us_fred_series 出現重複的 id「{sid}」，只保留第一筆。")
                continue
            seen.add(sid)
            freq = item.get("freq") or ""
            items.append({
                "id": sid,
                "name": item.get("name") or sid,
                "group": item.get("group") or "other",
                "unit": item.get("unit") or "",
                "freq": freq,
                "cache": item.get("cache"),
                "years_back": _fred_years_back(item, freq),
                "enabled": bool(item.get("enabled", True)),
                "in_group": bool(item.get("in_group", True)),
            })
    for x in items:
        if not x.get("years_back"):
            x["years_back"] = _fred_years_back(x, x.get("freq", ""))
        x["in_group"] = bool(x.get("in_group", True))
    if include_disabled:
        return items
    return [x for x in items if x.get("enabled", True)]


_FRED_YEARS_BY_FREQ = {"週": 15, "月": 25, "季": 25}
_FRED_YEARS_DEFAULT = 25


def _fred_years_back(item, freq):
    raw = item.get("years_back")
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    return _FRED_YEARS_BY_FREQ.get(freq, _FRED_YEARS_DEFAULT)


def load_us_indicator_groups():
    raw = _load_raw().get("us_indicator_groups")
    if not isinstance(raw, list) or not raw:
        return [dict(x) for x in DEFAULT_US_INDICATOR_GROUPS]
    groups = []
    for item in raw:
        if isinstance(item, dict) and item.get("key"):
            groups.append({"key": item["key"], "label": item.get("label") or item["key"]})
    return groups or [dict(x) for x in DEFAULT_US_INDICATOR_GROUPS]


def effective_per_buy(stock, thresholds=None):
    if thresholds is None:
        thresholds = load_thresholds()
    val = stock.get("per_buy")
    if isinstance(val, (int, float)):
        return val
    return thresholds.get("per_buy_default")
