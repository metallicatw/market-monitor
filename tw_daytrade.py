# -*- coding: utf-8 -*-
"""台股當沖比觀測：證交所 TWTB4U（上市）＋櫃買中心 intraday/stat（上櫃）的「當日沖銷交易統計」。

當沖比（成交值）＝ 當沖買進成交金額 ÷ 市場成交金額（買賣平均）
    官方公布的「占市場比重」就是這個定義（櫃買附註：總買進(賣出)成交金額 ÷（整體市場買進＋賣出）÷ 2）。
    上市＋上櫃合併時，用兩邊的買進金額與各自比重換算回市場總值再加權：
        合併當沖比 ＝ Σ 當沖買進金額 ÷ Σ（當沖買進金額 ÷ 該市場比重）
當沖比（成交量）＝ 當沖成交股數 ÷ 市場成交股數，另外保留供參考（低價股多時會被放大）。

為什麼要看
    當沖是「不留倉」的短線資金。比重越高，代表市場成交越多是投機性的日內來回，而不是願意持有的資金；
    多頭末段常見當沖比衝高、融資同步創高（散戶槓桿＋投機），一旦反轉，賣壓會被放大（人踩人）。
    當沖比單獨看意義有限，要和融資餘額、成交值、指數位置一起看：
        • 指數創高＋當沖比走高＋融資增加 → 投機過熱（警戒）
        • 指數下跌＋當沖比走高 → 恐慌下的短線換手、波動放大
        • 指數盤整＋當沖比回落＋融資減少 → 籌碼沉澱（落底條件之一）

判讀區間（成交值口徑；2014 年現股當沖開放、2017 年降稅後的常態大約 20%～35%，依近 400 個交易日分布再校準）
    < 25%   冷清：投機資金退場，留意是否量縮築底
    25～35% 常態
    35～45% 偏熱：短線資金比重高，波動放大
    ≥ 45%   過熱：投機為主，搭配融資創高時是位階過高的警訊
    個股：當沖比 ≥ 50% 屬「當沖股」，≥ 60%～80% 且股本小（< 3 億元）時暴漲暴跌、部位難以放大。

同一次請求也帶回「個股當沖成交股數」：存最近 20 個交易日（tw_daytrade_stocks.json），
金股道的〈估值決策〉拿去除以自己已有的個股成交量算個股當沖比——不再另外抓。

禮貌：同一個網站兩次請求至少隔 3.5 秒；一趟最多補固定天數，被擋就停、下次續補。
"""
from __future__ import annotations

import json
import os
from datetime import date

from tw_margin import Blocked, Net, _num

FILE = "tw_daytrade.json"
STOCK_FILE = "tw_daytrade_stocks.json"
TWSE = "https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U?date={ymd}&selectType=All&response=json"
TPEX = "https://www.tpex.org.tw/www/zh-tw/intraday/stat?date={y}/{m:02d}/{d:02d}&type=Daily&response=json"
PAGE_TWSE = "https://www.twse.com.tw/zh/trading/day-trading/twtb4u.html"
PAGE_TPEX = "https://www.tpex.org.tw/zh-tw/mainboard/trading/intraday/statistics.html"
FIELDS = ("twse_sh", "twse_sh_pct", "twse_buy", "twse_buy_pct", "twse_sell", "twse_sell_pct",
          "tpex_sh", "tpex_sh_pct", "tpex_buy", "tpex_buy_pct", "tpex_sell", "tpex_sell_pct", "ratio", "ratio_sh")
KEEP_STOCK_DAYS = 20

ZONES = ((25, "冷清", "投機資金退場；搭配量縮、融資減少時是築底條件之一"),
         (35, "常態", "短線資金比重正常"),
         (45, "偏熱", "短線資金比重高，波動放大；留意融資是否同步增加"),
         (999, "過熱", "投機為主；搭配融資創高、指數創高時是位階過高的警訊"))


def zone(v: float | None) -> tuple[str, str] | None:
    if v is None:
        return None
    for top, name, why in ZONES:
        if v < top:
            return name, why
    return None


def _pct(s) -> float | None:
    return _num(str(s if s is not None else "").replace("%", ""))


def parse(payload: dict) -> dict | None:
    """官方「當日沖銷交易統計資訊」第一張表 → {sh, sh_pct, buy, buy_pct, sell, sell_pct, stocks: {代號: 當沖股數}}。"""
    if not isinstance(payload, dict):
        return None
    tables = payload.get("tables") or []
    if not tables:
        return None
    head = tables[0]
    rows = head.get("data") or []
    if not rows or len(rows[0]) < 6:
        return None
    r = rows[0]
    out = {"sh": _num(r[0]), "sh_pct": _pct(r[1]), "buy": _num(r[2]), "buy_pct": _pct(r[3]),
           "sell": _num(r[4]), "sell_pct": _pct(r[5]), "stocks": {}}
    if out["buy"] is None or not out["buy_pct"]:
        return None
    for t in tables[1:]:
        f = [str(x).strip() for x in t.get("fields") or []]
        if "證券代號" in f and any("成交股數" in x for x in f):
            a = f.index("證券代號")
            b = next(i for i, x in enumerate(f) if "成交股數" in x)
            for row in t.get("data") or []:
                if len(row) > b and (v := _num(row[b])) is not None:
                    out["stocks"][str(row[a]).strip()] = v
    return out


def combine(tw: dict | None, tp: dict | None) -> tuple[float | None, float | None]:
    """合併上市＋上櫃的當沖比（成交值、成交量）。"""
    parts = [x for x in (tw, tp) if x and x.get("buy") and x.get("buy_pct")]
    if not parts:
        return None, None
    buy = sum(x["buy"] for x in parts)
    mkt = sum(x["buy"] / (x["buy_pct"] / 100) for x in parts)
    ratio = round(buy / mkt * 100, 2) if mkt else None
    sp = [x for x in parts if x.get("sh") and x.get("sh_pct")]
    ratio_sh = (round(sum(x["sh"] for x in sp) / sum(x["sh"] / (x["sh_pct"] / 100) for x in sp) * 100, 2)
                if sp else None)
    return ratio, ratio_sh


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: str, doc: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def fetch(data_dir: str, *, calendar: list[str], today: date, max_days: int = 40, window: int = 400,
          net: Net | None = None, log=print) -> dict:
    """依加權指數交易日曆補當沖統計：新的先補，再往回補到 window 個交易日。"""
    net = net or Net()
    path = os.path.join(data_dir, FILE)
    spath = os.path.join(data_dir, STOCK_FILE)
    old = _load(path)
    rows = {d: {k: (old.get(k) or [None] * len(old.get("dates") or []))[i] for k in FIELDS}
            for i, d in enumerate(old.get("dates") or [])}
    sold = _load(spath)
    sdays: list[str] = list(sold.get("dates") or [])
    sstocks: dict[str, list] = {c: list(v.get("dt") or []) for c, v in (sold.get("stocks") or {}).items()}
    cal = sorted(d for d in calendar if d <= today.isoformat())[-window:]
    todo = [d for d in reversed(cal) if (rows.get(d) or {}).get("ratio") is None]
    stats = {"days": 0, "blocked": []}
    fresh_stocks: dict[str, dict[str, float]] = {}
    for d in todo[:max_days]:
        if len(net.blocked) >= 2:
            break
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        tw = tp = None
        try:
            tw = parse(net.json(TWSE.format(ymd=d.replace("-", ""))) or {})
        except Blocked as e:
            stats["blocked"].append(str(e))
        try:
            tp = parse(net.json(TPEX.format(y=y, m=m, d=dd)) or {})
        except Blocked as e:
            stats["blocked"].append(str(e))
        if not tw and not tp:
            continue
        r = rows.setdefault(d, dict.fromkeys(FIELDS))
        for mk, x in (("twse", tw), ("tpex", tp)):
            if x:
                for k in ("sh", "sh_pct", "buy", "buy_pct", "sell", "sell_pct"):
                    r[f"{mk}_{k}"] = x[k]
        if tw and tp:                               # 兩邊都有才算合併比（只有一邊的會被下一趟補齊）
            r["ratio"], r["ratio_sh"] = combine(tw, tp)
        if d in cal[-KEEP_STOCK_DAYS:]:
            fresh_stocks[d] = {**(tw or {}).get("stocks", {}), **(tp or {}).get("stocks", {})}
        stats["days"] += 1
    dates = sorted(rows)
    doc = {"source": "證交所 TWTB4U／櫃買中心 當日沖銷交易統計", "unit": "金額：元；股數：股；比重：%",
           "fetched_at": today.isoformat(), "page_twse": PAGE_TWSE, "page_tpex": PAGE_TPEX, "dates": dates}
    for k in FIELDS:
        doc[k] = [rows[d].get(k) for d in dates]
    _write(path, doc)
    if fresh_stocks:                                # 個股：最近 20 個交易日的當沖股數（對齊日期）
        old_map = {d: {c: v[i] for c, v in sstocks.items() if i < len(v) and v[i] is not None}
                   for i, d in enumerate(sdays)}
        old_map.update(fresh_stocks)
        keep = sorted(old_map)[-KEEP_STOCK_DAYS:]
        codes = sorted({c for d in keep for c in old_map[d]})
        sdoc = {"source": doc["source"], "unit": "當沖成交股數（股）", "dates": keep,
                "stocks": {c: {"dt": [old_map[d].get(c) for d in keep]} for c in codes}}
        _write(spath, sdoc)
    last = next((rows[d]["ratio"] for d in reversed(dates) if rows[d].get("ratio") is not None), None)
    log(f"✅ 當沖比：這一趟補 {stats['days']} 天，連線 {net.requests} 次"
        + (f"；最新 {last:.2f}%" if last is not None else "")
        + (f"；{stats['blocked'][0]}" if stats["blocked"] else ""))
    return stats


def analyze(doc: dict | None, taiex: dict | None = None, margin: dict | None = None) -> dict | None:
    """近 20 日平均、百分位、與指數／融資的搭配判讀。"""
    if not doc or not doc.get("dates"):
        return None
    pairs = [(d, v) for d, v in zip(doc["dates"], doc.get("ratio") or [], strict=False) if v is not None]
    if not pairs:
        return None
    dates, vals = [p[0] for p in pairs], [p[1] for p in pairs]
    last = vals[-1]
    ma20 = sum(vals[-20:]) / len(vals[-20:])
    w = vals[-400:]
    pct = round(sum(1 for v in w if v < last) / len(w) * 100)
    z = zone(ma20)
    idx = dict(zip((taiex or {}).get("dates") or [], (taiex or {}).get("close") or [], strict=False))
    i0 = idx.get(dates[-1])
    i20 = idx.get(dates[-21]) if len(dates) > 20 else None
    idx20 = (i0 / i20 - 1) * 100 if i0 and i20 else None
    tot = {}
    if margin and margin.get("dates"):
        for d, a, b in zip(margin["dates"], margin.get("twse_amt") or [], margin.get("tpex_amt") or [], strict=False):
            if a is not None and b is not None:
                tot[d] = a + b
    m0 = tot.get(dates[-1])
    m20 = tot.get(dates[-21]) if len(dates) > 20 else None
    mg20 = (m0 / m20 - 1) * 100 if m0 and m20 else None
    combo = None
    if idx20 is not None and mg20 is not None:
        hot, up = ma20 >= 35, idx20 > 0
        if hot and up and mg20 > 0:
            combo = ("警戒", "指數上漲＋當沖偏熱＋融資增加：投機過熱")
        elif hot and not up:
            combo = ("波動放大", "指數下跌＋當沖偏熱：恐慌下的短線換手")
        elif ma20 < 30 and mg20 < 0 and abs(idx20) < 5:
            combo = ("沉澱", "指數盤整＋當沖回落＋融資減少：籌碼沉澱")
        else:
            combo = ("中性", "沒有明顯的投機或沉澱訊號")
    return {"dates": dates, "ratio": vals, "ratio_sh": [v for v in doc.get("ratio_sh") or [] if v is not None],
            "last": last, "ma20": round(ma20, 2), "pct": pct, "zone": z, "idx20": idx20, "mg20": mg20,
            "combo": combo, "day": dates[-1], "n": len(vals)}


def alerts(a: dict | None) -> list[tuple[str, str]]:
    if not a or not a.get("zone"):
        return []
    if a["ma20"] >= 45:
        return [("warn", f"當沖比過熱：近 20 日平均 {a['ma20']:.1f}%（≥ 45%）")]
    if a["ma20"] < 25:
        return [("buy", f"當沖比冷清：近 20 日平均 {a['ma20']:.1f}%（< 25%），投機資金退場")]
    return []
