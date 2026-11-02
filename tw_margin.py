# -*- coding: utf-8 -*-
"""台股融資餘額觀測：抓證交所／櫃買中心的信用交易資料，算出水位、速度、背離與融資維持率（估算），
判斷「過熱警戒／去槓桿中／籌碼清洗（留意落底）／中性」。

為什麼上市、上櫃要加起來看
    融資是散戶的槓桿。上市（集中市場）是新聞最常引用的數字，但上櫃的散戶比重更高、槓桿更早出事
    （上櫃融資成數 5 成、上市 6 成，跌到追繳線的距離上櫃約 35%、上市約 22%）。判斷「整體散戶槓桿」
    要看上市＋上櫃的融資金額合計；上櫃占比升高本身就是投機升溫的訊號，所以兩邊也分開列。
    一律看「金額（億元）」，不看「張數」：張數會被股價高低扭曲（一張台積電和一張雞蛋水餃股差上百倍）。

資料（全部官方、公開）
    證交所 MI_MARGN（selectType=MS 彙總、ALL 個股）、證交所收盤（openapi STOCK_DAY_ALL 只有最新一天；
    歷史用 MI_INDEX）、櫃買中心融資融券餘額與每日收盤行情。
    證交所附註：當天晚上公布的「今日餘額」之後還會調帳，以隔天表上的「前日餘額」為準——所以抓第 d 天時，
    同時用它的「前日餘額」改正前一個交易日（也因此回補歷史時只要每隔一天抓一次）。

融資維持率（估算）＝ Σ（個股融資餘額張數 × 1000 × 收盤價）÷ 融資金額 × 100%
    只算融資部位。交叉驗證：2026-07-29 上櫃算出 150.0%，凱基證券同日估算 149.97%；2026-10-30 合計 170.6%，
    證交所公布的整戶擔保維持率（另計其他擔保品）同期約 175%。CMoney 的估算系統性偏低約 20 個百分點
    （同日上櫃 126.8%），所以網路上「140% 以下恐慌」的說法是用那一套，不能直接套在這裡。
    門檻依 2026-07 斷頭潮實測校準：≤155% 恐慌（追繳／斷頭潮）、≤162% 警戒、≥180% 偏高（樂觀）；
    補滿 400 個交易日（涵蓋 2025-04 關稅股災）之後再依實際分布檢視。

禮貌：同一個網站兩次請求至少隔 3.5 秒，一趟最多補固定天數；證交所回「因為安全性考量…」或斷線，
整趟停止連證交所（不繞過），進度存檔，下一趟接著補。
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import date

FILE = "tw_margin.json"
TWSE_MS = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ymd}&selectType=MS&response=json"
TWSE_ALL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ymd}&selectType=ALL&response=json"
TWSE_CLOSE = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json"
TWSE_CLOSE_TODAY = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_BAL = "https://www.tpex.org.tw/www/zh-tw/margin/balance?date={y}%2F{m:02d}%2F{d:02d}&id=&response=json"
TPEX_CLOSE = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={y}%2F{m:02d}%2F{d:02d}&type=EW&response=json"
PAGE_TWSE = "https://www.twse.com.tw/zh/trading/margin/mi-margn.html"
PAGE_TPEX = "https://www.tpex.org.tw/zh-tw/mainboard/trading/margin-trading/transactions.html"
UA = "Mozilla/5.0 (compatible; MarketMonitorBot/1.0)"
GAP = 3.5
FIELDS = ("twse_amt", "tpex_amt", "twse_lots", "tpex_lots", "twse_short", "tpex_short")
MR_FIELDS = ("mr_twse", "mr_tpex", "mr_total")
ALL_FIELDS = FIELDS + MR_FIELDS + ("final", "twse_final", "tpex_final")


class Blocked(Exception):
    pass


# ── 解析 ───────────────────────────────────────────────────────────────


def _num(s):
    t = str(s if s is not None else "").replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def parse_twse_ms(payload: dict) -> dict | None:
    """證交所彙總表 → {today: {...}, prev: {...}}；融資金額單位轉成億元。"""
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return None
    for t in payload.get("tables") or []:
        rows = {str(r[0]).strip(): r for r in t.get("data") or [] if r}
        lots, short, amt = rows.get("融資(交易單位)"), rows.get("融券(交易單位)"), rows.get("融資金額(仟元)")
        if lots and amt:
            def pick(i):
                return {"amt": _num(amt[i]) / 1e5 if _num(amt[i]) is not None else None,
                        "lots": _num(lots[i]), "short": _num(short[i]) if short else None}
            return {"prev": pick(4), "today": pick(5)}
    return None


def parse_twse_all(payload: dict) -> dict[str, float]:
    """證交所個股表 → {代號: 融資今日餘額（張）}。"""
    for t in (payload or {}).get("tables") or []:
        f = [str(x).strip() for x in t.get("fields") or []]
        if f[:1] == ["代號"] and "今日餘額" in f:
            i = f.index("今日餘額")
            return {str(r[0]).strip(): v for r in t.get("data") or [] if (v := _num(r[i])) is not None}
    return {}


def parse_tpex_bal(payload: dict) -> dict | None:
    """櫃買融資融券餘額 → {today, prev, lots: {代號: 資餘額}}。"""
    tables = (payload or {}).get("tables") or []
    if not tables:
        return None
    t = tables[0]
    f = [str(x).strip() for x in t.get("fields") or []]
    summ = {str(r[1]).strip(): r for r in t.get("summary") or [] if len(r) > 6}
    tot, money = summ.get("合計(張)"), summ.get("融資金(仟元)")
    if not tot or not money or "資餘額" not in f:
        return None
    i_now, i_prev = f.index("資餘額"), 2
    i_short_now = f.index("券餘額") if "券餘額" in f else 14
    i_short_prev = f.index("前券餘額(張)") if "前券餘額(張)" in f else 10
    lots = {str(r[0]).strip(): v for r in t.get("data") or [] if (v := _num(r[i_now])) is not None}

    def amt(i):
        v = _num(money[i])
        return v / 1e5 if v is not None else None
    return {"today": {"amt": amt(i_now), "lots": _num(tot[i_now]), "short": _num(tot[i_short_now])},
            "prev": {"amt": amt(i_prev), "lots": _num(tot[i_prev]), "short": _num(tot[i_short_prev])},
            "lots": lots}


def parse_twse_close(payload: dict) -> dict[str, float]:
    for t in (payload or {}).get("tables") or []:
        f = [str(x).strip() for x in t.get("fields") or []]
        if "證券代號" in f and "收盤價" in f:
            a, b = f.index("證券代號"), f.index("收盤價")
            return {str(r[a]).strip(): v for r in t.get("data") or [] if (v := _num(r[b]))}
    return {}


def parse_twse_openapi(rows, day: date) -> dict[str, float]:
    """openapi 只有最新一天：日期對得上才用。"""
    if not isinstance(rows, list) or not rows:
        return {}
    roc = f"{day.year - 1911}{day.month:02d}{day.day:02d}"
    if str(rows[0].get("Date", "")).strip() != roc:
        return {}
    return {str(r.get("Code", "")).strip(): v for r in rows if (v := _num(r.get("ClosingPrice")))}


def parse_tpex_close(payload: dict) -> dict[str, float]:
    for t in (payload or {}).get("tables") or []:
        f = [str(x).strip() for x in t.get("fields") or []]
        if f[:1] == ["代號"] and any(x.startswith("收盤") for x in f):
            b = next(i for i, x in enumerate(f) if x.startswith("收盤"))
            return {str(r[0]).strip(): v for r in t.get("data") or [] if (v := _num(r[b]))}
    return {}


def maintenance(lots: dict[str, float], close: dict[str, float], loan_bil: float | None) -> float | None:
    """融資維持率（估算）＝ 融資股票市值 ÷ 融資金額。收盤價缺的那幾檔不算進分子（通常不到 0.1%）。"""
    if not lots or not close or not loan_bil:
        return None
    covered = sum(v for c, v in lots.items() if c in close)
    if covered < 0.95 * sum(lots.values()):
        return None                       # 收盤價對不上太多檔（日期錯了）：寧可不算
    value = sum(v * 1000 * close[c] for c, v in lots.items() if c in close)
    return round(value / (loan_bil * 1e8) * 100, 1)


# ── 抓取 ───────────────────────────────────────────────────────────────


class Net:
    def __init__(self, get=None, sleep=time.sleep, clock=time.monotonic, gap: float = GAP):
        self._get = get or self._urlopen
        self._sleep, self._clock, self.gap = sleep, clock, gap
        self._last: dict[str, float] = {}
        self.blocked: dict[str, str] = {}
        self.requests = 0

    @staticmethod
    def _urlopen(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=45) as r:  # noqa: S310 - 固定官方網域
            return r.read()

    def json(self, url: str):
        host = url.split("/")[2]
        if host in self.blocked:
            raise Blocked(self.blocked[host])
        last = self._last.get(host)
        if last is not None and self._clock() - last < self.gap:
            self._sleep(self.gap - (self._clock() - last))
        self._last[host] = self._clock()
        self.requests += 1
        try:
            raw = self._get(url)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            self.blocked[host] = f"{host} 連不上或被擋（{type(e).__name__}），這一趟不再連"
            raise Blocked(self.blocked[host]) from e
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if "SECURITY REASONS" in text[:3000] or "因為安全性考量" in text[:3000]:
            self.blocked[host] = f"{host} 因為請求太頻繁暫時擋下，這一趟不再連（下一趟接著補）"
            raise Blocked(self.blocked[host])
        try:
            return json.loads(text)
        except ValueError:
            return None


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _table(doc: dict) -> dict[str, dict]:
    """存檔（欄位陣列）→ {日期: {欄位: 值}}。"""
    out: dict[str, dict] = {}
    for i, d in enumerate(doc.get("dates") or []):
        out[d] = {k: (doc.get(k) or [])[i] if i < len(doc.get(k) or []) else None for k in ALL_FIELDS}
    return out


def _dump(rows: dict[str, dict], meta: dict) -> dict:
    dates = sorted(rows)
    doc = {**meta, "dates": dates}
    for k in ALL_FIELDS:
        doc[k] = [rows[d].get(k) for d in dates]
    return doc


def fetch(data_dir: str, *, calendar: list[str], today: date, max_days: int = 60, mr_days: int = 10,
          mr_window: int = 400, net: Net | None = None, log=print) -> dict:
    """依加權指數的交易日曆補資料：新的先補，再往回補歷史；回傳這一趟的統計。"""
    net = net or Net()
    path = os.path.join(data_dir, FILE)
    old = _load(path)
    rows = _table(old)
    cal = sorted(d for d in calendar if d <= today.isoformat())
    prev_of = {cal[i]: cal[i - 1] for i in range(1, len(cal))}
    stats = {"days": 0, "mr": 0, "requests": 0, "blocked": [], "notes": []}

    fresh = set(cal[-3:])

    def need(d):
        """缺數字就要抓；還沒定案（等隔天表上的「前日餘額」改正）只對最近 3 個交易日重抓——
        回補是隔天抓一次，被抓的那幾天定案要靠下一天的表，而下一天已經有數字、不會再抓；
        那種日子的「今日餘額」跟定案值只差調帳，不值得為它多抓一次（否則每一趟都會重抓同一批）。"""
        r = rows.get(d) or {}
        if r.get("twse_amt") is None or r.get("tpex_amt") is None:
            return True
        return not r.get("final") and d in fresh

    def put(d, market, vals, final):
        r = rows.setdefault(d, dict.fromkeys(ALL_FIELDS))
        if not vals or vals.get("amt") is None:
            return
        if r.get(f"{market}_final") and not final:
            return                                  # 已經是改正過的數字，不用當天的蓋掉
        r[f"{market}_amt"], r[f"{market}_lots"], r[f"{market}_short"] = (
            round(vals["amt"], 2), vals.get("lots"), vals.get("short"))
        if final:
            r[f"{market}_final"] = True
        r["final"] = bool(r.get("twse_final") and r.get("tpex_final"))

    tpex_lots_cache: dict[str, dict] = {}
    twse_lots_cache: dict[str, dict] = {}
    todo = [d for d in reversed(cal) if need(d)]
    done = 0
    for d in todo:
        if done >= max_days:
            break
        if not need(d):
            continue                                  # 剛剛已經從後一天的「前日餘額」補到
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        got = False
        try:
            if "www.twse.com.tw" not in net.blocked:
                ms = parse_twse_ms(net.json(TWSE_MS.format(ymd=d.replace("-", ""))) or {})
                if ms:
                    put(d, "twse", ms["today"], False)
                    if d in prev_of:
                        put(prev_of[d], "twse", ms["prev"], True)
                    got = True
        except Blocked as e:
            stats["blocked"].append(str(e))
        try:
            tp = parse_tpex_bal(net.json(TPEX_BAL.format(y=y, m=m, d=dd)) or {})
            if tp:
                put(d, "tpex", tp["today"], False)
                if d in prev_of:
                    put(prev_of[d], "tpex", tp["prev"], True)
                tpex_lots_cache[d] = tp["lots"]
                got = True
        except Blocked as e:
            stats["blocked"].append(str(e))
        if got:
            done += 1
        if len(net.blocked) >= 2:
            break
    # 融資維持率（估算）：最近 mr_window 個交易日裡還沒有的，一趟補 mr_days 天（新的先）
    recent = [d for d in reversed(cal[-mr_window:]) if (rows.get(d) or {}).get("mr_total") is None
              and (rows.get(d) or {}).get("twse_amt") is not None]
    for d in recent[:mr_days]:
        if len(net.blocked) >= 2:
            break
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        r = rows[d]
        mr_tw = mr_tp = None
        try:
            if "www.tpex.org.tw" not in net.blocked:
                lots = tpex_lots_cache.get(d)
                if lots is None:
                    tp = parse_tpex_bal(net.json(TPEX_BAL.format(y=y, m=m, d=dd)) or {})
                    lots = tp["lots"] if tp else {}
                close = parse_tpex_close(net.json(TPEX_CLOSE.format(y=y, m=m, d=dd)) or {})
                mr_tp = maintenance(lots, close, r.get("tpex_amt"))
        except Blocked as e:
            stats["blocked"].append(str(e))
        try:
            lots = twse_lots_cache.get(d)
            close = {}
            if d == cal[-1]:
                try:
                    close = parse_twse_openapi(net.json(TWSE_CLOSE_TODAY), date(y, m, dd))
                except Blocked as e:
                    stats["blocked"].append(str(e))
            if "www.twse.com.tw" not in net.blocked:
                if lots is None:
                    lots = parse_twse_all(net.json(TWSE_ALL.format(ymd=d.replace("-", ""))) or {})
                if not close:
                    close = parse_twse_close(net.json(TWSE_CLOSE.format(ymd=d.replace("-", ""))) or {})
                mr_tw = maintenance(lots, close, r.get("twse_amt"))
                if lots and not close:
                    stats["notes"].append(f"{d} 上市收盤價讀不到（證交所 MI_INDEX 格式可能改了），上市維持率沒算")
        except Blocked as e:
            stats["blocked"].append(str(e))
        if mr_tw is not None:
            r["mr_twse"] = mr_tw
        if mr_tp is not None:
            r["mr_tpex"] = mr_tp
        if mr_tw is not None and mr_tp is not None and r.get("twse_amt") and r.get("tpex_amt"):
            r["mr_total"] = round((mr_tw * r["twse_amt"] + mr_tp * r["tpex_amt"]) / (r["twse_amt"] + r["tpex_amt"]), 1)
            stats["mr"] += 1
    stats["days"] = done
    stats["requests"] = net.requests
    meta = {"source": "證交所 MI_MARGN／MI_INDEX／openapi STOCK_DAY_ALL；櫃買中心 融資融券餘額／每日收盤行情",
            "unit": "融資金額：億元；張數：張；維持率：%（估算）",
            "fetched_at": today.isoformat(),
            "blocked": sorted(set(stats["blocked"]))[:3]}
    doc = _dump({d: r for d, r in rows.items() if any(r.get(k) is not None for k in FIELDS)}, meta)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, path)
    missing = sum(1 for d in cal if need(d))
    log(f"✅ 融資餘額：這一趟補 {done} 天、維持率 {stats['mr']} 天，連線 {net.requests} 次；"
        f"日曆上還缺 {missing} 天" + (f"；{stats['blocked'][0]}" if stats["blocked"] else "")
        + (f"；⚠️ {stats['notes'][0]}（共 {len(stats['notes'])} 天）" if stats["notes"] else ""))
    stats["missing"] = missing
    return stats


# ── 判讀 ───────────────────────────────────────────────────────────────

DEFAULTS = {
    "margin_mr_panic": 155, "margin_mr_warn": 162, "margin_mr_high": 180, "margin_mr_window": 400,
    "margin_pct_high": 90, "margin_pct_low": 20, "margin_yoy_hot": 40,
    "margin_gap_hot": 5, "margin_m20_hot": 8, "margin_m20_purge": -10, "margin_idx20_purge": -8,
    "margin_idx20_div": -3, "margin_m20_div": 3, "margin_day_drop": 2.0,
}


def _pct_rank(xs: list[float], v: float) -> int | None:
    xs = [x for x in xs if x is not None]
    if len(xs) < 120:
        return None
    return round(sum(1 for x in xs if x < v) / len(xs) * 100)


def _chg(xs: list, i: int, n: int) -> float | None:
    if i - n < 0 or xs[i] is None or xs[i - n] in (None, 0):
        return None
    return (xs[i] / xs[i - n] - 1) * 100


def _state(s: dict, cfg: dict) -> tuple[str, str, list[str]]:
    """依序判斷：籌碼清洗（留意落底）＞ 過熱警戒 ＞ 散戶接刀（背離）＞ 去槓桿 ＞ 法人主導 ＞ 中性。"""
    why: list[str] = []
    mr, m20, i20 = s.get("mr"), s.get("m20"), s.get("idx20")
    if (mr is not None and mr <= cfg["margin_mr_panic"]) or (
            m20 is not None and i20 is not None and m20 <= cfg["margin_m20_purge"] and i20 <= cfg["margin_idx20_purge"]):
        if mr is not None and mr <= cfg["margin_mr_panic"]:
            why.append(f"融資維持率估算 {mr:.1f}% ≤ {cfg['margin_mr_panic']}%（追繳／斷頭潮區）")
        if m20 is not None and m20 <= cfg["margin_m20_purge"]:
            why.append(f"融資 20 日減少 {abs(m20):.1f}%、指數 20 日跌 {abs(i20):.1f}%")
        return "purge", "籌碼清洗中・留意落底", why
    heat = 0
    if s.get("pct") is not None and s["pct"] >= cfg["margin_pct_high"]:
        heat += 1
        why.append(f"融資金額在近 5 年第 {s['pct']} 百分位")
    if s.get("yoy") is not None and s["yoy"] >= cfg["margin_yoy_hot"]:
        heat += 1
        why.append(f"融資年增 {s['yoy']:.0f}%（≥{cfg['margin_yoy_hot']}% 歷史上屬高風險）")
    if m20 is not None and i20 is not None and m20 >= cfg["margin_m20_hot"] and m20 - i20 >= cfg["margin_gap_hot"]:
        heat += 1
        why.append(f"融資 20 日增 {m20:.1f}%，比指數（{i20:+.1f}%）快 {m20 - i20:.1f} 個百分點：散戶追價")
    if s.get("otc_share_chg") is not None and s["otc_share_chg"] >= 2:
        heat += 1
        why.append(f"上櫃融資占比 60 日上升 {s['otc_share_chg']:.1f} 個百分點：投機升溫")
    if mr is not None and mr >= cfg["margin_mr_high"]:
        heat += 1
        why.append(f"融資維持率估算 {mr:.1f}%（帳上獲利豐厚，追高意願強）")
    if heat >= 3:
        return "hot", "過熱警戒", why
    why = [f"過熱跡象（{heat}/5）：{w}" for w in why]   # 沒到警戒，但先列出來
    if m20 is not None and i20 is not None and i20 <= cfg["margin_idx20_div"] and m20 >= cfg["margin_m20_div"]:
        return "catch", "散戶接刀（背離）", why + [f"指數 20 日 {i20:+.1f}%，融資卻增加 {m20:+.1f}%：散戶逢低攤平，籌碼未清"]
    if mr is not None and mr <= cfg["margin_mr_warn"]:
        return "delever", "去槓桿・警戒", why + [f"融資維持率估算 {mr:.1f}%，離 130% 追繳線不遠"]
    if m20 is not None and i20 is not None and m20 <= -5 and i20 < 0:
        return "delever", "去槓桿中", why + [f"融資 20 日減少 {abs(m20):.1f}%"]
    if m20 is not None and i20 is not None and i20 >= 3 and m20 <= i20 / 2:
        return "healthy", "法人主導・融資溫和", why + [f"指數 20 日 {i20:+.1f}%，融資只增 {m20:+.1f}%"]
    return "neutral", "中性", why


STATE_TONE = {"purge": ("buy", "#22d3ee"), "hot": ("warn", "#ef4444"), "catch": ("warn", "#f97316"),
              "delever": ("warn", "#f59e0b"), "healthy": ("info", "#34d399"), "neutral": ("info", "#94a3b8")}


def analyze(margin: dict | None, taiex: dict | None, mcap: dict | None = None, cfg: dict | None = None) -> dict | None:
    if not margin or not margin.get("dates"):
        return None
    cfg = {**DEFAULTS, **(cfg or {})}
    ds = margin["dates"]
    tw, tp = margin.get("twse_amt") or [], margin.get("tpex_amt") or []
    total = [round(a + b, 2) if a is not None and b is not None else None for a, b in zip(tw, tp, strict=False)]
    idx_map = dict(zip((taiex or {}).get("dates") or [], (taiex or {}).get("close") or [], strict=False))
    val_map = dict(zip((taiex or {}).get("dates") or [], (taiex or {}).get("value_twd") or [], strict=False))
    keep = [i for i, v in enumerate(total) if v is not None]
    if not keep:
        return None
    dates = [ds[i] for i in keep]
    tot = [total[i] for i in keep]
    twa, tpa = [tw[i] for i in keep], [tp[i] for i in keep]
    idx = [idx_map.get(d) for d in dates]
    lots = [((margin.get("twse_lots") or [])[i] or 0) + ((margin.get("tpex_lots") or [])[i] or 0) for i in keep]
    short = [((margin.get("twse_short") or [])[i] or 0) + ((margin.get("tpex_short") or [])[i] or 0) for i in keep]
    mr = [(margin.get("mr_total") or [None] * len(ds))[i] for i in keep]
    mr_tw = [(margin.get("mr_twse") or [None] * len(ds))[i] for i in keep]
    mr_tp = [(margin.get("mr_tpex") or [None] * len(ds))[i] for i in keep]
    otc_share = [round(b / t * 100, 2) if t else None for b, t in zip(tpa, tot, strict=False)]
    n = len(tot) - 1
    cap = None
    if mcap and mcap.get("dates"):
        cm = dict(zip(mcap["dates"], mcap.get("market_cap") or [], strict=False))
        month = max((m for m in cm if m[:7] <= dates[-1][:7]), default=None)
        if month and cm[month]:
            cap = {"month": month[:7], "ratio": round(tot[-1] / (cm[month] / 100) * 100, 3)}  # 百萬元→億元
    last_mr = next((v for v in reversed(mr) if v is not None), None)
    last_mr_day = next((dates[i] for i in range(n, -1, -1) if mr[i] is not None), None)
    s = {"date": dates[-1], "total": tot[-1], "twse": twa[-1], "tpex": tpa[-1],
         "d1": round(tot[-1] - tot[-2], 2) if n >= 1 else None, "d1_pct": _chg(tot, n, 1),
         "m20": _chg(tot, n, 20), "idx20": _chg(idx, n, 20) if idx[-1] is not None else None,
         "yoy": _chg(tot, n, 245), "pct": _pct_rank(tot[-1250:], tot[-1]), "otc_share": otc_share[-1],
         "otc_share_chg": (otc_share[-1] - otc_share[-61]) if n >= 60 and otc_share[-61] is not None else None,
         "short_ratio": round(short[-1] / lots[-1] * 100, 2) if lots[-1] else None,
         "value_ratio": round(tot[-1] / (val_map[dates[-1]] / 1e8), 2) if val_map.get(dates[-1]) else None,
         "mr": last_mr if last_mr_day and (len(dates) - 1 - dates.index(last_mr_day)) <= 3 else None,
         "mr_any": last_mr, "mr_day": last_mr_day,
         "mr_twse": next((v for v in reversed(mr_tw) if v is not None), None),
         "mr_tpex": next((v for v in reversed(mr_tp) if v is not None), None),
         "cap": cap, "days": len(tot), "first": dates[0]}
    s["high"] = max(tot[-1250:])
    s["state"], s["label"], s["why"] = _state(s, cfg)
    if s.get("d1_pct") is not None and s["d1_pct"] <= -cfg["margin_day_drop"]:
        s["why"].append(f"單日融資減少 {abs(s['d1']):.0f} 億元（{s['d1_pct']:.1f}%）：追繳或停損賣壓")
    # 歷史驗證：每天都判一次狀態，看各狀態「第一天」之後 20／60 個交易日加權指數的漲跌
    hist = []
    for i in range(60, n + 1):
        si = {"m20": _chg(tot, i, 20), "idx20": _chg(idx, i, 20) if idx[i] is not None else None,
              "yoy": _chg(tot, i, 245), "pct": _pct_rank(tot[max(0, i - 1250):i + 1], tot[i]),
              "otc_share_chg": (otc_share[i] - otc_share[i - 60]) if otc_share[i - 60] is not None else None,
              "mr": mr[i]}
        hist.append((i, _state(si, cfg)[0]))
    episodes: dict[str, list] = {}
    prev = None
    for i, st in hist:
        if st != prev and idx[i]:
            r = {}
            for h in (20, 60):
                if i + h <= n and idx[i + h]:
                    r[h] = round((idx[i + h] / idx[i] - 1) * 100, 2)
            episodes.setdefault(st, []).append({"date": dates[i], **{f"r{h}": v for h, v in r.items()}})
        prev = st
    s["episodes"] = episodes
    series = {"dates": dates, "total": tot, "twse": twa, "tpex": tpa, "idx": idx, "mr": mr,
              "mr_twse": mr_tw, "mr_tpex": mr_tp,
              "m20": [None if (v := _chg(tot, i, 20)) is None else round(v, 2) for i in range(n + 1)],
              "idx20": [None if idx[i] is None or (v := _chg(idx, i, 20)) is None else round(v, 2) for i in range(n + 1)]}
    return {"snap": s, "series": series, "cfg": cfg}


def alerts(a: dict | None) -> list[tuple[str, str]]:
    """給報告頂端的摘要：只在「過熱警戒、散戶接刀、去槓桿警戒、籌碼清洗」時提醒。"""
    if not a:
        return []
    s = a["snap"]
    kind = STATE_TONE.get(s["state"], ("info", ""))[0]
    if kind not in ("warn", "buy"):
        return []
    lead = f"台股融資（上市＋上櫃）{s['total']:,.0f} 億元：{s['label']}"
    return [(kind, lead + ("——" + s["why"][0] if s["why"] else ""))]


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))
