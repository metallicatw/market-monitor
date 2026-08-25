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


def effective_per_buy(stock, thresholds=None):
    """取得某檔個股實際生效的本益比布局門檻：個股自訂優先，沒填就用全域預設。"""
    if thresholds is None:
        thresholds = load_thresholds()
    val = stock.get("per_buy")
    if isinstance(val, (int, float)):
        return val
    return thresholds.get("per_buy_default")
