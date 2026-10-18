# -*- coding: utf-8 -*-
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

    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def __call__(self, url, timeout=20):
        self.urls.append(url)
        return self.payload


class _RoutingHTTP:

    def __init__(self, routes, missing=None):
        self.routes = routes
        self.missing = missing or ()
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
    stub = _RoutingHTTP(routes or MARKET_CAP_ROUTES, missing)
    orig_get, orig_post, orig_dir = fmd._http_get, fmd._http_post, fmd.DATA_DIR
    orig_sleep = fmd.time.sleep
    with tempfile.TemporaryDirectory() as tmp:
        fmd._http_get = stub
        fmd._http_post = lambda url, data, timeout=30: stub(url)
        fmd.DATA_DIR = tmp
        fmd.time.sleep = lambda *_a, **_k: None
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
    stub = _StubHTTP(sample(fixture_name))
    orig_get, orig_dir = fmd._http_get, fmd.DATA_DIR
    with tempfile.TemporaryDirectory() as tmp:
        fmd._http_get, fmd.DATA_DIR = stub, tmp
        try:
            return fn(incremental=False, **kwargs), stub
        finally:
            fmd._http_get, fmd.DATA_DIR = orig_get, orig_dir




def test_tw_pmi():
    result, _ = run_with_fixture("ndc_pmi_ndc6100", fmd.fetch_tw_pmi, years_back=50)
    assert result is not None, "PMI parser 回 None"
    assert result["dates"][0] == "2012-07-01", result["dates"][0]
    assert result["dates"][-1] == "2026-08-01", result["dates"][-1]
    assert result["pmi"][-1] == 62.5, result["pmi"][-1]
    assert result["nmi"][-1] == 55.6, result["nmi"][-1]
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
    result, _ = run_with_fixture("cbc_ef19m01_m1b_factors", fmd.fetch_tw_m1b, years_back=50)
    assert result is None, "抓到變動額檔案卻沒被擋下來，這正是會靜靜出錯的那種 bug"
    print("  M1B 反向測試 ok：EF19M01（變動額）有被擋下來")


def test_tw_market_cap_sums_two_sources():
    result, _, stub = run_market_cap(incremental=False)
    assert result is not None, "市值 parser 回 None"
    assert len(result["dates"]) >= 120, \
        f"接了長歷史來源之後不該只有 {len(result['dates'])} 個月"
    assert result["dates"][0] == "2016-01-01", result["dates"][0]
    i = result["dates"].index("2026-07-01")
    assert abs(result["market_cap"][i] - (140_848_179 + 9_526_934.205226)) < 1, \
        result["market_cap"][i]
    joined = " ".join(stub.urls)
    for frag in ("EG27M01", "monthlyRptMkt", "datasets/11138"):
        assert frag in joined, f"{frag} 沒有被請求"
    print(f"  市值 ok：{len(result['dates'])} 個月 {result['dates'][0]}～{result['dates'][-1]}，"
          f"最新 {result['market_cap'][-1]/1e6:.2f} 兆元")


def test_market_cap_reconciles_against_t49():
    result, _, _ = run_market_cap(incremental=False)
    assert result["reconciled_months"] >= 4, \
        f"只對帳到 {result['reconciled_months']} 個月，t49 的滾動視窗是不是變了？"
    assert result["reconcile_mismatches"] == 0, \
        f"有 {result['reconcile_mismatches']} 個月對不上 t49"
    print(f"  對帳 ok：{result['reconciled_months']} 個重疊月份與 t49 完全相符")


def test_market_cap_only_writes_months_both_sources_have():
    result, _, _ = run_market_cap(incremental=False)
    assert result["dates"][0] >= "2016-01-01", \
        f"寫進了櫃買沒有資料的月份：{result['dates'][0]}"


def test_market_cap_merge_never_shrinks_history():
    history = {
        "dates": [f"2015-{m:02d}-01" for m in range(1, 13)],
        "market_cap": [50_000_000 + m * 100_000 for m in range(1, 13)],
        "listed_count": [1700 + m for m in range(1, 13)],
    }
    result, _, _ = run_market_cap(existing=history)
    assert result["dates"][0] == "2015-01-01", "舊歷史被洗掉了"
    assert len(result["dates"]) > 120


def test_market_cap_keeps_cache_when_a_source_fails():
    history = {"dates": ["2024-01-01"], "market_cap": [70_000_000], "listed_count": [1800]}
    for missing in ("EG27M01", "monthlyRptMkt"):
        result, on_disk, _ = run_market_cap(missing=(missing,), existing=history)
        assert on_disk == history, f"{missing} 失敗時卻動到了既有快取"
        assert result == history
    print("  失敗保護 ok：上市、上櫃任一支掛掉都不動既有快取")


def test_market_cap_survives_t49_being_gone():
    result, _, _ = run_market_cap(missing=("datasets/11138",), incremental=False)
    assert result is not None, "對帳來源掛掉不該讓主資料一起失敗"
    assert len(result["dates"]) >= 120
    assert result["reconciled_months"] == 0
    print("  t49 降級 ok：對帳來源掛掉，主資料照樣寫入（只是沒有對帳）")


def test_ods_parser_reads_the_right_column_by_name():
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
            assert result["dates"][-1] == "2026-07-01", result["dates"][-1]
            assert result["dates"][0] == "2016-01-01", result["dates"][0]
            assert len(result["dates"]) == len(cap["dates"]), \
                "比值的月份數應該等於市值的月份數（M1B 覆蓋更長）"
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
    from datetime import date as _date
    raw = ("observation_date,UNRATE\n"
           "2026-05-01,4.0\n"
           "2026-06-01,.\n"
           "2026-07-01,4.1\n")
    dates, values = fmd._parse_fred_csv(raw, "UNRATE", _date(2020, 1, 1))
    assert dates == ["2026-05-01", "2026-07-01"], dates
    assert values == [4.0, 4.1], values
    print("  FRED parser ok：缺值 '.' 有被跳過而不是變成 0")


def test_twse_mi_index_really_has_no_market_cap():
    tables = json.loads(sample("twse_mi_index_tables_20260831").decode("utf-8"))["tables"]
    all_fields = [f for t in tables if t.get("fields") for f in t["fields"]]
    assert all_fields, "fixture 壞了"
    assert not any("市值" in f for f in all_fields), \
        "MI_INDEX 竟然出現市值欄位了？那可以改用它當更即時的來源"
    print(f"  TWSE MI_INDEX ok：{len(tables)} 張表 / {len(all_fields)} 個欄位，確認沒有市值")


def test_every_us_indicator_chart_is_wired_to_a_canvas_that_exists():
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
        assert "usfrUMCSENT" not in canvases, "密大消費者信心被畫了第二次"
        for meta, _ in members:
            assert meta["name"] in html
        drawn += len(canvases)
    assert drawn >= 10, f"只接上了 {drawn} 條，預期十一條左右"
    print(f"  美股指標歷史線 ok：{drawn} 條，各自一張圖、一條軸")


def test_密大信心照樣抓只是不在那一組裡畫():
    import generate_report_local as grl

    series = {m["id"]: m for m in grl.load_fred_series(include_disabled=True)}
    umc = series.get("UMCSENT")
    assert umc, "UMCSENT 整筆不見了——底下那塊 VIX＆密大信心會跟著空掉"

    assert umc.get("enabled", True) is True, (
        "UMCSENT 被關掉了。這樣 data/michigan.json 不會再更新，而底下那一塊"
        "〔VIX 恐慌指數 ＆ 密大消費者信心〕讀的就是它——畫面上不會報錯，只會"
        "永遠停在最後一次抓到的那一天。要拿掉趨勢圖請用 in_group=False。"
    )
    assert umc.get("cache") == "michigan.json", (
        "UMCSENT 的快取檔名被改了。底下那一塊寫死讀 michigan.json，"
        "改了檔名等於把那一塊斷線。"
    )
    assert umc.get("in_group") is False, (
        "UMCSENT 又回到〔房地產與信心〕那一組了——同一條線會在同一頁出現兩次。"
    )

    assert "UMCSENT" in {m["id"] for m in grl.load_fred_series()}, \
        "UMCSENT 從要抓的清單裡消失了"

    fake = {"dates": ["2026-07-01", "2026-08-01"], "close": [58.2, 55.2]}
    group = {"key": "housing_sentiment", "label": "🏠 房地產與信心"}
    html, script = grl.render_us_indicator_group(group, [(umc, fake)])
    assert "密大消費者信心" in html, "數值卡也被拿掉了——這一組會只剩房地產"
    assert "55.2" in html, "數值卡沒有數字"
    assert "usfrUMCSENT" not in html, "趨勢圖還在"
    assert "usfrUMCSENT" not in script, "趨勢圖的 JS 還在"
    print("  密大信心 ok：照樣抓（michigan.json）、數值卡還在、只是不再畫第二張圖")


def test_the_report_lets_you_change_the_list_without_leaving_the_page():
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

    assert set(options) == set(grl.MANAGE_ACTIONS) | set(grl.CARD_ACTIONS), (
        sorted(options), sorted(set(grl.MANAGE_ACTIONS) | set(grl.CARD_ACTIONS))
    )
    assert not set(grl.MANAGE_ACTIONS) & set(grl.CARD_ACTIONS), "同一個動作有兩個入口"
    for name in grl.MANAGE_ACTIONS:
        assert f'<option value="{name}">' in bar, f"選單裡少了「{name}」"
    for name in grl.CARD_ACTIONS:
        assert f'<option value="{name}">' not in bar, f"「{name}」不該還留在選單裡"

    for key in ("action", "code", "price_buy", "per_buy", "years"):
        assert f"{key}:" in wf, f"workflow 沒有 {key} 這個 input"
        assert key in bar, f"表單沒有送出 {key}"
    print(f"  管理表單 ok：選單 {len(grl.MANAGE_ACTIONS)} 個動作"
          f"＋股票旁邊 {len(grl.CARD_ACTIONS)} 個，5 個欄位")


def test_every_field_says_what_it_is_and_what_its_default_is():
    import generate_report_local as grl

    wf = open(os.path.join(BASE_DIR, ".github", "workflows",
                           grl.MANAGE_WORKFLOW), encoding="utf-8").read()
    bar = grl.render_manage_bar()
    for key, text in grl.MANAGE_FIELD_HINTS.items():
        assert f'description: "{text}"' in wf, f"{key} 的說明和 workflow 不一樣"
        assert f'<span class="mm-lab">{text}' in bar, f"{key} 的說明沒有寫在欄位上面"
    form = bar[bar.index("<form"):bar.index("</form>")]
    assert "placeholder=" not in form, "說明又被塞回 placeholder 了，長的那幾句會被截掉"
    assert bar.count('class="mm-lab"') == len(grl.MANAGE_FIELD_HINTS)
    print(f"  {len(grl.MANAGE_FIELD_HINTS)} 個欄位的說明寫在欄位上面，和 workflow 一致")


def test_every_button_sends_a_code_the_workflow_will_accept():
    import re

    import generate_report_local as grl

    wf = open(os.path.join(BASE_DIR, ".github", "workflows",
                           grl.MANAGE_WORKFLOW), encoding="utf-8").read()
    assert "*[!0-9A-Za-z]*" in wf, "workflow 的代號檢查改了，這條測試要跟著改"
    ok = re.compile(r"^[0-9A-Za-z]+$")

    stocks = grl.load_jp_stocks(include_disabled=True)
    assert stocks, "設定裡一檔都沒有"
    for s in stocks:
        assert ok.match(s["key"]), f'檔名代號 {s["key"]!r} 過不了 workflow 那一關'

    row = grl.render_hidden_row(stocks[:3])
    for sent in re.findall(r'data-code="([^"]*)"', row):
        assert ok.match(sent), f"隱藏列送出 {sent!r}，workflow 會退回來"
    print(f"  {len(stocks)} 檔的代號都過得了 workflow 那一關")


def test_hiding_a_stock_is_not_a_one_way_door():
    import generate_report_local as grl

    row = grl.render_hidden_row([
        {"key": "testco", "code": "9999.T", "name": "測試公司"},
    ])
    assert "恢復顯示" in row, "那一列不會送出〔恢復顯示〕"
    assert 'data-code="testco"' in row, "代號沒有跟著按鈕走"
    assert 'data-code="9999.T"' not in row, "又送 Yahoo ticker 了，workflow 會退回來"
    assert "9999.T" in row, "畫面上要看得到代號"
    assert "測試公司" in row
    assert 'id="mm-hidden-row"' in row, "沒有 id，JS 找不到這一列"

    empty = grl.render_hidden_row([])
    assert 'id="mm-hidden-row"' in empty, "空的時候整列不見了，第一次隱藏會沒地方掛"
    assert " hidden>" in empty, "空的那一列沒有藏起來"
    assert "hidden-chip" not in empty, "空的卻長了 chip 出來"
    assert " hidden>" not in row, "有隱藏個股卻把整列藏起來"
    print("  〔恢復顯示〕有家了（空的時候容器還在，只是藏著）")


def test_那三顆按鈕的圖示是自己畫的不是_emoji():
    import json as _json

    import generate_report_local as grl

    icons = {"ICON_EYE": grl.ICON_EYE, "ICON_EYE_OFF": grl.ICON_EYE_OFF,
             "ICON_TRASH": grl.ICON_TRASH}
    for name, svg in icons.items():
        assert svg.startswith("<svg") and svg.endswith("</svg>"), f"{name} 不是一張 SVG"
        assert "currentColor" in svg, f"{name} 沒吃 currentColor，hover 變色時會卡住"
        assert "<path" in svg, f"{name} 是空的"
    assert len(set(icons.values())) == 3, "三顆圖示裡有重複的"

    import inspect

    src = inspect.getsource(grl.render_jp_stock_section)
    acts = src.split("actions_html = (", 1)[1].split("\n    )", 1)[0]
    assert "{ICON_EYE_OFF}" in acts, "隱藏鈕沒有用閉眼圖示"
    assert "{ICON_TRASH}" in acts, "移除鈕沒有用垃圾桶圖示"
    assert acts.count("aria-label=") == 2, "那兩顆按鈕沒有各自的名字"

    bar = grl.render_manage_bar()
    assert _json.dumps(grl.ICON_EYE) in bar, (
        "JS 那一側畫的還原鈕沒有用 ICON_EYE。兩邊各寫一份的話，"
        "剛按下閉眼長出來的那顆、和重新整理之後畫出來的那顆會長得不一樣。"
    )
    for bad in ("🙈", "🗑", "👁"):
        assert bad not in bar, f"管理列裡還留著 {bad}"
    print("  圖示 ok：三張各自的 SVG，伺服器和 JS 畫的是同一顆眼睛")


def test_no_credential_is_ever_baked_into_the_report():
    import re

    import generate_report_local as grl

    bar = grl.render_manage_bar()
    for prefix in ("github_pat_", "ghp_", "gho_", "ghs_", "ghu_"):
        for m in re.finditer(re.escape(prefix) + r"[A-Za-z0-9_]{4,}", bar):
            raise AssertionError(f"HTML 裡有疑似權杖：{m.group(0)[:20]}…")
    assert "localStorage" in bar, "權杖應該存在瀏覽器，不是別的地方"
    assert "api.github.com" in bar
    hosts = set(re.findall(r"https://([a-z0-9.\-]+)", bar))
    assert hosts <= {"api.github.com", "github.com"}, hosts
    print("  報告裡沒有任何憑證，權杖只送 api.github.com")


def test_the_manage_link_survives_a_local_regeneration():
    import generate_report_local as grl

    saved = os.environ.pop("GITHUB_REPOSITORY", None)
    try:
        url = grl.manage_url()
    finally:
        if saved is not None:
            os.environ["GITHUB_REPOSITORY"] = saved
    assert url.endswith("/actions/workflows/" + grl.MANAGE_WORKFLOW), url
    assert url.count("/") >= 6, f"repo 段沒解析出來：{url}"
    print(f"  本機也拿得到網址：{url}")


def test_toggling_one_stock_does_not_refetch_the_whole_world():
    wf = os.path.join(BASE_DIR, ".github", "workflows", "manage.yml")
    with open(wf, encoding="utf-8") as f:
        body = f.read()
    step = body.split("更新資料並產生報告", 1)[1].split("有變動才提交", 1)[0]

    for action in ("隱藏個股", "移除個股"):
        assert action in step, f"{action} 沒有走到快的那條路"
    fast = step.split('"隱藏個股"|"移除個股")', 1)[1].split(";;", 1)[0]
    assert "run.py report" in fast, "隱藏／移除沒有改用只重畫報告的那條路"
    assert "run.py update" not in fast, "隱藏／移除還是在重抓整個世界"

    show = step.split('"恢復顯示")', 1)[1].split(";;", 1)[0]
    assert "--only" in show, "恢復顯示沒有用 --only，等於又把整個世界重抓一遍"
    assert "run.py update" not in show, "恢復顯示還是在重抓整個世界"

    src = os.path.join(BASE_DIR, "fetch_market_data.py")
    with open(src, encoding="utf-8") as f:
        fetch_src = f.read()
    assert '"--only"' in fetch_src, "fetch_market_data.py 不認得 --only"
    print("  隱藏／移除只重畫報告；恢復顯示只補抓那一檔")


def test_every_action_either_shows_up_at_once_or_refreshes_when_it_is_done():
    import generate_report_local as grl

    every = set(grl.MANAGE_ACTIONS) | set(grl.CARD_ACTIONS)
    local = set(grl.LOCAL_FIRST_ACTIONS)
    rebuild = set(grl.REBUILD_ACTIONS)
    assert local | rebuild == every, f"沒有分類到的動作：{every - (local | rebuild)}"
    assert not (local & rebuild), f"同時屬於兩類：{local & rebuild}"

    bar = grl.render_manage_bar()
    for action in local:
        assert f'"{action}": 1' in bar.split("MM_NEEDS_REBUILD", 1)[0], \
            f"{action} 沒進 MM_LOCAL_FIRST"
    for action in rebuild:
        assert f'"{action}": 1' in bar.split("MM_NEEDS_REBUILD", 1)[1].split("\n", 1)[0], \
            f"{action} 沒進 MM_NEEDS_REBUILD"
    assert "location.replace" in bar, "跑完沒有自動重新整理"
    assert "mmLocalRevert" in bar, "失敗之後沒有把畫面還原回去的路"
    print(f"  {len(local)} 個立即反映、{len(rebuild)} 個跑完自動重整，沒有漏的")



def test_密大官網表格讀得出終值():
    dates, vals = fmd.parse_michigan_table(sample("michigan_tbmics"))
    got = dict(zip(dates, vals))
    assert got["2026-07-01"] == 55.2 and got["2026-08-01"] == 51.7, (dates[-3:], vals[-3:])
    assert dates == sorted(dates), "月份沒有照順序"
    assert all(d.endswith("-01") for d in dates), "日期要和 FRED 一樣是該月 1 號"
    assert 40 < min(vals[-120:]) and max(vals[-120:]) < 120, "量級不對（是不是讀到別的欄？）"
    print(f"  表格 ok：{len(dates)} 個月，最新 {dates[-1][:7]} = {vals[-1]}")


def test_密大官網首頁讀得出當月初值與下次發布日():
    home = fmd.parse_michigan_home(sample("michigan_home"))
    assert home == {
        "month": "2026-09-01", "value": 47.8, "status": "preliminary",
        "next_release": {"date": "2026-09-25", "what": "final", "month": 9},
    }, home
    print("  首頁 ok：2026-09 初值 47.8，9/25 終值")


def test_密大首頁改成終值也認得():
    html = (b"<h3>Final Results for September 2026</h3><table><tr><td>Index of Consumer "
            b"Sentiment</td><td>48.1</td><td>51.7</td></tr></table>"
            b"Next data release: Friday, October 9, 2026 for Preliminary October data at 10am ET")
    home = fmd.parse_michigan_home(html)
    assert home["status"] == "final" and home["value"] == 48.1, home
    assert home["next_release"] == {"date": "2026-10-09", "what": "preliminary", "month": 10}


def test_密大首頁認不出來就回_None_不猜():
    assert fmd.parse_michigan_home(b"<html>maintenance</html>") is None


def test_密大官網疊上去之後最新值是官方的():
    fred = {"series_id": "UMCSENT", "name": "密大消費者信心",
            "dates": ["2026-05-01", "2026-06-01", "2026-07-01"], "close": [44.8, 49.5, 55.2]}
    table = fmd.parse_michigan_table(sample("michigan_tbmics"))
    home = fmd.parse_michigan_home(sample("michigan_home"))
    out = fmd.merge_michigan_official(fred, table, home)
    assert out["dates"][-3:] == ["2026-07-01", "2026-08-01", "2026-09-01"], out["dates"][-3:]
    assert out["close"][-3:] == [55.2, 51.7, 47.8], out["close"][-3:]
    assert out["prelim"] == ["2026-09-01"]
    assert out["dates"][0] == "2026-05-01", "表格從 1952 年開始，不該把既有序列的視窗撐大"


def test_密大終值出來之後初值標記會拿掉():
    prev = {"dates": ["2026-08-01", "2026-09-01"], "close": [51.7, 47.8],
            "prelim": ["2026-09-01"], "next_release": {"date": "2026-09-25"}}
    table = (["2026-08-01", "2026-09-01"], [51.7, 48.1])
    out = fmd.merge_michigan_official(prev, table, None)
    assert out["close"][-1] == 48.1, "終值沒有蓋過初值"
    assert out["prelim"] == [], "終值出來了，初值標記還在"


def test_密大首頁那天沒抓到_初值標記要留著():
    prev = {"dates": ["2026-08-01", "2026-09-01"], "close": [51.7, 47.8],
            "prelim": ["2026-09-01"], "next_release": {"date": "2026-09-25"}}
    out = fmd.merge_michigan_official(prev, (["2026-08-01"], [51.7]), None)
    assert out["prelim"] == ["2026-09-01"] and out["close"][-1] == 47.8
    assert out["next_release"] == {"date": "2026-09-25"}


def test_FRED那一步不會把初值標記洗掉():
    import json as _json
    tmp = tempfile.mkdtemp()
    old_dir, old_get = fmd.DATA_DIR, fmd._http_get
    try:
        fmd.DATA_DIR = tmp
        with open(os.path.join(tmp, "michigan.json"), "w", encoding="utf-8") as f:
            _json.dump({"dates": ["2026-07-01", "2026-09-01"], "close": [55.2, 47.8],
                        "prelim": ["2026-09-01"], "next_release": {"date": "2026-09-25"},
                        "official_source": fmd.MICHIGAN_HOME_URL}, f)
        fmd._http_get = _StubHTTP(b"observation_date,UMCSENT\n2026-07-01,55.2\n")
        out = fmd.fetch_fred_series("UMCSENT", cache_name="michigan.json", years_back=25)
    finally:
        fmd.DATA_DIR, fmd._http_get = old_dir, old_get
    assert out["prelim"] == ["2026-09-01"], out
    assert out["next_release"] == {"date": "2026-09-25"}
    assert out["dates"][-1] == "2026-09-01", "FRED 那一步把初值那個月弄丟了"


def test_密大官網每天真的有被叫到():
    src = open(os.path.join(BASE_DIR, "fetch_market_data.py"), encoding="utf-8").read()
    main = src[src.index('if __name__ == "__main__":'):]
    fred_at = main.index("fetch_fred_series,")
    official_at = main.index("fetch_michigan_official")
    assert official_at > fred_at, "官網那一步要排在 FRED 後面（同一個檔，後寫的贏）"


def test_報告上標出初值與官網的下次發布日():
    import generate_report_local as grl
    from datetime import date, timedelta
    soon = (date.today() + timedelta(days=2)).isoformat()
    mi = {"dates": ["2026-08-01", "2026-09-01"], "close": [51.7, 47.8],
          "prelim": ["2026-09-01"], "official_source": fmd.MICHIGAN_HOME_URL,
          "next_release": {"date": soon, "what": "final", "month": 9}}
    txt = grl.michigan_vintage(mi)
    assert "2026-09" in txt and "初值" in txt and "9月終值" in txt, txt
    assert "延遲一個月" not in txt, "有官網資料的時候不該再說 FRED 延遲一個月"
    html, _ = grl.render_michigan_section(mi)
    assert "2026/09 初值" in html, "數值卡沒有標初值"
    assert "sca.isr.umich.edu" in html, "來源沒有指到官網"
    mi2 = dict(mi, prelim=[])
    assert "終值" in grl.michigan_vintage(mi2) and "初值" not in grl.michigan_vintage(mi2).split("｜")[0]


def test_摘要徽章和數值卡用同一個區間名稱():
    import generate_report_local as grl
    src = open(os.path.join(BASE_DIR, "generate_report_local.py"), encoding="utf-8").read()
    assert '<span class="chip warn solid">衰退警戒</span>' not in src
    assert grl.michigan_zone(47.8)[0] == "系統危機"


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
