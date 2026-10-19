import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser

from config_loader import load_jp_stocks

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TAIPEI = timezone(timedelta(hours=8))

LIST_URL = "https://webapi.yanoshin.jp/webapi/tdnet/list/{code}.json?limit=40"
UA = "Mozilla/5.0 (market-monitor; personal use)"

FIELDS = ["revenue_oku_jpy", "business_profit_oku_jpy", "operating_margin_pct",
          "net_income_oku_jpy", "eps_jpy", "bvps_jpy"]

REV_TAGS = ["NetSales", "SalesIFRS", "NetSalesIFRS", "RevenueIFRS", "RevenuesIFRS", "NetSalesUS",
            "OperatingRevenues", "OperatingRevenuesIFRS", "OperatingRevenuesUS", "OrdinaryRevenues",
            "GrossOperatingRevenues", "TotalRevenuesUS", "RevenuesUS"]
PROFIT_TAGS = ["OperatingIncome", "OperatingIncomeIFRS", "OperatingIncomeUS", "OperatingProfitIFRS",
               "OrdinaryIncome", "ProfitBeforeTaxIFRS", "IncomeBeforeIncomeTaxesUS"]
NI_TAGS = ["ProfitAttributableToOwnersOfParent", "ProfitAttributableToOwnersOfParentIFRS",
           "NetIncomeAttributableToShareholdersUS", "NetIncomeAttributableToOwnersOfParentUS",
           "NetIncome", "ProfitIFRS"]
EPS_TAGS = ["NetIncomePerShare", "BasicEarningsPerShareIFRS", "NetIncomePerShareUS",
            "BasicEarningsPerShareUS", "BasicNetIncomePerShareUS"]
EQ_TAGS = ["OwnersEquity", "EquityAttributableToOwnersOfParentIFRS",
           "ShareholdersEquityUS", "EquityAttributableToOwnersOfParentUS"]
BPS_TAGS = ["NetAssetsPerShare", "EquityAttributableToOwnersOfParentPerShareIFRS",
            "ShareholdersEquityPerShareUS"]


def _today():
    return datetime.now(TAIPEI).date()


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class _IX(HTMLParser):
    def __init__(self):
        super().__init__()
        self.facts = []
        self.ctx = {}
        self._stack = []
        self._ctx_id = None
        self._ctx_tag = None
        self._ctx_vals = {}
        self._text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("ix:nonfraction", "ix:nonnumeric"):
            self._stack.append([tag, a, []])
        elif tag == "xbrli:context":
            self._ctx_id = a.get("id")
            self._ctx_vals = {}
        elif self._ctx_id and tag in ("xbrli:startdate", "xbrli:enddate", "xbrli:instant"):
            self._ctx_tag = tag
            self._text = []

    def handle_endtag(self, tag):
        if tag in ("ix:nonfraction", "ix:nonnumeric") and self._stack:
            t, a, txt = self._stack.pop()
            text = "".join(txt).strip()
            for s in self._stack:
                s[2].append(text)
            self.facts.append((t, a, text))
        elif tag == "xbrli:context" and self._ctx_id:
            self.ctx[self._ctx_id] = self._ctx_vals
            self._ctx_id = None
        elif self._ctx_tag and tag == self._ctx_tag:
            self._ctx_vals[tag.split(":")[1]] = "".join(self._text).strip()
            self._ctx_tag = None

    def handle_data(self, data):
        if self._stack:
            self._stack[-1][2].append(data)
        if self._ctx_tag:
            self._text.append(data)


def parse_summary(html_text):
    p = _IX()
    p.feed(html_text)
    values, texts = {}, {}
    for t, a, text in p.facts:
        name = (a.get("name") or "").split(":")[-1]
        ctx = a.get("contextref") or ""
        if t == "ix:nonnumeric":
            texts.setdefault(name, text)
            continue
        if a.get("xsi:nil") == "true" or not text:
            continue
        try:
            v = float(text.replace(",", ""))
        except ValueError:
            continue
        v *= 10 ** int(a.get("scale") or 0)
        if a.get("sign") == "-":
            v = -v
        values[(name, ctx)] = v
    q = next((v for (n, _c), v in values.items() if n == "QuarterlyPeriod"), None)
    period = int(q) if q in (1, 2, 3) else 4
    return {"values": values, "texts": texts, "ctx": p.ctx, "period": period}


def _pick(doc, tags, when, kind):
    p = doc["period"]
    if when == "cur":
        base = f"CurrentAccumulatedQ{p}{kind}" if p < 4 else f"CurrentYear{kind}"
    else:
        base = f"PriorAccumulatedQ{p}{kind}" if p < 4 else f"PriorYear{kind}"
    for scope in ("ConsolidatedMember", "NonConsolidatedMember"):
        ctx = f"{base}_{scope}_ResultMember"
        for tag in tags:
            v = doc["values"].get((tag, ctx))
            if v is not None:
                return tag, v
    return None, None


def _end_date(doc):
    p = doc["period"]
    cid = f"CurrentAccumulatedQ{p}Instant" if p < 4 else "CurrentYearInstant"
    c = doc["ctx"].get(cid) or {}
    return c.get("instant") or c.get("enddate")


def _shares(doc):
    p = doc["period"]
    cid = (f"CurrentAccumulatedQ{p}Instant" if p < 4 else "CurrentYearInstant") + "_NonConsolidatedMember_ResultMember"
    issued = doc["values"].get(("NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock", cid))
    treasury = doc["values"].get(("NumberOfTreasuryStockAtTheEndOfFiscalYear", cid)) or 0
    return issued - treasury if issued else None


def _quarter_label(d, fy_end_month):
    months_after_fy_start = (d.month - fy_end_month - 1) % 12
    q = months_after_fy_start // 3 + 1
    fy = d.year + 1 if d.month > fy_end_month else d.year
    return f"FY{str(fy)[-2:]}Q{q}"


def _close(a, b, n, per=0.011):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(per * n, abs(b) * 0.002)


def _fy_of(label):
    return label.split("Q")[0]


def derive_quarter(d, doc, fy_end_month):
    labels = d.get("fiscal_years") or []
    end = _end_date(doc)
    if not end:
        return None, "XBRL 裡找不到期末日"
    end_d = date.fromisoformat(end)
    label = _quarter_label(end_d, fy_end_month)
    q = int(label.split("Q")[1])
    if q != doc["period"]:
        return None, f"季別對不上（期末 {end} 推算為 Q{q}，XBRL 標 Q{doc['period']}）"
    if label in labels:
        return None, f"{label} 已經在資料裡了"
    ends = d.get("fiscal_year_end_dates") or []
    if ends and end <= ends[-1]:
        return None, f"期末日 {end} 沒有比最後一季 {ends[-1]} 晚"
    fy = _fy_of(label)
    prev_fy = f"FY{int(fy[2:]) - 1:02d}"
    same_fy = [f"{fy}Q{i}" for i in range(1, q)]
    want_prev = f"{fy}Q{q - 1}" if q > 1 else f"{prev_fy}Q4"
    if labels and labels[-1] != want_prev:
        return None, f"中間缺季（資料最後是 {labels[-1]}，這份是 {label}），無法還原單季"
    prior_labels = [f"{prev_fy}Q{i}" for i in range(1, q + 1)]
    if not all(lb in labels for lb in prior_labels):
        return None, f"缺少去年同期（{'、'.join(prior_labels)}），無法交叉核對"

    def stored_sum(field, lbs):
        arr = d.get(field) or []
        vals = [arr[labels.index(lb)] for lb in lbs]
        if any(v is None for v in vals):
            return None
        return sum(vals)

    chosen = {}
    for field, tags, unit in (("revenue_oku_jpy", REV_TAGS, 1e8),
                              ("business_profit_oku_jpy", PROFIT_TAGS, 1e8),
                              ("net_income_oku_jpy", NI_TAGS, 1e8),
                              ("eps_jpy", EPS_TAGS, 1)):
        want = stored_sum(field, prior_labels)
        if want is None:
            return None, f"去年同期的 {field} 有缺值，無法交叉核對"
        hit = None
        for tag in tags:
            _t, prior = _pick(doc, [tag], "prior", "Duration")
            if prior is not None and _close(prior / unit, want, q, 0.011 if unit > 1 else 0.06):
                hit = tag
                break
        if not hit:
            return None, f"{field} 對不上去年同期的既有數字（定義可能不同），改由人工登錄"
        _t, cur = _pick(doc, [hit], "cur", "Duration")
        if cur is None:
            return None, f"{field} 本期沒有數字"
        before = stored_sum(field, same_fy) if same_fy else 0
        if before is None:
            return None, f"同一年度前面季別的 {field} 有缺值"
        chosen[field] = round(cur / unit - before, 2)

    _t, bps = _pick(doc, BPS_TAGS, "cur", "Instant")
    if bps is None:
        _t, eq = _pick(doc, EQ_TAGS, "cur", "Instant")
        sh = _shares(doc)
        bps = eq / sh if (eq and sh) else None
    rev, prof = chosen["revenue_oku_jpy"], chosen["business_profit_oku_jpy"]
    row = {
        "label": label, "endDate": end,
        "revenue_oku_jpy": rev,
        "business_profit_oku_jpy": prof,
        "operating_margin_pct": round(prof / rev * 100, 2) if rev else None,
        "net_income_oku_jpy": chosen["net_income_oku_jpy"],
        "eps_jpy": chosen["eps_jpy"],
        "bvps_jpy": round(bps, 2) if bps else None,
    }
    return row, None


def append_row(key, d, row, source, url, disclosed):
    n = len(d.get("fiscal_years") or [])
    for f in FIELDS + ["fiscal_year_end_dates"]:
        if len(d.get(f) or []) != n:
            return False, f"欄位 {f} 長度與季數不符，沒有寫入"
    d["fiscal_years"].append(row["label"])
    d["fiscal_year_end_dates"].append(row["endDate"])
    for f in FIELDS:
        d[f].append(row[f])
    d.setdefault("auto_updates", []).append(
        {"label": row["label"], "source": source, "url": url, "disclosed": disclosed,
         "added": _today().isoformat()})
    d["fetched_at"] = _today().isoformat()
    path = os.path.join(DATA_DIR, f"stock_{key}_quarterly_financials.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    _update_snapshot(key, row, source, url, disclosed)
    return True, ""


def _update_snapshot(key, row, source, url, disclosed):
    p = os.path.join(DATA_DIR, f"stock_{key}_financials.json")
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as f:
        snap = json.load(f)
    if str(snap.get("disclosure_date") or "") >= disclosed:
        return
    end = date.fromisoformat(row["endDate"])
    span = f"{end.year}年{(end.month - 3) % 12 + 1}-{end.month}月"
    snap["fiscal_period"] = f"{row['label']}（{span}）実績"
    snap["source"] = source
    snap["source_urls"] = [url]
    snap["disclosure_date"] = disclosed
    snap["fetched_at"] = _today().isoformat()
    for f in ("revenue_oku_jpy", "net_income_oku_jpy", "operating_margin_pct"):
        if f in snap and row.get(f) is not None:
            snap[f] = row[f]
    note = snap.get("note") or ""
    snap["note"] = re.sub(r"^此資料為最新一季（[^）]*）官方決算短信數字。",
                          f"此資料為最新一季（{row['label']}，{span}）官方決算短信數字。", note)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)


def tdnet_candidates(code4, after):
    raw = json.loads(_get(LIST_URL.format(code=code4)).decode("utf-8"))
    out = []
    for it in raw.get("items") or []:
        t = it.get("Tdnet") or {}
        title = t.get("title") or ""
        xbrl = t.get("url_xbrl") or ""
        pub = (t.get("pubdate") or "")[:10]
        if "決算短信" not in title or "訂正" in title or not xbrl or pub <= after:
            continue
        xbrl = xbrl.split("rd.php?", 1)[-1]
        if not xbrl.startswith("https://www.release.tdnet.info/"):
            continue
        out.append((pub, title, xbrl))
    return sorted(out)


def read_summary_zip(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if "/Summary/" in n and n.endswith("-ixbrl.htm")]
        if not names:
            return None
        return z.read(names[0]).decode("utf-8", "ignore")


def try_tdnet(stock, d, fy_end_month, log):
    code4 = stock["code"].split(".")[0]
    ends = d.get("fiscal_year_end_dates") or []
    after = _next_end(ends[-1]).isoformat() if ends else "2000-01-01"
    added = 0
    for pub, title, url in tdnet_candidates(code4, after):
        try:
            html_text = read_summary_zip(_get(url))
        except Exception as e:  # noqa: BLE001
            log(f"   TDnet 檔案取不到（{e}；TDnet 只保留約一個月）：{title}")
            continue
        if not html_text:
            continue
        doc = parse_summary(html_text)
        row, why = derive_quarter(d, doc, fy_end_month)
        if not row:
            log(f"   略過「{title}」：{why}")
            continue
        ok, why = append_row(stock["key"], d, row, f"TDnet {title} XBRL 官方數字", url, pub)
        if not ok:
            log(f"   ⚠️ {why}")
            break
        log(f"   ✅ 已自動補上 {row['label']}（{row['endDate']}，{pub} 公布，來源 TDnet）")
        added += 1
    return added


def try_jquants(stock, d, log):
    if "J-Quants" not in str(d.get("source") or ""):
        return 0
    import build_financial_history as bfh

    key = bfh._get_cred("api_key", "JQUANTS_API_KEY")
    if not key:
        return 0
    quiet = lambda *_a, **_k: None
    rows = bfh.pick_disclosures(bfh.fetch_statements(stock["code"], key, quiet), quiet)
    payload = bfh.build_payload(stock["code"], d.get("name") or stock["name"],
                                bfh.to_quarterly(rows, quiet), progress=quiet)
    labels = d["fiscal_years"]
    new_labels = payload["fiscal_years"]
    for lb in labels[-4:]:
        if lb in new_labels:
            i, j = labels.index(lb), new_labels.index(lb)
            for f in ("revenue_oku_jpy", "business_profit_oku_jpy", "net_income_oku_jpy"):
                a, b = d[f][i], payload[f][j]
                if a is not None and b is not None and not _close(a, b, 1):
                    log(f"   ⚠️ J-Quants 的 {lb} {f} 跟既有資料不一致（{b} vs {a}），不自動寫入")
                    return 0
    added = 0
    for j, lb in enumerate(new_labels):
        if lb in labels or payload["fiscal_year_end_dates"][j] <= d["fiscal_year_end_dates"][-1]:
            continue
        row = {"label": lb, "endDate": payload["fiscal_year_end_dates"][j]}
        for f in FIELDS:
            row[f] = payload[f][j]
        ok, why = append_row(stock["key"], d, row, "J-Quants API 決算短信 XBRL 摘要",
                             "https://jpx-jquants.com/", "")
        if not ok:
            log(f"   ⚠️ {why}")
            break
        log(f"   ✅ 已自動補上 {lb}（來源 J-Quants）")
        labels = d["fiscal_years"]
        added += 1
    return added


def _next_end(last):
    nxt = date.fromisoformat(last) + timedelta(days=100)
    return date(nxt.year, nxt.month, 1) - timedelta(days=1)


def needs_update(d, fy_end_month, today, start_days=20):
    ends = d.get("fiscal_year_end_dates") or []
    if not ends:
        return False
    return (today - _next_end(ends[-1])).days >= start_days


def main():
    from check_earnings_due import (
        DEFAULT_FY_END_MONTH,
        FISCAL_YEAR_END_MONTH,
    )

    today = _today()
    total = 0
    print("=" * 60)
    print("自動補季報（TDnet 即時 → J-Quants 備援）")
    for s in load_jp_stocks():
        path = os.path.join(DATA_DIR, f"stock_{s['key']}_quarterly_financials.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        fym = FISCAL_YEAR_END_MONTH.get(s["key"], DEFAULT_FY_END_MONTH)
        if not needs_update(d, fym, today):
            continue
        print(f"🔎 {s['name']}：最後一季 {d['fiscal_years'][-1]}，找新的決算短信…")
        got = 0
        try:
            got = try_tdnet(s, d, fym, print)
        except Exception as e:  # noqa: BLE001
            print(f"   TDnet 查詢失敗：{e}")
        if not got:
            try:
                got = try_jquants(s, d, print)
            except Exception as e:  # noqa: BLE001
                print(f"   J-Quants 查詢失敗：{e}")
        if not got:
            print("   還沒有可用的新資料。")
        total += got
    print(f"本次自動補上 {total} 季。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
