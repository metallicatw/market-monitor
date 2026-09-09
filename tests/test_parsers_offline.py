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


def test_tw_market_cap():
    result, _ = run_with_fixture("fsc_t49_11138_market_overview", fmd.fetch_tw_market_cap)
    assert result is not None, "市值 parser 回 None"
    assert result["dates"] == ["2026-01-01", "2026-02-01", "2026-03-01",
                               "2026-04-01", "2026-05-01"], result["dates"]
    # 原始檔 202605 是 158010.38 十億元 -> 158,010,380 百萬元
    assert abs(result["market_cap"][-1] - 158_010_380) < 1, result["market_cap"][-1]
    assert result["listed_count"][-1] == 1968, result["listed_count"][-1]
    print(f"  市值 ok：來源給 {len(result['dates'])} 個月（滾動視窗），"
          f"最新 {result['dates'][-1]} = {result['market_cap'][-1]/1e6:.2f} 兆元")


def test_market_cap_merge_never_shrinks_history():
    """
    來源只回最近 5 個月。如果寫檔是覆蓋而不是合併，
    每跑一次就會把辛苦累積的歷史砍成 5 個月 —— 而且不會報錯。
    """
    stub = _StubHTTP(sample("fsc_t49_11138_market_overview"))
    orig_get, orig_dir = fmd._http_get, fmd.DATA_DIR
    with tempfile.TemporaryDirectory() as tmp:
        fmd._http_get, fmd.DATA_DIR = stub, tmp
        try:
            # 先假裝本地已經累積了 2024 年的歷史
            history = {
                "dates": [f"2024-{m:02d}-01" for m in range(1, 13)],
                "market_cap": [70_000_000 + m * 100_000 for m in range(1, 13)],
                "listed_count": [1800 + m for m in range(1, 13)],
            }
            with open(os.path.join(tmp, "tw_market_cap.json"), "w", encoding="utf-8") as f:
                json.dump(history, f)

            result = fmd.fetch_tw_market_cap(incremental=True)
            assert result is not None
            assert len(result["dates"]) == 17, f"12 個月歷史 + 5 個月新資料應該是 17，實際 {len(result['dates'])}"
            assert result["dates"][0] == "2024-01-01", "舊歷史被洗掉了"
            assert result["dates"][-1] == "2026-05-01"
        finally:
            fmd._http_get, fmd.DATA_DIR = orig_get, orig_dir
    print("  市值合併 ok：舊歷史 12 個月 + 新 5 個月 = 17 個月，沒有被覆蓋")


def test_market_cap_keeps_cache_when_source_fails():
    """來源掛掉時，既有快取必須原封不動 —— 不能寫出一個空的或殘缺的檔。"""
    def boom(url, timeout=20):
        raise OSError("simulated connection reset")

    orig_get, orig_dir = fmd._http_get, fmd.DATA_DIR
    with tempfile.TemporaryDirectory() as tmp:
        fmd._http_get, fmd.DATA_DIR = boom, tmp
        fmd_sleep = fmd.time.sleep
        fmd.time.sleep = lambda *_a, **_k: None  # 測試不要真的等重試 backoff
        try:
            history = {"dates": ["2024-01-01"], "market_cap": [70_000_000], "listed_count": [1800]}
            path = os.path.join(tmp, "tw_market_cap.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(history, f)

            result = fmd.fetch_tw_market_cap(incremental=True)
            with open(path, encoding="utf-8") as f:
                on_disk = json.load(f)
            assert on_disk == history, "來源失敗卻動到了既有快取"
            assert result == history
        finally:
            fmd._http_get, fmd.DATA_DIR = orig_get, orig_dir
            fmd.time.sleep = fmd_sleep
    print("  市值失敗保護 ok：來源掛掉時快取原封不動")


def test_ratio_alignment_and_magnitude():
    """
    市值貨幣比：只算「兩邊都有的月份」。
    M1B 比市值新，多出來的月份不能拿舊市值去湊。
    """
    orig_dir = fmd.DATA_DIR
    with tempfile.TemporaryDirectory() as tmp:
        fmd.DATA_DIR = tmp
        try:
            cap, _ = run_with_fixture("fsc_t49_11138_market_overview", fmd.fetch_tw_market_cap)
            m1b, _ = run_with_fixture("cbc_ef15m01_money_aggregates", fmd.fetch_tw_m1b, years_back=50)
            # run_with_fixture 用的是它自己的暫存目錄，這裡重新寫進本測試的目錄
            for name, payload in (("tw_market_cap.json", cap), ("tw_m1b.json", m1b)):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                    json.dump(payload, f)

            result = fmd.compute_tw_marketcap_m1b_ratio()
            assert result is not None
            # 市值只到 202605，所以比值也只能到 202605（M1B 有到 202607）
            assert result["dates"][-1] == "2026-05-01", result["dates"][-1]
            assert len(result["dates"]) == 5, result["dates"]
            expected = [3.81, 4.13, 3.72, 4.56, 5.16]
            for got, want in zip(result["ratio"], expected):
                assert abs(got - want) < 0.01, f"比值 {got} 與預期 {want} 不符"
            print(f"  市值貨幣比 ok：{result['dates'][0]}~{result['dates'][-1]}，"
                  f"比值 {[round(r,2) for r in result['ratio']]}")
        finally:
            fmd.DATA_DIR = orig_dir


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
