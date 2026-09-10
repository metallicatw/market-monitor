# -*- coding: utf-8 -*-
"""
共用設定載入器。

fetch_market_data.py 與 generate_report_local.py 都從這裡取得設定，
確保兩支程式看到的個股清單與門檻永遠一致。

設計原則：
1. config.json 不存在或格式錯誤時，一律退回內建預設值，並印出警告，
   絕不讓整個流程掛掉（監控報告的可用性優先）。
2. 缺欄位就補預設值，不強制使用者每次都要寫完整。
3. 對明顯的設定錯誤（key 重複、缺必填欄位）主動示警，避免默默產生錯誤報告。
"""
import json
import os
import sys


def _setup_console_encoding():
    """讓中文與圖示在 Windows 主控台也能正常輸出。

    Windows 的預設主控台編碼是地區設定（繁體中文是 cp950），遇到 emoji 會直接
    丟出 UnicodeEncodeError 讓整支程式中斷。這裡把標準輸出改成 UTF-8，
    並在真的無法編碼時以替代字元代過，不讓顯示問題影響到實際工作。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # 顯示不了就算了，不能因為這種事中斷資料更新


_setup_console_encoding()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# ---------------------------------------------------------------------------
# 內建預設值：config.json 不存在時使用，也是各欄位缺漏時的 fallback
# ---------------------------------------------------------------------------
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
    "tw_marketcap_m1b_high": 4.5,
    "tw_marketcap_m1b_low": 2.5,
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


def _load_raw():
    if not os.path.exists(CONFIG_PATH):
        print(f"⚠️ 找不到 {CONFIG_PATH}，本次使用內建預設設定。")
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"⚠️ config.json 格式錯誤（{e}），本次使用內建預設設定。請檢查逗號/括號是否寫錯。")
        return {}
    except Exception as e:
        print(f"⚠️ 讀取 config.json 失敗（{e}），本次使用內建預設設定。")
        return {}


def load_thresholds():
    """回傳完整門檻設定，缺的欄位自動補預設值。"""
    raw = _load_raw().get("thresholds", {})
    result = dict(DEFAULT_THRESHOLDS)
    for k, v in raw.items():
        if k in result and isinstance(v, (int, float)):
            result[k] = v
        elif k in result:
            print(f"⚠️ thresholds.{k} 必須是數字（目前是 {v!r}），本項改用預設值 {result[k]}。")
    return result


def load_jp_stocks(include_disabled=False):
    """
    回傳個股清單（list of dict），順序即為報告顯示順序。

    include_disabled=False（預設）只回傳 enabled=true 的個股；
    設為 True 則連隱藏的一併回傳（例如想順便更新隱藏個股的股價快取時使用）。
    """
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


# ---------------------------------------------------------------------------
# 美股欄設定：三大指數 與 FRED 經濟指標
# ---------------------------------------------------------------------------
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
    {"id": "UMCSENT", "name": "密大消費者信心", "group": "housing_sentiment", "cache": "michigan.json"},
]

DEFAULT_US_INDICATOR_GROUPS = [
    {"key": "growth", "label": "📈 經濟增長與整體產出"},
    {"key": "labor", "label": "💼 勞動力市場"},
    {"key": "inflation", "label": "🔍 通膨與物價"},
    {"key": "housing_sentiment", "label": "🏠 房地產與信心"},
]


def load_us_indices(include_disabled=False):
    """回傳美股指數清單。改 config.json 的 us_indices 即可增刪，不用動程式。"""
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
    """
    回傳要抓的 FRED 序列清單。

    每筆至少要有 id（FRED 序列代號）；name / group / unit / freq 是給報告用的，
    cache 可覆寫存檔檔名（UMCSENT 沿用既有的 michigan.json 就是靠這個）。

    ⚠️ ISM 製造業/服務業 PMI 不在這裡，因為沒有免費官方源 ——
       FRED 的 NAPM 序列在 2016 年因授權問題下架，實測回 404。
    """
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
            })
    # 走內建預設清單那條路的時候，上面那個迴圈沒跑過，這裡補上。
    for x in items:
        if not x.get("years_back"):
            x["years_back"] = _fred_years_back(x, x.get("freq", ""))
    if include_disabled:
        return items
    return [x for x in items if x.get("enabled", True)]


#: 每個頻率預設抓幾年。FRED 的 CSV 端點給完整歷史、不收錢也不需要 key，所以
#: 視窗短不是為了省成本，只是預設值一直沒有人回頭調過。
#:
#: 月頻與季頻放 25 年：這一組指標的用途是「認出現在在循環的哪個位置」，而一個
#: 完整的景氣循環動輒七到十年。5 年連一輪都蓋不住，於是每一條線看起來都像在
#: 單調上升——那不是資料的性質，是視窗太短造成的錯覺。
#:
#: 週頻（初請失業金）放 15 年：它一年 52 個點，25 年會讓檔案胖到 30 KB 以上，
#: 圖上也會糊成一團。15 年已經蓋得住 2008 與 2020 兩次尖峰，而那正是這條線
#: 最有參考價值的兩段。
_FRED_YEARS_BY_FREQ = {"週": 15, "月": 25, "季": 25}
_FRED_YEARS_DEFAULT = 25


def _fred_years_back(item, freq):
    """單筆序列要抓幾年：設定裡寫死的優先，否則依頻率取預設。"""
    raw = item.get("years_back")
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    return _FRED_YEARS_BY_FREQ.get(freq, _FRED_YEARS_DEFAULT)


def load_us_indicator_groups():
    """回傳美股指標的分組與顯示標題，順序即報告顯示順序。"""
    raw = _load_raw().get("us_indicator_groups")
    if not isinstance(raw, list) or not raw:
        return [dict(x) for x in DEFAULT_US_INDICATOR_GROUPS]
    groups = []
    for item in raw:
        if isinstance(item, dict) and item.get("key"):
            groups.append({"key": item["key"], "label": item.get("label") or item["key"]})
    return groups or [dict(x) for x in DEFAULT_US_INDICATOR_GROUPS]


def effective_per_buy(stock, thresholds=None):
    """取得某檔個股實際生效的本益比布局門檻：個股自訂優先，沒填就用全域預設。"""
    if thresholds is None:
        thresholds = load_thresholds()
    val = stock.get("per_buy")
    if isinstance(val, (int, float)):
        return val
    return thresholds.get("per_buy_default")
