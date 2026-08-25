# -*- coding: utf-8 -*-
"""
季報歷史資料自動建立
====================

用 J-Quants API（日本交易所集團 JPX 官方）建立個股的季度財報歷史。

為什麼用 J-Quants
-----------------
它回傳的是決算短信的 XBRL 摘要，也就是我們過去人工翻 PDF 讀的同一份官方資料，
而且欄位是結構化標記的（Sales / OP / OdP / NP …），
TypeOfDocument 還會標明會計準則（JGAAP / IFRS / US-GAAP）。

這正好避開先前川崎重工那次的災難：當時抓第三方網站的「經常益」欄位，
對 IFRS 公司來說那裡裝的是稅前利益而非本業獲利，整條數列因此錯誤。

限制（請先知道）
----------------
* 免費方案：資料期間約過去 2 年、且延遲約 12 週。
  所以能建立約 8 季，最新 1～2 季要用控制台的「財報登錄」手動補。
* 需要免費註冊：https://jpx-jquants.com/

認證設定
--------
J-Quants 已於 2026-06-01 終止 V1，改用 API 金鑰認證，不再需要密碼。
到 https://jpx-jquants.com/ja/dashboard 產生 API Key 後，擇一設定：

1. 控制台「財報登錄」分頁填入（會存到 secrets.json，已列入 .gitignore）
2. 環境變數 JQUANTS_API_KEY
3. 手動建立 secrets.json： {"jquants": {"api_key": "..."}}

不要放進 config.json，那個檔案會被 commit 到 GitHub。

用法
----
    python build_financial_history.py 4063            # 用代號
    python build_financial_history.py --key shinetsu  # 用 config.json 裡的檔名代號
    python build_financial_history.py 4063 --years 3  # 指定回溯年數（受方案上限限制）
    python build_financial_history.py 4063 --dry-run  # 只看抓到什麼，不寫檔
"""
import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from config_loader import load_jp_stocks, CONFIG_PATH

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
API = "https://api.jquants.com/v2"
HEADERS = {"User-Agent": "MarketMonitor/1.0", "Content-Type": "application/json"}

# V2 的欄位名稱是縮寫，這裡對照回我們用得到的項目
F_SALES = "Sales"      # 營收
F_OP = "OP"            # 營業利益
F_ORD = "OdP"          # 經常利益（IFRS／US-GAAP 沒有這個概念，會是空的）
F_NP = "NP"            # 母公司股東應占淨利
F_EPS = "EPS"
F_BPS = "BPS"          # 每股純資產（季報常為空）
F_EQ = "Eq"            # 自己資本
F_SHARES = "ShOutFY"   # 期末發行股數（含庫藏股）
F_TREASURY = "TrShFY"  # 期末庫藏股數

WANTED_PERIODS = {"1Q", "2Q", "3Q", "4Q", "FY"}


def _ctx():
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


def _request(url, data=None, headers=None, timeout=30):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or HEADERS,
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        return json.load(r)


# ---------------------------------------------------------------------------
# 認證
# ---------------------------------------------------------------------------
SECRETS_PATH = os.path.join(BASE_DIR, "secrets.json")


def _load_secrets():
    """讀取 secrets.json。這個檔案在 .gitignore 裡，不會被推上 GitHub。"""
    if not os.path.exists(SECRETS_PATH):
        return {}
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        print(f"⚠️ secrets.json 讀取失敗（{e}），將改用其他來源。")
        return {}


def _creds_from_config():
    """設定檔裡的認證資訊。放這裡會被 commit 進 GitHub，僅為相容舊設定而保留。"""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            c = (json.load(f).get("jquants") or {})
        if c.get("mail") or c.get("password") or c.get("refresh_token"):
            print("⚠️ 偵測到 config.json 裡存有 J-Quants 帳密。")
            print("   這個檔案會被 commit 進 GitHub，等於把密碼公開。")
            print("   建議改存到 secrets.json（已列入 .gitignore），或設成環境變數。")
        return c
    except Exception:
        return {}


def _get_cred(name, *env_names):
    """依序找：環境變數 → secrets.json → config.json（舊做法）。"""
    for e in env_names:
        v = os.environ.get(e)
        if v:
            return v
    s = _load_secrets().get("jquants") or _load_secrets()
    if isinstance(s, dict) and s.get(name):
        return s[name]
    return (_creds_from_config() or {}).get(name)


def get_api_key(progress=print):
    """取得 V2 的 API 金鑰。

    J-Quants 已於 2026-06-01 終止 V1，認證從「帳密換 token」改為
    「在儀表板產生 API 金鑰，放進 x-api-key 標頭」。所以這裡不再需要密碼。
    """
    key = _get_cred("api_key", "JQUANTS_API_KEY")
    if not key:
        raise RuntimeError(
            "找不到 J-Quants API 金鑰。\n"
            "J-Quants 已改用 API 金鑰認證（V1 的帳密登入方式已於 2026-06-01 終止）。\n"
            "取得方式：\n"
            "  1. 登入 https://jpx-jquants.com/ja/dashboard\n"
            "  2. 在儀表板產生 API Key（免費方案即可）\n"
            "  3. 貼進控制台「財報登錄」分頁的 API 金鑰欄位\n"
            "     或設環境變數 JQUANTS_API_KEY"
        )
    progress("使用 API 金鑰認證")
    return key


def _auth_headers(key):
    return {"x-api-key": key, "User-Agent": HEADERS["User-Agent"]}


# ---------------------------------------------------------------------------
# 取得並整理財報
# ---------------------------------------------------------------------------
def fetch_statements(code, api_key, progress=print):
    """抓某檔股票的所有決算資料（V2 /fins/summary）。code 可為 4063 或 4063.T。"""
    num = code.split(".")[0]
    progress(f"向 J-Quants 查詢 {num} 的決算資料…")

    rows, page_key, page = [], None, 0
    while True:
        url = f"{API}/fins/summary?code={urllib.parse.quote(num)}"
        if page_key:
            url += f"&pagination_key={urllib.parse.quote(page_key)}"
        try:
            r = _request(url, headers=_auth_headers(api_key))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError(
                    f"認證被拒（HTTP {e.code}）。請確認 API 金鑰是否正確、是否已在儀表板啟用方案。\n"
                    "金鑰可於 https://jpx-jquants.com/ja/dashboard 產生。"
                )
            if e.code == 404:
                raise RuntimeError(f"查無 {num} 的資料，請確認代號是否正確。")
            if e.code == 429:
                raise RuntimeError("請求次數超過方案上限（HTTP 429），請稍後再試。")
            raise RuntimeError(f"查詢失敗（HTTP {e.code}）")

        batch = r.get("data") or []
        rows.extend(batch)
        page += 1
        page_key = r.get("pagination_key")
        if not page_key:
            break
        progress(f"  已取得 {len(rows)} 筆，繼續下一頁…")
        if page > 30:      # 保險，避免異常情況下無限迴圈
            progress("  分頁過多，停止繼續抓取")
            break

    progress(f"取得 {len(rows)} 筆揭露紀錄")
    return rows


def fetch_company_name(code, api_key, progress=print):
    """向 JPX 官方的上場銘柄一覧查公司名稱。

    Yahoo 對日股多半只回英文名，這裡改用交易所自己的名冊，
    可以拿到官方的日文（漢字）公司名，轉成繁體後就很接近中文寫法。
    回傳 {"ja": 日文名, "en": 英文名}，查不到就回空字典。
    """
    num = code.split(".")[0]
    url = f"{API}/equities/master?code={urllib.parse.quote(num)}"
    try:
        r = _request(url, headers=_auth_headers(api_key))
    except Exception:
        return {}
    rows = r.get("data") or []
    if not rows:
        return {}
    row = rows[0]
    return {"ja": row.get("CoName") or "", "en": row.get("CoNameEn") or ""}


def _num(v):
    if v is None or v == "" or v == "－":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pick_disclosures(statements, progress=print):
    """挑出正式的季度決算，同一期間若有訂正版本，取最新揭露的那一份。"""
    best = {}
    for s in statements:
        period = s.get("CurPerType")
        doc = s.get("DocType") or ""
        if period not in WANTED_PERIODS:
            continue
        if "FinancialStatements" not in doc:
            continue  # 業績預想修正、配當修正等不是決算本身
        fy_end = s.get("CurFYEn") or ""
        key = (fy_end, period)
        prev = best.get(key)
        if prev is None or str(s.get("DiscNo", "")) > str(prev.get("DiscNo", "")):
            best[key] = s

    rows = sorted(best.values(), key=lambda x: (x.get("CurFYEn") or "", x.get("CurPerEn") or ""))
    progress(f"篩出 {len(rows)} 筆正式決算揭露")
    return rows


def _shares(s):
    """發行股數扣除庫藏股，用來在官方沒給 BVPS 時自行推算。"""
    issued = _num(s.get(F_SHARES))
    treasury = _num(s.get(F_TREASURY))
    if issued and issued > 0:
        return issued - (treasury or 0)
    return None


def to_quarterly(rows, progress=print):
    """把累計數字還原成單季。

    決算短信的數字是「期首起算的累計值」，所以同一會計年度內：
      第一期 = 原值
      之後各期 = 本期累計 − 前期累計

    這裡不寫死期別名稱，而是依「期末日」排序後循序差分，
    所以 1Q/2Q/3Q/FY、1Q/2Q/3Q/4Q，甚至變則決算的 5Q 都能正確處理。
    """
    by_fy = {}
    for s in rows:
        by_fy.setdefault(s.get("CurFYEn") or "", []).append(s)

    out = []
    for fy_end in sorted(by_fy):
        periods = sorted(by_fy[fy_end], key=lambda x: x.get("CurPerEn") or "")
        prev = None
        for i, s in enumerate(periods):
            cum = {
                "rev": _num(s.get(F_SALES)),
                "op": _num(s.get(F_OP)),
                "ord": _num(s.get(F_ORD)),
                "ni": _num(s.get(F_NP)),
                "eps": _num(s.get(F_EPS)),
            }
            if i == 0:
                single = dict(cum)          # 該年度第一期本身就是單季
            elif prev is None:
                # 前一期缺漏就沒辦法差分。這時候寧可留白，
                # 也絕不能把累計值當成單季寫進去（那會是完全錯誤的數字）。
                single = {k: None for k in cum}
            else:
                single = {}
                for k in cum:
                    a, b = cum[k], prev.get(k)
                    single[k] = None if (a is None or b is None) else a - b

            fy_year = (fy_end or "")[:4]
            label = f"FY{fy_year[-2:]}Q{i + 1}" if fy_year else f"?Q{i + 1}"

            out.append({
                "label": label,
                "endDate": s.get("CurPerEn"),
                "doc": s.get("DocType", ""),
                "disclosedDate": s.get("DiscDate"),
                "single": single,
                "bvps": _num(s.get(F_BPS)),
                "equity": _num(s.get(F_EQ)),
                "shares": _shares(s),
            })
            prev = cum

    progress(f"還原出 {len(out)} 個單季")
    return out


def build_payload(code, name, quarters, years=None, progress=print):
    """組成報告用的資料檔內容。"""
    if years:
        keep = years * 4
        quarters = quarters[-keep:]

    # 判斷會計準則與獲利科目：IFRS/US-GAAP 用營業利益，日本基準優先用營業利益，
    # 若該公司沒有營業利益（例如銀行），退而使用經常利益。
    docs = " ".join(q["doc"] for q in quarters)
    if "IFRS" in docs:
        standard = "IFRS"
    elif "US" in docs:
        standard = "US-GAAP"
    else:
        standard = "日本基準"

    has_op = any(q["single"].get("op") is not None for q in quarters)
    profit_field = "op" if has_op else "ord"
    profit_label = "營業利益" if has_op else "經常利益"

    labels, ends, rev, prof, margin, ni, eps, bvps = [], [], [], [], [], [], [], []
    for q in quarters:
        s = q["single"]
        r = s.get("rev")
        p = s.get(profit_field)
        labels.append(q["label"])
        ends.append(q["endDate"])
        rev.append(round(r / 1e8, 2) if r is not None else None)
        prof.append(round(p / 1e8, 2) if p is not None else None)
        margin.append(round(p / r * 100, 2) if (r and p is not None) else None)
        n = s.get("ni")
        ni.append(round(n / 1e8, 2) if n is not None else None)
        eps.append(round(s["eps"], 2) if s.get("eps") is not None else None)

        b = q.get("bvps")
        if b is None and q.get("equity") and q.get("shares"):
            b = q["equity"] / q["shares"]      # 官方季報常不給 BVPS，用淨值÷股數自行推算
        bvps.append(round(b, 2) if b is not None else None)

    filled = sum(1 for x in prof if x is not None)
    progress(f"組成 {len(labels)} 季（獲利科目：{profit_label}，準則：{standard}）")

    return {
        "name": name,
        "code": code,
        "source": "J-Quants API（日本取引所グループ JPX 官方）/fins/statements，資料源為各公司決算短信 XBRL 摘要",
        "source_urls": ["https://jpx-jquants.com/"],
        "fetched_at": datetime.now().strftime("%Y-%m-%d"),
        "methodology": (
            f"由 J-Quants API 自動建立（JPX 官方，資料源為決算短信 XBRL 摘要）。"
            f"會計準則：{standard}；獲利欄位採用「{profit_label}」（API 欄位 "
            f"{'OP' if profit_field == 'op' else 'OdP'}）。"
            "決算短信的數字為期首起算的累計值，本檔已用差分還原為單季："
            "Q2＝上半年累計−Q1、Q3＝前三季累計−上半年累計、Q4＝全年−前三季累計。"
            "營益率＝獲利÷營收×100 由程式計算。"
            "BVPS 優先採用官方揭露的每股純資產；季報未揭露時，以（自己資本÷（發行股數−庫藏股））推算。"
            "注意：免費方案的資料期間與即時性有限制，最新一至兩季可能尚未涵蓋，"
            "需另以官方決算短信人工補登。"
            f"（{filled}/{len(labels)} 季取得獲利數字）"
        ),
        "fiscal_years": labels,
        "fiscal_year_end_dates": ends,
        "revenue_oku_jpy": rev,
        "business_profit_oku_jpy": prof,
        "operating_margin_pct": margin,
        "net_income_oku_jpy": ni,
        "eps_jpy": eps,
        "bvps_jpy": bvps,
        "_standard": standard,
        "_profit_label": profit_label,
    }


def verify(payload, rows, progress=print):
    """把還原出來的單季加總回去，跟官方全年數字比對，抓出差分錯誤。"""
    issues = []
    fy_totals = {}
    for s in rows:
        if (s.get("CurPerType") or "") in ("FY", "4Q"):
            fy_end = s.get("CurFYEn") or ""
            fy_totals[fy_end[:4]] = {
                "rev": _num(s.get(F_SALES)),
                "op": _num(s.get(F_OP)) or _num(s.get(F_ORD)),
                "ni": _num(s.get(F_NP)),
            }

    by_year = {}
    for lbl, r, p, n in zip(payload["fiscal_years"], payload["revenue_oku_jpy"],
                            payload["business_profit_oku_jpy"], payload["net_income_oku_jpy"]):
        yr = lbl[2:4]
        d = by_year.setdefault(yr, {"rev": 0, "op": 0, "ni": 0, "n": 0})
        if r is not None: d["rev"] += r
        if p is not None: d["op"] += p
        if n is not None: d["ni"] += n
        d["n"] += 1

    for yr, d in sorted(by_year.items()):
        if d["n"] != 4:
            continue   # 不完整的年度不比對
        full_year = "20" + yr
        official = fy_totals.get(full_year)
        if not official or official.get("rev") is None:
            continue
        off_rev = official["rev"] / 1e8
        diff = abs(d["rev"] - off_rev)
        tol = max(1.0, off_rev * 0.005)
        mark = "✓" if diff <= tol else "✗"
        progress(f"  {mark} FY{yr} 四季營收加總 {d['rev']:.0f} 億 vs 官方全年 {off_rev:.0f} 億")
        if diff > tol:
            issues.append(f"FY{yr} 營收加總與官方全年差 {diff:.0f} 億，請人工確認")
    return issues


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build(code=None, key=None, years=None, dry_run=False, progress=print):
    stocks = load_jp_stocks(include_disabled=True)
    stock = None
    if key:
        stock = next((s for s in stocks if s["key"] == key), None)
        if not stock:
            raise RuntimeError(f"config.json 裡找不到檔名代號「{key}」")
        code = stock["code"]
    elif code:
        norm = code if "." in code else code + ".T"
        stock = next((s for s in stocks if s["code"].upper() == norm.upper()), None)
    if not code:
        raise RuntimeError("請指定股票代號或檔名代號")

    name = (stock or {}).get("name") or code
    out_key = (stock or {}).get("key") or "s" + code.replace(".", "").lower()

    progress(f"開始建立「{name}」（{code}）的季報歷史")
    api_key = get_api_key(progress)
    statements = fetch_statements(code, api_key, progress)
    if not statements:
        raise RuntimeError("J-Quants 沒有回傳任何資料。免費方案僅涵蓋近兩年，"
                           "若是剛上市或代號有誤也可能查無資料。")

    rows = pick_disclosures(statements, progress)
    if not rows:
        raise RuntimeError("抓到資料但沒有任何決算短信，無法建立歷史。")

    quarters = to_quarterly(rows, progress)
    payload = build_payload(code, name, quarters, years=years, progress=progress)

    progress("核對年度加總…")
    issues = verify(payload, rows, progress)

    standard = payload.pop("_standard")
    profit_label = payload.pop("_profit_label")

    if dry_run:
        progress("（試跑模式，沒有寫檔）")
    else:
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, f"stock_{out_key}_quarterly_financials.json")
        backup = None
        if os.path.exists(path):
            backup = path + ".bak"
            with open(path, encoding="utf-8") as f_in, open(backup, "w", encoding="utf-8") as f_out:
                f_out.write(f_in.read())
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        progress(f"已寫入 data/stock_{out_key}_quarterly_financials.json")
        if backup:
            progress(f"（原檔已備份為 stock_{out_key}_quarterly_financials.json.bak）")

    n = len(payload["fiscal_years"])
    gaps = {k: sum(1 for v in payload[k] if v is None)
            for k in ["revenue_oku_jpy", "business_profit_oku_jpy", "net_income_oku_jpy",
                      "eps_jpy", "bvps_jpy"]}
    progress("")
    progress(f"完成：{n} 季　會計準則 {standard}　獲利科目「{profit_label}」")
    progress(f"缺漏：營收 {gaps['revenue_oku_jpy']}／獲利 {gaps['business_profit_oku_jpy']}／"
             f"淨利 {gaps['net_income_oku_jpy']}／EPS {gaps['eps_jpy']}／BVPS {gaps['bvps_jpy']}")
    if payload["fiscal_years"]:
        progress(f"期間：{payload['fiscal_years'][0]} ～ {payload['fiscal_years'][-1]}")
    if issues:
        progress("")
        progress("⚠️ 需要人工確認：")
        for i in issues:
            progress("  ・" + i)
    progress("")
    progress("提醒：免費方案有約 12 週延遲，最新一至兩季請用「財報登錄」補上。")
    progress("　　　獲利科目請對照官方決算短信確認，特別是 IFRS 公司的事業利益／營業利益差異。")

    return {"key": out_key, "count": n, "gaps": gaps, "issues": issues,
            "standard": standard, "profitLabel": profit_label}


def main():
    ap = argparse.ArgumentParser(description="用 J-Quants API 自動建立個股季報歷史")
    ap.add_argument("code", nargs="?", help="股票代號，例如 4063")
    ap.add_argument("--key", help="config.json 裡的檔名代號，例如 shinetsu")
    ap.add_argument("--years", type=int, default=None, help="只保留最近幾年（預設全部）")
    ap.add_argument("--dry-run", action="store_true", help="只顯示結果不寫檔")
    args = ap.parse_args()

    if not args.code and not args.key:
        ap.print_help()
        return 1
    try:
        build(code=args.code, key=args.key, years=args.years, dry_run=args.dry_run)
        return 0
    except RuntimeError as e:
        print(f"\n❌ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
