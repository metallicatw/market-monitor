# -*- coding: utf-8 -*-
"""
離線 parser 測試 —— 完全不打網路。

每個測試都拿 reference/samples/*.raw.gz 裡「真的打過端點拿回來的原始 bytes」
餵給 parser，驗證欄位、單位、量級都對。這樣端點哪天改格式，
測試會在資料進到報告之前先紅，而不是報告上默默出現一條錯誤的線。

跑法：
    python tests/test_parsers_offline.py
    # 或 pytest tests/test_parsers_offline.py
"""
import gzip
import json
import os
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(BASE_DIR, "reference", "samples")
sys.path.insert(0, BASE_DIR)

import fetch_market_data as fmd  # noqa: E402


def sample(name):
    with gzip.open(os.path.join(SAMPLES, f"{name}.raw.gz"), "rb") as f:
        return f.read()


class _StubHTTP:
    """把 _http_get 換成「從 fixture 讀」，順便記錄被要求的網址。"""

    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def __call__(self, url, timeout=20):
        self.urls.append(url)
        return self.payload


class _RoutingHTTP:
    """依網址分流到不同 fixture 的 stub。

    市值那一支現在打三個地方（央行 CSV、櫃買索引、櫃買 ODS）外加一個對帳用的
    t49，單一 payload 的 stub 不夠用了。找不到對應的 fixture 就 raise——
    測試裡「悄悄回了別人的資料」比直接失敗糟得多。
    """

    def __init__(self, routes, missing=None):
        self.routes = routes          # {網址片段: fixture 名稱}
        self.missing = missing or ()  # 這些片段要模擬「抓不到」
        self.urls = []

    def __call__(self, url, timeout=20, **kwargs):
        self.urls.append(url)
        for frag in self.missing:
            if frag in url:
                raise OSError(f"simulated failure for {frag}")
        for frag, name in self.routes.items():
            if frag in url:
                return sample(name)
        raise AssertionError(f"測試沒有為這個網址準備 fixture：{url}")


MARKET_CAP_ROUTES = {
    "EG27M01": "cbc_eg27m01_listed_marketcap",
    "monthlyRptMktDl": "tpex_monthlyrptmkt_ods",
    "monthlyRptMkt": "tpex_monthlyrptmkt_index",
    "datasets/11138": "fsc_t49_11138_market_overview",
}


def run_market_cap(routes=None, missing=(), existing=None, incremental=True):
    """在乾淨的暫存 DATA_DIR 裡跑 fetch_tw_market_cap，網路全部走 fixture。"""
    stub = _RoutingHTTP(routes or MARKET_CAP_ROUTES, missing)
    orig_get, orig_post, orig_dir = fmd._http_get, fmd._http_post, fmd.DATA_DIR
    orig_sleep = fmd.time.sleep
    with tempfile.TemporaryDirectory() as tmp:
        fmd._http_get = stub
        fmd._http_post = lambda url, data, timeout=30: stub(url)
        fmd.DATA_DIR = tmp
        fmd.time.sleep = lambda *_a, **_k: None      # 不要真的等重試 backoff
        try:
            if existing is not None:
                with open(os.path.join(tmp, "tw_market_cap.json"), "w", encoding="utf-8") as f:
                    json.dump(existing, f)
            result = fmd.fetch_tw_market_cap(incremental=incremental)
            on_disk = None
            path = os.path.join(tmp, "tw_market_cap.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    on_disk = json.load(f)
            return result, on_disk, stub
        finally:
            fmd._http_get, fmd._http_post, fmd.DATA_DIR = orig_get, orig_post, orig_dir
            fmd.time.sleep = orig_sleep


def run_with_fixture(fixture_name, fn, **kwargs):
    """在一個乾淨的暫存 DATA_DIR 裡，用 fixture 當回應跑 fetcher。"""
    stub = _StubHTTP(sample(fixture_name))
    orig_get, orig_dir = fmd._http_get, fmd.DATA_DIR
    with tempfile.TemporaryDirectory() as tmp:
        fmd._http_get, fmd.DATA_DIR = stub, tmp
        try:
            return fn(incremental=False, **kwargs), stub
        finally:
            fmd._http_get, fmd.DATA_DIR = orig_get, orig_dir


# ---------------------------------------------------------------------------


def test_tw_pmi():
    result, _ = run_with_fixture("ndc_pmi_ndc6100", fmd.fetch_tw_pmi, years_back=50)
    assert result is not None, "PMI parser 回 None"
    assert result["dates"][0] == "2012-07-01", result["dates"][0]
    assert result["dates"][-1] == "2026-08-01", result["dates"][-1]
    assert result["pmi"][-1] == 62.5, result["pmi"][-1]
    assert result["nmi"][-1] == 55.6, result["nmi"][-1]
    # 早期 NMI 欄位是 "-"，必須解析成 None 而不是 0
    assert result["nmi"][0] is None, result["nmi"][0]
    assert all(20 < v < 80 for v in result["pmi"] if v is not None), "PMI 應該都在 20~80"
    print(f"  PMI ok：{len(result['dates'])} 個月，最新 {result['dates'][-1]} "
          f"PMI={result['pmi'][-1]} NMI={result['nmi'][-1]}")


def test_tw_m1b_uses_balance_not_change():
    result, _ = run_with_fixture("cbc_ef15m01_money_aggregates", fmd.fetch_tw_m1b, years_back=50)
    assert result is not None, "M1B parser 回 None"
    assert result["dates"][-1] == "2026-07-01", result["dates"][-1]
    assert abs(result["m1b"][-1] - 30_530_948) < 1, result["m1b"][-1]
    assert result["unit"] == "新臺幣百萬元"
    assert all(v > 0 for v in result["m1b"]), "餘額不該有負值"
    print(f"  M1B ok：{len(result['dates'])} 個月，最新 {result['dates'][-1]} "
          f"= {result['m1b'][-1]:,.0f} 百萬元")


def test_m1b_parser_rejects_the_lookalike_file():
    """
    EF19M01（M1B變動因素分析）的欄位名幾乎跟 EF15M01 一樣，
    但值是「當月變動額」不是餘額。抓錯了畫出來的線只是在零附近抖，
    不會有任何錯誤訊息 —— 所以 parser 必須自己擋下來。
    """
    result, _ = run_with_fixture("cbc_ef19m01_m1b_factors", fmd.fetch_tw_m1b, years_back=50)
    assert result is None, "抓到變動額檔案卻沒被擋下來，這正是會靜靜出錯的那種 bug"
    print("  M1B 反向測試 ok：EF19M01（變動額）有被擋下來")


def test_tw_market_cap_sums_two_sources():
    """央行（上市）＋ 櫃買（上櫃）＝ 上市櫃總市值，而且歷史不是 5 個月。"""
    result, _, stub = run_market_cap(incremental=False)
    assert result is not None, "市值 parser 回 None"
    assert len(result["dates"]) >= 120, \
        f"接了長歷史來源之後不該只有 {len(result['dates'])} 個月"
    assert result["dates"][0] == "2016-01-01", result["dates"][0]
    # 央行 2026M07 上市 140,848,179 + 櫃買 115年7月 上櫃 9,526,934.205 百萬元
    i = result["dates"].index("2026-07-01")
    assert abs(result["market_cap"][i] - (140_848_179 + 9_526_934.205226)) < 1, \
        result["market_cap"][i]
    # 三個來源都要真的被打到（不是某一支悄悄沒跑）
    joined = " ".join(stub.urls)
    for frag in ("EG27M01", "monthlyRptMkt", "datasets/11138"):
        assert frag in joined, f"{frag} 沒有被請求"
    print(f"  市值 ok：{len(result['dates'])} 個月 {result['dates'][0]}～{result['dates'][-1]}，"
          f"最新 {result['market_cap'][-1]/1e6:.2f} 兆元")


def test_market_cap_reconciles_against_t49():
    """
    這是整個資料源替換案的證據：央行＋櫃買 vs 金管會 t49，重疊月份必須相符。

    t49 是獨立編製的，所以對得上就同時證明了三件事——單位是新臺幣百萬元、
    兩邊都是期末口徑（不是月平均）、以及「央行那份只含上市、櫃買那份只含上櫃」。
    對不上就是有東西變了，這個測試會在資料進到報告之前先紅。
    """
    result, _, _ = run_market_cap(incremental=False)
    assert result["reconciled_months"] >= 4, \
        f"只對帳到 {result['reconciled_months']} 個月，t49 的滾動視窗是不是變了？"
    assert result["reconcile_mismatches"] == 0, \
        f"有 {result['reconcile_mismatches']} 個月對不上 t49"
    print(f"  對帳 ok：{result['reconciled_months']} 個重疊月份與 t49 完全相符")


def test_market_cap_only_writes_months_both_sources_have():
    """
    央行從 1987 年起、櫃買從 2016 年起。只有上市的月份寫進去，就是一個少了
    上櫃、卻叫做「上市櫃總市值」的假總額——而且不會有任何錯誤訊息。
    """
    result, _, _ = run_market_cap(incremental=False)
    assert result["dates"][0] >= "2016-01-01", \
        f"寫進了櫃買沒有資料的月份：{result['dates'][0]}"


def test_market_cap_merge_never_shrinks_history():
    """寫檔必須是合併不是覆蓋，否則早期累積的歷史會被砍掉。"""
    history = {
        "dates": [f"2015-{m:02d}-01" for m in range(1, 13)],
        "market_cap": [50_000_000 + m * 100_000 for m in range(1, 13)],
        "listed_count": [1700 + m for m in range(1, 13)],
    }
    result, _, _ = run_market_cap(existing=history)
    assert result["dates"][0] == "2015-01-01", "舊歷史被洗掉了"
    assert len(result["dates"]) > 120


def test_market_cap_keeps_cache_when_a_source_fails():
    """任何一個來源掛掉，既有快取都必須原封不動——不能寫出殘缺的檔。"""
    history = {"dates": ["2024-01-01"], "market_cap": [70_000_000], "listed_count": [1800]}
    for missing in ("EG27M01", "monthlyRptMkt"):
        result, on_disk, _ = run_market_cap(missing=(missing,), existing=history)
        assert on_disk == history, f"{missing} 失敗時卻動到了既有快取"
        assert result == history
    print("  失敗保護 ok：上市、上櫃任一支掛掉都不動既有快取")


def test_market_cap_survives_t49_being_gone():
    """t49 只是對帳用的第二意見。它掛掉不該讓整份市值抓不成。"""
    result, _, _ = run_market_cap(missing=("datasets/11138",), incremental=False)
    assert result is not None, "對帳來源掛掉不該讓主資料一起失敗"
    assert len(result["dates"]) >= 120
    assert result["reconciled_months"] == 0
    print("  t49 降級 ok：對帳來源掛掉，主資料照樣寫入（只是沒有對帳）")


def test_ods_parser_reads_the_right_column_by_name():
    """
    櫃買那份 1989～2015 是年列、2016 起是月列，混在同一張表。
    欄位位置也不保證固定，所以是用欄名找，不是寫死索引。
    """
    rows = fmd._ods_rows(sample("tpex_monthlyrptmkt_ods"))
    assert rows, "ODS 解不出任何列"
    header = next(r for r in rows if any("上櫃股票市值" in c for c in r))
    col = next(i for i, c in enumerate(header) if "上櫃股票市值" in c)
    months = [r for r in rows if fmd._roc_month_to_iso(r[0])]
    years = [r for r in rows if not fmd._roc_month_to_iso(r[0]) and "年" in r[0]]
    assert len(months) >= 120, f"只解出 {len(months)} 個月列"
    assert years, "年列應該存在且被排除在外"
    assert float(months[-1][col]) > 1_000_000, "上櫃市值的量級不對（應為百萬元）"
    print(f"  ODS ok：{len(months)} 個月列、{len(years)} 個年列（年列已排除），欄位第 {col} 欄")


def test_ratio_alignment_and_magnitude():
    """
    市值貨幣比：只算「兩邊都有的月份」。
    M1B 比市值新，多出來的月份不能拿舊市值去湊。
    """
    stub = _RoutingHTTP(MARKET_CAP_ROUTES)
    orig_get, orig_post, orig_dir = fmd._http_get, fmd._http_post, fmd.DATA_DIR
    with tempfile.TemporaryDirectory() as tmp:
        fmd._http_get = stub
        fmd._http_post = lambda url, data, timeout=30: stub(url)
        fmd.DATA_DIR = tmp
        try:
            cap = fmd.fetch_tw_market_cap(incremental=False)
            m1b_stub = _StubHTTP(sample("cbc_ef15m01_money_aggregates"))
            fmd._http_get = m1b_stub
            m1b = fmd.fetch_tw_m1b(years_back=50, incremental=False)

            result = fmd.compute_tw_marketcap_m1b_ratio()
            assert result is not None
            # 市值到 202607、M1B 也到 202607，所以比值的尾端是 202607。
            assert result["dates"][-1] == "2026-07-01", result["dates"][-1]
            # 交集的起點由市值決定（櫃買的月資料 2016-01 起），不是 M1B（1987 起）。
            assert result["dates"][0] == "2016-01-01", result["dates"][0]
            assert len(result["dates"]) == len(cap["dates"]), \
                "比值的月份數應該等於市值的月份數（M1B 覆蓋更長）"
            # 這五個月是探測時人工對過 MacroMicro 量級的，留著當定樁。
            for month, want in (("2026-01-01", 3.81), ("2026-02-01", 4.13),
                                ("2026-03-01", 3.72), ("2026-04-01", 4.56),
                                ("2026-05-01", 5.16)):
                got = result["ratio"][result["dates"].index(month)]
                assert abs(got - want) < 0.01, f"{month} 比值 {got} 與預期 {want} 不符"
            assert 1.0 < min(result["ratio"]) and max(result["ratio"]) < 20.0, \
                "比值量級不對，單位可能又錯了"
            print(f"  市值貨幣比 ok：{len(result['dates'])} 個月 "
                  f"{result['dates'][0]}~{result['dates'][-1]}，"
                  f"區間 {min(result['ratio']):.2f}~{max(result['ratio']):.2f}")
        finally:
            fmd._http_get, fmd._http_post, fmd.DATA_DIR = orig_get, orig_post, orig_dir


def test_fred_csv_parser():
    """FRED 回應格式固定兩欄，缺值是 '.'。用手寫的最小樣本驗證解析規則。"""
    from datetime import date as _date
    raw = ("observation_date,UNRATE\n"
           "2026-05-01,4.0\n"
           "2026-06-01,.\n"        # 缺值：跳過，不補
           "2026-07-01,4.1\n")
    dates, values = fmd._parse_fred_csv(raw, "UNRATE", _date(2020, 1, 1))
    assert dates == ["2026-05-01", "2026-07-01"], dates
    assert values == [4.0, 4.1], values
    print("  FRED parser ok：缺值 '.' 有被跳過而不是變成 0")


def test_twse_mi_index_really_has_no_market_cap():
    """
    留這個測試是為了記錄結論：MI_INDEX 的 9 張表沒有任何一張有市值。
    以後有人想「再去 TWSE 找找看」時，這裡直接給答案。
    """
    tables = json.loads(sample("twse_mi_index_tables_20260831").decode("utf-8"))["tables"]
    all_fields = [f for t in tables if t.get("fields") for f in t["fields"]]
    assert all_fields, "fixture 壞了"
    assert not any("市值" in f for f in all_fields), \
        "MI_INDEX 竟然出現市值欄位了？那可以改用它當更即時的來源"
    print(f"  TWSE MI_INDEX ok：{len(tables)} 張表 / {len(all_fields)} 個欄位，確認沒有市值")


def test_every_us_indicator_chart_is_wired_to_a_canvas_that_exists():
    """十二條指標線，每一條都要有畫布、有資料、有週期切換。

    這一段原本刻意不畫圖，理由是「單位不同畫在同一張圖上沒有意義」——那個理由
    沒有錯，錯的是它推出的結論。一格一張圖就沒有這個問題，而缺了圖的代價是
    4.1% 的失業率看不出它是持平第三個月還是從 3.5% 爬上來的。

    這條測試守的是接線：canvas 的 id、chartRegistry 的鍵、tf-bar 的 id 三個必須
    是同一個字串。錯開的話畫面上是一塊空白，而且**不會有任何錯誤**——Chart.js
    拿到 null 就靜靜地什麼都不做。

    VIX 不在裡面：它在「房地產與信心」那一組裡是借放的，而它本來就有自己的一整
    個區塊。同一條線畫兩次，第二次只是讓人懷疑哪一張才算數。
    """
    import re

    import generate_report_local as grl

    groups = grl.load_us_indicator_groups()
    series = grl.load_fred_series()
    fred = {}
    for meta in series:
        cache = meta.get("cache") or f"fred_{meta['id'].lower()}.json"
        path = os.path.join(BASE_DIR, "data", cache)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                fred[meta["id"]] = json.load(fh)
    assert fred, "data/ 裡一筆 FRED 序列都沒有，這條測試沒有東西可驗"

    drawn = 0
    for group in groups:
        members = [(m, fred[m["id"]]) for m in series
                   if m.get("group") == group["key"] and m["id"] in fred]
        # VIX 在呼叫端被併進這一組——這裡照做，才驗得到「它不會被畫第二次」。
        if group["key"] == "housing_sentiment":
            members.append(({"name": "VIX", "unit": "", "freq": "日"},
                            {"dates": ["2026-09-01"], "close": [15.0]}))
        if not members:
            continue
        html, script = grl.render_us_indicator_group(group, members)
        canvases = set(re.findall(r'<canvas id="(usfr[A-Z0-9]+)Chart"', html))
        bars = set(re.findall(r'id="tf-(usfr[A-Z0-9]+)"', html))
        keys = set(re.findall(r"chartRegistry\['(usfr[A-Z0-9]+)'\]", script))
        assert canvases == keys == bars, (group["key"], canvases, keys, bars)
        assert "usfrVIX" not in canvases, "VIX 被畫了第二次"
        # 每一格的數值卡還在——圖是多出來的，不是拿來取代數字的。
        for meta, _ in members:
            assert meta["name"] in html
        drawn += len(canvases)
    assert drawn >= 10, f"只接上了 {drawn} 條，預期十二條左右"
    print(f"  美股指標歷史線 ok：{drawn} 條，各自一張圖、一條軸")


def test_the_report_lets_you_change_the_list_without_leaving_the_page():
    """「我要的是直接在前台操作，不是連結到後台。」

    上一版是一顆連到 Actions 的按鈕。那還是「到後台去做」，只是換了一個入口：
    在手機上想加一檔股票，要跳出報告、進 GitHub、找到 workflow、展開 Run
    workflow、填表、送出，然後再自己走回來看結果。

    這一版是表單，就在報告上。這條守三件事：欄位齊、動作選單和 workflow 的
    choice 逐字相同（不一致的時候 dispatch 會被 GitHub 打回來，而錯誤訊息只寫
    「Required input is not provided」）、以及 repo 與 workflow 檔名是算出來的
    不是寫死的。
    """
    import re

    import generate_report_local as grl

    bar = grl.render_manage_bar()
    assert bar, "找不到管理列"
    assert 'onsubmit="return mmDispatch' in bar, "沒有表單，還是一顆連結？"
    for field in ("mmAction", "mmCode", "mmPrice", "mmPer", "mmYears", "mmGo"):
        assert f'id="{field}"' in bar, f"少了欄位 {field}"

    wf = open(os.path.join(BASE_DIR, ".github", "workflows",
                           grl.MANAGE_WORKFLOW), encoding="utf-8").read()
    block = wf.split("options:", 1)[1].split("code:", 1)[0]
    options = tuple(m.strip() for m in re.findall(r"^\s*-\s*(\S.*)$", block, re.M))

    # workflow 的每一個動作都要有地方按得到，而按得到的每一個動作 workflow 都要
    # 認得。兩邊各自漏掉的症狀不一樣，但都不會報錯：
    #
    #   * 選單裡少一個 → 那個功能從前台消失，而沒有人會發現它曾經在。
    #   * 選單裡多一個 → dispatch 送出一個 workflow 不認得的字串，case 落到
    #     `*)`，於是它「成功地」只更新了報告，名單一個字都沒改。
    #
    # 所以比的是集合相等，不是 MANAGE_ACTIONS 自己等於 options——那三個貼在股票
    # 旁邊的動作（隱藏／恢復／移除）也是 workflow 的動作，只是不由選單送出。
    assert set(options) == set(grl.MANAGE_ACTIONS) | set(grl.CARD_ACTIONS), (
        sorted(options), sorted(set(grl.MANAGE_ACTIONS) | set(grl.CARD_ACTIONS))
    )
    assert not set(grl.MANAGE_ACTIONS) & set(grl.CARD_ACTIONS), "同一個動作有兩個入口"
    for name in grl.MANAGE_ACTIONS:
        assert f'<option value="{name}">' in bar, f"選單裡少了「{name}」"
    for name in grl.CARD_ACTIONS:
        assert f'<option value="{name}">' not in bar, f"「{name}」不該還留在選單裡"

    # 送出的 inputs 名稱要和 workflow 的 inputs 一致。
    for key in ("action", "code", "price_buy", "per_buy", "years"):
        assert f"{key}:" in wf, f"workflow 沒有 {key} 這個 input"
        assert key in bar, f"表單沒有送出 {key}"
    print(f"  管理表單 ok：選單 {len(grl.MANAGE_ACTIONS)} 個動作"
          f"＋股票旁邊 {len(grl.CARD_ACTIONS)} 個，5 個欄位")


def test_every_field_says_what_it_is_and_what_its_default_is():
    """每一格的說明文字抄自 workflow 的 description，一字不差，而且**看得到全文**。

    兩次都栽在同一句話的句尾：

    1. 第一版是自己縮寫過的（「本益比」對上「本益比布局參考線（選填，留空用預設
       20）」）。縮寫掉的正是「選填」和「預設 20」。
    2. 第二版照抄了全文，但塞進 placeholder。格子只有 200 px 寬，於是畫面上是
       「本益比布局參考線（選填，留空用預」——又把「預設 20」吃掉了。而且
       placeholder 一打字就消失，可是這幾格是偶爾用一次的東西。

    所以現在是欄位**上面**的標籤（`.mm-lab`），和 Actions 那張 Run workflow 表單
    同一個排法。這條測試釘住那個結構：不是 placeholder，是標籤。
    """
    import generate_report_local as grl

    wf = open(os.path.join(BASE_DIR, ".github", "workflows",
                           grl.MANAGE_WORKFLOW), encoding="utf-8").read()
    bar = grl.render_manage_bar()
    for key, text in grl.MANAGE_FIELD_HINTS.items():
        assert f'description: "{text}"' in wf, f"{key} 的說明和 workflow 不一樣"
        assert f'<span class="mm-lab">{text}' in bar, f"{key} 的說明沒有寫在欄位上面"
    # 只看那張表單。權杖那一格的 placeholder（`github_pat_…`）留著是對的：
    # 它是格式範例、不是說明，而且短到不會被截。
    form = bar[bar.index("<form"):bar.index("</form>")]
    assert "placeholder=" not in form, "說明又被塞回 placeholder 了，長的那幾句會被截掉"
    # 每一格都要有標籤：少一格不會報錯，只會讓那一格變成一個沒有名字的輸入框。
    assert bar.count('class="mm-lab"') == len(grl.MANAGE_FIELD_HINTS)
    print(f"  {len(grl.MANAGE_FIELD_HINTS)} 個欄位的說明寫在欄位上面，和 workflow 一致")


def test_every_button_sends_a_code_the_workflow_will_accept():
    """按鈕送出去的代號，必須通過 manage.yml 自己那一關。

    這一條是踩出來的。第一版按鈕送的是 `code`，而 `code` 是 Yahoo 的 ticker
    ——「4452.T」。manage.yml 裡有一段 shell 只收數字與英文字母（那一關擋的是
    把奇怪的字送進 manage_stock.py），於是每一次按 🙈 或 🗑️ 都是：

        Error: 股票代號只能是數字或英文字母，收到的是：4109.T

    而且**前端完全看不出來**：dispatch 回 204，報告上顯示「已送出，雲端開始
    跑了…」，兩分鐘後才變成「那一趟沒有成功」。

    `manage_stock._find()` 兩種都認（key 或 code），而 key 永遠是英數，所以送
    key 是唯一不會撞到那一關的寫法。這條測試直接拿 workflow 裡那個字元類別去
    比對每一顆按鈕真的送出去的字串。
    """
    import re

    import generate_report_local as grl

    wf = open(os.path.join(BASE_DIR, ".github", "workflows",
                           grl.MANAGE_WORKFLOW), encoding="utf-8").read()
    # workflow 用 shell 的 case 擋：`*[!0-9A-Za-z]*` 就是「有任何一個字元不是英數」。
    assert "*[!0-9A-Za-z]*" in wf, "workflow 的代號檢查改了，這條測試要跟著改"
    ok = re.compile(r"^[0-9A-Za-z]+$")

    stocks = grl.load_jp_stocks(include_disabled=True)
    assert stocks, "設定裡一檔都沒有"
    for s in stocks:
        assert ok.match(s["key"]), f'檔名代號 {s["key"]!r} 過不了 workflow 那一關'

    # 隱藏列上那幾顆按鈕真的送的是什麼。
    row = grl.render_hidden_row(stocks[:3])
    for sent in re.findall(r'data-code="([^"]*)"', row):
        assert ok.match(sent), f"隱藏列送出 {sent!r}，workflow 會退回來"
    print(f"  {len(stocks)} 檔的代號都過得了 workflow 那一關")


def test_hiding_a_stock_is_not_a_one_way_door():
    """〔恢復顯示〕要有地方按得到。

    隱藏起來的個股照定義沒有卡片，所以「恢復」這個動作沒有天然的位置。原本的
    答案是選單裡的〔列出目前名單〕：跑一趟 Actions、等兩分鐘、去 log 裡讀名單、
    回來再跑第二趟。那個動作拿掉了，取而代之的是卡片底下那一列。

    沒有這一列，隱藏就變成單向操作——而那不會報錯，只會讓一檔股票再也回不來。
    """
    import generate_report_local as grl

    row = grl.render_hidden_row([
        {"key": "testco", "code": "9999.T", "name": "測試公司"},
    ])
    assert "恢復顯示" in row, "那一列不會送出〔恢復顯示〕"
    # 送出的是檔名代號（英數，過得了 workflow 那一關）；畫面上顯示的是 Yahoo
    # ticker，因為那是人看得懂的那一個。兩者刻意不同。
    assert 'data-code="testco"' in row, "代號沒有跟著按鈕走"
    assert 'data-code="9999.T"' not in row, "又送 Yahoo ticker 了，workflow 會退回來"
    assert "9999.T" in row, "畫面上要看得到代號"
    assert "測試公司" in row
    # 沒有隱藏中的股票就整列不畫——一條空的分隔線不是資訊。
    assert grl.render_hidden_row([]) == ""
    print("  〔恢復顯示〕有家了")


def test_no_credential_is_ever_baked_into_the_report():
    """權杖由使用者自己貼，存在他自己的瀏覽器裡——**絕不**進這份 HTML。

    這一頁是公開的。一把不小心被寫進產生器的權杖會直接躺在 GitHub Pages 上，
    而且沒有任何症狀：功能照常運作。

    所以這條測試在意的不是「現在沒有」，是「它不可能有」——產生器只寫得出讀取
    localStorage 的程式碼，沒有任何路徑把一個字面值的權杖放進去。
    """
    import re

    import generate_report_local as grl

    bar = grl.render_manage_bar()
    # GitHub 權杖的幾種前綴。出現在 HTML 裡就是出事了。
    for prefix in ("github_pat_", "ghp_", "gho_", "ghs_", "ghu_"):
        # 說明文字裡那個 placeholder（`github_pat_…`）是給人看的樣子，
        # 後面沒有接任何字元；真的權杖後面會有一長串。
        for m in re.finditer(re.escape(prefix) + r"[A-Za-z0-9_]{4,}", bar):
            raise AssertionError(f"HTML 裡有疑似權杖：{m.group(0)[:20]}…")
    assert "localStorage" in bar, "權杖應該存在瀏覽器，不是別的地方"
    assert "api.github.com" in bar
    # 權杖只能去一個地方：GitHub 的 API。
    hosts = set(re.findall(r"https://([a-z0-9.\-]+)", bar))
    assert hosts <= {"api.github.com", "github.com"}, hosts
    print("  報告裡沒有任何憑證，權杖只送 api.github.com")


def test_the_manage_link_survives_a_local_regeneration():
    """只靠 GITHUB_REPOSITORY 的話，本機重跑一次報告這顆按鈕就會消失。

    而這份 index.html 本機重新產生過不只一次（併衝突的時候就是這樣解的）。
    一顆時有時無的按鈕比沒有按鈕更難用：它會讓人以為功能被拿掉了。
    """
    import generate_report_local as grl

    saved = os.environ.pop("GITHUB_REPOSITORY", None)
    try:
        url = grl.manage_url()          # 沒有 env，只能問 git remote
    finally:
        if saved is not None:
            os.environ["GITHUB_REPOSITORY"] = saved
    assert url.endswith("/actions/workflows/" + grl.MANAGE_WORKFLOW), url
    assert url.count("/") >= 6, f"repo 段沒解析出來：{url}"
    print(f"  本機也拿得到網址：{url}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        print(f"▶ {t.__name__}")
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ❌ 未預期例外：{e!r}")
    print("-" * 60)
    if failed:
        print(f"❌ {failed}/{len(tests)} 個測試失敗")
        sys.exit(1)
    print(f"✅ {len(tests)} 個測試全部通過（完全沒打網路）")
