# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _with_config(config_text):
    import contextlib

    import config_loader

    @contextlib.contextmanager
    def _cm():
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            if config_text is not None:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(config_text)
            original = config_loader.CONFIG_PATH
            config_loader.CONFIG_PATH = path
            try:
                yield config_loader
            finally:
                config_loader.CONFIG_PATH = original

    return _cm()




def test_設定檔壞掉不會安靜地退回內建清單():
    import config_loader

    broken = '{"jp_stocks": [ {"code": "6981.T",, ] }'
    with _with_config(broken) as cl:
        try:
            cl._load_raw()
        except cl.ConfigBroken as exc:
            assert "config.json" in str(exc)
            assert "不產生報告" in str(exc), "訊息沒有說清楚這次不會產出東西"
        else:
            raise AssertionError(
                "設定檔壞掉卻沒有丟 ConfigBroken——會退回內建的 10 檔，"
                "報告上少六檔而沒有任何一個字說少了東西"
            )
    assert issubclass(config_loader.ConfigBroken, Exception)


def test_設定檔不存在仍然用內建預設():
    with _with_config(None) as cl:
        assert cl._load_raw() == {}, "檔案不存在的時候應該回空 dict 走預設"


def test_設定檔正常的時候原樣讀回來():
    payload = {"jp_stocks": [{"code": "6981.T", "key": "murata", "name": "村田"}]}
    with _with_config(json.dumps(payload, ensure_ascii=False)) as cl:
        assert cl._load_raw() == payload


def test_壞掉的設定檔印的是一句人話不是_traceback():
    import io
    import contextlib

    import config_loader

    err = io.StringIO()
    exc = config_loader.ConfigBroken("config.json 格式錯誤（第 12 行）。\n   細節……")
    with contextlib.redirect_stderr(err):
        try:
            config_loader._config_broken_excepthook(
                type(exc), exc, exc.__traceback__)
        except SystemExit as bye:
            assert bye.code == 1, f"結束碼是 {bye.code}，排程不會當成失敗"
        else:
            raise AssertionError("設定檔壞掉卻沒有讓程式以非 0 結束")
    text = err.getvalue()
    assert "config.json 格式錯誤" in text, text
    assert "Traceback" not in text, "還是吐了 traceback"


def test_其他例外不會被這個_hook_吃掉():
    import config_loader

    seen = []
    original = config_loader._PREVIOUS_EXCEPTHOOK
    try:
        config_loader._PREVIOUS_EXCEPTHOOK = lambda k, v, tb: seen.append(v)
        boom = ValueError("別的問題")
        config_loader._config_broken_excepthook(
            type(boom), boom, boom.__traceback__)
    finally:
        config_loader._PREVIOUS_EXCEPTHOOK = original
    assert seen and isinstance(seen[0], ValueError), "ValueError 被這個 hook 吃掉了"


def test_hook_真的裝上去了():
    import config_loader

    assert sys.excepthook is config_loader._config_broken_excepthook, (
        "config_loader 沒有把 excepthook 裝上去——壞掉的設定檔還是會吐 traceback"
    )




def _run_taiex(*, months_fail, cached_rows):
    import fetch_market_data as fmd

    def boom(*a, **k):
        raise TimeoutError("測試裡不打網路")

    def payload(*a, **k):
        return {"data": [["115/09/18", "1,000", "2,000", "3", "20,000.5", "1.0"]]}

    real_fetch = fmd._fetch_json_with_retry
    real_sleep = fmd.time.sleep
    real_load = fmd._load_cache
    real_write = fmd._write_json
    saved = {}
    try:
        fmd._fetch_json_with_retry = boom if months_fail else payload
        fmd.time.sleep = lambda *a, **k: None
        fmd._load_cache = lambda name: cached_rows
        fmd._write_json = lambda path, obj: saved.update({path: obj})
        return fmd.fetch_taiex(years_back=1, sleep_sec=0), saved
    finally:
        fmd._fetch_json_with_retry = real_fetch
        fmd.time.sleep = real_sleep
        fmd._load_cache = real_load
        fmd._write_json = real_write


def test_taiex_一個月都沒抓到要回_None():
    stale = {"dates": ["2026-09-04"], "close": [20000.0],
             "volume_shares": [1.0], "value_twd": [1.0]}
    result, _ = _run_taiex(months_fail=True, cached_rows=stale)
    assert result is None, (
        "一天新資料都沒拿到，卻回了一個非 None 的 dict。上層只看 None，"
        f"所以這會被算成「成功更新」：{str(result)[:200]}"
    )


def test_taiex_有抓到東西就正常回傳():
    result, _ = _run_taiex(months_fail=False, cached_rows=None)
    assert result is not None, "抓得到卻回了 None"
    assert result.get("dates"), f"回了東西但沒有日期：{str(result)[:200]}"


def test_taiex_沒有新交易日但也沒有失敗不算失敗():
    import fetch_market_data as fmd
    import inspect

    src = inspect.getsource(fmd.fetch_taiex)
    assert "failed_months and not out_dates" in src, (
        "判斷只看了 `out_dates`——沒有新交易日的日子會被當成失敗，每天紅一次"
    )


def test_上層把_None_算成失敗():
    import inspect

    import fetch_market_data as fmd

    src = inspect.getsource(fmd)
    main = src.split('if __name__ == "__main__":', 1)[1]
    assert "def _run(" in main, "找不到 `_run`"
    runner = main.split("def _run(", 1)[1].split("\n    print(", 1)[0]
    assert "if result is None" in runner and "failures.append" in runner, (
        "`_run` 沒有把 None 算成失敗，`fetch_taiex` 回 None 也沒有意義"
    )





def test_沒有電腦版手機版切換鈕():
    import inspect

    import generate_report_local as grl

    src = inspect.getsource(grl)
    for gone in ("modeToggleBtn", "mode-toggle-btn", "toggleViewMode", "applyViewMode",
                 "hideToggleWhenEmbedded", "force-mobile", "force-desktop", "header-actions"):
        assert gone not in src, f"{gone} 還在"




def test_月更新的來源落後兩個月要說是正常的():
    import generate_report_local as grl
    note = grl.vintage_note("2026-07-01", months_behind=2, freq="月",
                            normal_lag=grl.TW_MC_M1B_NORMAL_LAG)
    assert "2026/07" in note
    assert "目前最新" in note, f"沒有說這是來源最新的一筆：{note}"
    assert "stale" not in note, f"正常的落後不該染警示色：{note}"


def test_超過正常範圍還是要示警():
    import generate_report_local as grl
    note = grl.vintage_note("2026-05-01", months_behind=4, freq="月",
                            normal_lag=grl.TW_MC_M1B_NORMAL_LAG)
    assert "stale" in note and "落後 4 個月" in note, note


def test_沒給正常範圍的照舊():
    import generate_report_local as grl
    assert grl.vintage_note("2026-07-01", months_behind=2, freq="月") == (
        '<span class="vintage">資料月份 2026/07｜月頻</span>'
    )


def test_正常的落後不要寫進摘要列():
    import inspect

    import generate_report_local as grl
    src = inspect.getsource(grl)
    seg = src[src.index('stale_note = f"，資料月份'):]
    seg = seg[:seg.index("if last_ratio")]
    assert "TW_MC_M1B_NORMAL_LAG" in seg, seg
    assert "if behind and behind >" in seg, seg


def test_卡片真的把正常範圍傳進去():
    import inspect

    import generate_report_local as grl

    src = inspect.getsource(grl.render_tw_marketcap_m1b_section)
    assert "normal_lag=TW_MC_M1B_NORMAL_LAG" in src, (
        "市值貨幣比那張卡片沒有把正常落後範圍傳給 vintage_note"
    )


def test_說明文字沒有再說_M1B_只落後一個月():
    import explanations

    text = explanations.TIPS["tw_marketcap_m1b"][1]
    assert "M1B 落後一個月" not in text, "說明還寫著 M1B 只落後一個月"
    assert "落後一到兩個月" in text, text[:200]





def test_四支抓取器都要有空回應守門():
    import inspect

    import fetch_market_data as F

    for fn in (F.fetch_vix, F.fetch_nikkei, F.fetch_jp_stock, F.fetch_index):
        src = inspect.getsource(fn)
        assert "_stalled(" in src, f"{fn.__name__} 沒有空回應守門"
        assert "return None" in src.split("_stalled(")[1][:120], (
            f"{fn.__name__} 有守門但沒有真的回 None"
        )


def test_Yahoo回空的時候真的回None():
    import fetch_market_data as F

    cached = {"dates": ["2026-09-17", "2026-09-18"], "close": [1.0, 2.0],
              "fetched_at": "2026-09-18"}
    empty_chart = {"chart": {"result": [{
        "timestamp": [],
        "indicators": {"quote": [{"close": []}]},
    }]}}

    wrote = []
    orig = (F._load_cache, F._fetch_json_with_retry, F._write_json)
    F._load_cache = lambda *a, **k: cached
    F._fetch_json_with_retry = lambda *a, **k: empty_chart
    F._write_json = lambda path, obj: wrote.append(path)
    try:
        got = F.fetch_index("^DJI", "dji", name="道瓊工業指數")
    finally:
        F._load_cache, F._fetch_json_with_retry, F._write_json = orig

    assert got is None, (
        f"Yahoo 回了空的 chart，程式卻說成功：last={got and got['dates'][-1]}、"
        f"fetched_at={got and got.get('fetched_at')}"
    )
    assert not wrote, f"什麼都沒抓到卻還是寫了檔案：{wrote}"


def test_資料沒有前進就算失敗():
    import fetch_market_data as F

    old = {"dates": ["2026-09-17", "2026-09-18"], "close": [1.0, 2.0]}
    same = {"dates": ["2026-09-17", "2026-09-18"], "close": [1.0, 2.0]}
    assert F._stalled("測試", old, same), "資料一天都沒前進，卻不算失敗"

    ahead = {"dates": ["2026-09-17", "2026-09-18", "2026-09-19"],
             "close": [1.0, 2.0, 3.0]}
    assert not F._stalled("測試", old, ahead)

    filled = {"dates": ["2026-09-16", "2026-09-17", "2026-09-18"],
              "close": [0.5, 1.0, 2.0]}
    assert not F._stalled("測試", old, filled), "補了中間的洞卻被當成沒前進"


def test_還沒到下一個交易日不算失敗():
    import datetime as dt

    import fetch_market_data as F

    fri = {"dates": ["2026-10-15", "2026-10-16"], "close": [1.0, 2.0]}
    orig = F._today
    try:
        for today, stalled in [("2026-10-17", False), ("2026-10-19", False), ("2026-10-20", False),
                               ("2026-10-22", False), ("2026-10-23", True)]:
            F._today = lambda t=today: dt.date.fromisoformat(t)
            assert F._stalled("測試", fri, dict(fri)) is stalled, today
    finally:
        F._today = orig


def test_第一次跑沒有快照可以比():
    import fetch_market_data as F

    fresh = {"dates": ["2026-09-18"], "close": [1.0]}
    assert not F._stalled("測試", None, fresh)
    assert not F._stalled("測試", {"dates": []}, fresh)


def test_新的None不可以蓋掉舊的值():
    import fetch_market_data as F

    existing = {"dates": ["2026-06-01", "2026-07-01"], "pmi": [60.7, 61.5]}
    merged = F._merge_series(existing, ["2026-07-01", "2026-08-01"],
                             {"pmi": [None, 62.5]})
    assert merged["pmi"][1] == 61.5, (
        f"上游這次沒給 7 月的值，既有的 61.5 被挖成 {merged['pmi'][1]}"
    )
    assert merged["pmi"][2] == 62.5

    fixed = F._merge_series(existing, ["2026-07-01"], {"pmi": [61.9]})
    assert fixed["pmi"][1] == 61.9, "官方校正被擋掉了"

    added = F._merge_series(existing, ["2026-08-01"], {"pmi": [None]})
    assert added["dates"][-1] == "2026-08-01" and added["pmi"][-1] is None




def test_窗口過了的財報要算逾期而不是消失():
    import inspect

    import check_earnings_due as C

    src = inspect.getsource(C.main)
    assert "overdue" in src, "沒有「逾期」這一類"
    window = src[src.index("for qe in _quarter_end_dates"):]
    window = window[:window.index("nxt = _next_quarter_end")]
    assert "break  # 更早的季別就不用看了" not in window, (
        "還在用 break——窗口一過就什麼都偵測不到"
    )
    assert "overdue.append(item)" in window


def test_逾期要在Actions上留一個警告():
    import inspect

    import check_earnings_due as C

    src = inspect.getsource(C.main)
    assert "::warning title=有個股的財報逾期未更新" in src, (
        "逾期只印在 log 裡，Actions 摘要上看不到"
    )


def test_排程會跑財報偵測():
    wf = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".github/workflows/daily-update.yml"),
              encoding="utf-8").read()
    assert "check_earnings_due.py" in wf, (
        "偵測器沒有掛進排程——它就只會在有人手動跑的時候上班"
    )




def test_快照的本益比用現價():
    import generate_report_local as G

    stock = {
        "dates": ["2026-03-31", "2026-06-30", "2026-09-18"],
        "close": [1000.0, 1500.0, 2000.0],
    }
    annual = {
        "fiscal_years": ["FY26Q1", "FY26Q2", "FY26Q3", "FY26Q4"],
        "fiscal_year_end_dates": ["2025-06-30", "2025-09-30",
                                  "2025-12-31", "2026-03-31"],
        "eps_jpy": [25.0, 25.0, 25.0, 25.0],
    }
    got = G._latest_ttm_per(stock, annual)
    assert got == 20.0, f"用的不是今天的收盤（2000/100 = 20），而是 {got}"


def test_三份本益比實作合成一份():
    import inspect

    import generate_report_local as G

    assert hasattr(G, "ttm_eps_at"), "近四季 EPS 沒有抽成共用函式"
    src = inspect.getsource(G.render_jp_stock_section)
    assert "snap_per = _latest_ttm_per(stock, annual)" in src, (
        "卡片上的快照本益比沒有走共用的那一份"
    )


def test_近四季不齊就不算():
    import generate_report_local as G

    labels = ["FY26Q1", "FY26Q2", "FY26Q3", "FY26Q4"]
    assert G.ttm_eps_at([1.0, 2.0, 3.0, 4.0], labels, 3) == 10.0
    assert G.ttm_eps_at([1.0, None, 3.0, 4.0], labels, 3) is None
    assert G.ttm_eps_at([1.0, 2.0], labels[:2], 1) is None, "只有兩季卻算得出來"
    assert G.ttm_eps_at([7.0], ["FY26"], 0) == 7.0





def test_抓取層一律用台北時間():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "fetch_market_data.py"), encoding="utf-8").read()
    body = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#") and "原本是" not in ln)
    assert "date.today()" not in body, "還有地方在用 UTC 的 date.today()"
    assert "def _today():" in src


def test_閏日不會讓半個報告掛掉():
    import datetime as _dt

    import fetch_market_data as F

    real = F._today
    try:
        F._today = lambda: _dt.date(2028, 2, 29)
        for n in (5, 11, 25):
            got = F._years_ago(n)
            assert got == _dt.date(2028 - n, 2, 1), got
    finally:
        F._today = real


def test_上一次失敗的月份下一次要補回來():
    import inspect

    import fetch_market_data as F

    src = inspect.getsource(F.fetch_taiex)
    assert 'carried = [m for m in (existing or {}).get("failed_months"' in src, (
        "沒有把上一次失敗的月份排回請求清單"
    )
    assert 'months = sorted(set(months) | set(carried))' in src
    assert '"failed_months": sorted(set(failed_months))' in src, (
        "failed_months 還是整個覆寫"
    )


def test_缺了資料來源要印在頁面上():
    import generate_report_local as G

    _h, s = G.render_page_header([], {"dates": ["2026-09-18"]},
                                 missing=["vix.json", "個股 towa"])
    assert "本次報告缺少 2 個資料來源" in s, s[:300]
    assert "vix.json" in s and "個股 towa" in s

    _h2, s2 = G.render_page_header([], {"dates": ["2026-09-18"]})
    assert "缺少" not in s2, "沒缺東西卻掛了一條警告"


def test_市值只有單邊的月份要留下紀錄():
    import inspect

    import fetch_market_data as F

    src = inspect.getsource(F.fetch_tw_market_cap)
    assert '"skipped_months": skipped' in src, "少掉的月份沒有寫進檔案"
    assert "set(listed) ^ set(otc)" in src


def test_百分位的視窗是滾動的():
    import inspect

    import generate_report_local as G

    assert hasattr(G, "TW_MC_M1B_PCT_WINDOW")
    assert G.TW_MC_M1B_PCT_WINDOW >= 24, "視窗短到算不出有意義的百分位"
    src = inspect.getsource(G.render_tw_marketcap_m1b_section)
    assert "window = ratios[-TW_MC_M1B_PCT_WINDOW:]" in src
    assert "for r in window" in src, "百分位還是拿全部歷史算的"


def test_布局門檻只能是數字():
    wf = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".github/workflows/manage.yml"), encoding="utf-8").read()
    assert 'for v in "$IN_PRICE_BUY" "$IN_PER_BUY"' in wf, (
        "兩個門檻參數沒有經過驗證"
    )
    assert "布局門檻只能是數字" in wf



_WF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       ".github", "workflows")


def _workflow_texts():
    for name in sorted(os.listdir(_WF_DIR)):
        if name.endswith((".yml", ".yaml")):
            with open(os.path.join(_WF_DIR, name), encoding="utf-8") as fh:
                yield name, fh.read()


def _expression_problems(text):
    import re
    starts_ok = re.compile(r"[A-Za-z_(!'\-0-9]")
    bad = []
    for no, line in enumerate(text.splitlines(), 1):
        i = 0
        while True:
            i = line.find("${{", i)
            if i < 0:
                break
            j = line.find("}}", i + 3)
            if j < 0:
                bad.append((no, "沒有收尾的 }}"))
                break
            inner = line[i + 3:j].strip()
            if not inner:
                bad.append((no, "空的 ${{ }}"))
            elif not starts_ok.match(inner):
                bad.append((no, f"不像表達式：{inner!r}"))
            i = j + 2
    return bad


def test_workflow_裡沒有空的表達式():
    problems = {name: p for name, t in _workflow_texts() if (p := _expression_problems(t))}
    assert not problems, f"GitHub 會拒收這些 workflow：{problems}"


def test_掃描器真的抓得到上次那個錯():
    sample = (
        "        run: |\n"
        "          # 不是 RCE（沒有 eval，${{ }} 已經走\n"
        "          echo ok\n"
    )
    assert _expression_problems(sample) == [(2, "空的 ${{ }}")]
    assert _expression_problems("x: ${{ inputs.code") == [(1, "沒有收尾的 }}")]
    assert _expression_problems("x: ${{ … }}") == [(1, "不像表達式：'…'")]
    assert _expression_problems("x: ${{ inputs.code }} ${{ secrets.K }}") == []


def test_使用者輸入不直接內插進_run():
    import re
    offenders = []
    for name, text in _workflow_texts():
        run_indent = None
        for no, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if run_indent is not None:
                if stripped and indent <= run_indent:
                    run_indent = None
                elif "${{ inputs." in line or "${{ github.event.inputs." in line:
                    offenders.append(f"{name}:{no}")
                    continue
                else:
                    continue
            m = re.match(r"(\s*)(?:- )?run:\s*(.*)$", line)
            if m:
                if m.group(2).startswith(("|", ">")):
                    run_indent = len(m.group(1))
                elif "${{ inputs." in m.group(2):
                    offenders.append(f"{name}:{no}")
    assert not offenders, f"這些 run: 直接內插了使用者輸入，改走 env：{offenders}"



def _daily_wf():
    return open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             ".github/workflows/daily-update.yml"), encoding="utf-8").read()


def test_排程_早上美股_下午台日股_各有保險():
    import re
    wf = _daily_wf()
    crons = re.findall(r'cron:\s*"([^"]+)"', wf)
    assert crons == ["23 22 * * 1-5", "3 23 * * 1-5", "13 8 * * 1-5", "3 10 * * 1-5"], crons
    for c in crons:
        assert int(c.split()[0]) % 5, c
        assert c.split()[1] != "9", c
    assert '"3 23 * * 1-5") after="00:00"' in wf
    assert '"3 10 * * 1-5") after="16:00"' in wf
    assert "needs: gate" in wf and "needs.gate.outputs.skip != 'yes'" in wf
    assert "workflow_dispatch:" in wf and "concurrency:" in wf


def test_不再獨立發布網站_報告推到_report_分支():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("daily-update.yml", "manage.yml"):
        wf = open(os.path.join(root, ".github/workflows", name), encoding="utf-8").read()
        assert "deploy-pages" not in wf and "pages: write" not in wf, name
        assert "./.github/actions/publish-report" in wf, name
    act = open(os.path.join(root, ".github/actions/publish-report/action.yml"), encoding="utf-8").read()
    assert "report" in act and "push -q -f" in act


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
