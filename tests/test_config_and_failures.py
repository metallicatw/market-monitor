# -*- coding: utf-8 -*-
"""兩種「成功地產出一份錯的東西」。

這兩件事的形狀一模一樣：程式沒有 crash、結束碼是 0、job 全綠，而產出的東西
是錯的。它們都不是抓取失敗——抓取失敗很吵，很容易發現。

1. **config.json 被改壞** → 退回內建預設清單。實測：16 檔日股變成內建的 10
   檔，六檔從報告上消失，而消失的方式是「那幾張卡片不見了」，頁面上沒有任何
   一個字說少了東西。

2. **TAIEX 一個月都沒抓到** → 仍然回一個看起來正常的 dict。上層的判定是
   `if result is None`，所以它算成功；合併那一段在「什麼都沒抓到」的時候原封
   不動回傳既有快取、把 `fetched_at` 蓋成今天。於是 TWSE 掛一整天的結果是：

       ✅ 所有資料源都成功更新。     ← 程式這樣說
       dates[-1] = 兩個星期前         ← 資料實際上是這樣

   而頁面那邊反而是誠實的（它自己算預期交易日，掛一個「資料尚未更新到今天」
   的 chip）——**頁面誠實、程式碼撒謊**，而排程只看程式碼的結束碼。

完全不打網路：設定檔用 tmp 目錄，TAIEX 那一段把抓月份的函式換掉。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _with_config(config_text):
    """context manager 版本：進去之後 config_loader 看到的就是這份設定。"""
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


# ── 一、設定檔壞掉要停下來 ──────────────────────────────────────────────


def test_設定檔壞掉不會安靜地退回內建清單():
    """這是整件事的重點：壞掉的設定檔曾經只是一行警告。

    退回內建清單的問題不是「清單比較短」，是**使用者看不出來**——報告照常產出、
    照常發布，只是少了六張卡片。
    """
    import config_loader

    broken = '{"jp_stocks": [ {"code": "6981.T",, ] }'   # 多一個逗號
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
    """這一條守的是**不要修過頭**。

    「檔案不存在」和「檔案壞了」是兩件事：前者是第一次跑，還沒有設定，退回
    預設是對的。兩件事一起停下來的話，clone 下來第一次跑就爆炸。
    """
    with _with_config(None) as cl:
        assert cl._load_raw() == {}, "檔案不存在的時候應該回空 dict 走預設"


def test_設定檔正常的時候原樣讀回來():
    payload = {"jp_stocks": [{"code": "6981.T", "key": "murata", "name": "村田"}]}
    with _with_config(json.dumps(payload, ensure_ascii=False)) as cl:
        assert cl._load_raw() == payload


def test_壞掉的設定檔印的是一句人話不是_traceback():
    """`generate_report_local.py` 在 **import 的時候**就讀設定（模組層級的
    `_TH` 與 `JP_STOCK_CONFIG`），所以包在 `main` 上的裝飾器攔不到。

    改成在 `config_loader` import 時裝 excepthook，這裡直接呼叫那個 hook 驗。
    """
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
    """只處理 ConfigBroken。把別的例外也吃掉的話，真正的 bug 會變成一行訊息。"""
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
    """寫對了但沒裝上去，症狀和沒寫一模一樣。"""
    import config_loader

    assert sys.excepthook is config_loader._config_broken_excepthook, (
        "config_loader 沒有把 excepthook 裝上去——壞掉的設定檔還是會吐 traceback"
    )


# ── 二、TAIEX 一個月都沒抓到要算失敗 ───────────────────────────────────


def _run_taiex(*, months_fail, cached_rows):
    """真的跑一次 `fetch_taiex`，但網路與 sleep 換掉。回傳它回了什麼。

    `months_fail=True` ＝ 每一個月都抓失敗；`False` ＝ 每一個月都回一份有資料的
    payload。`cached_rows` 是既有快取（模擬「上一次跑完留下來的 data/taiex.json」）。
    """
    import fetch_market_data as fmd

    def boom(*a, **k):
        raise TimeoutError("測試裡不打網路")

    def payload(*a, **k):
        return {"data": [["115/09/18", "1,000", "2,000", "3", "20,000.5", "1.0"]]}

    real_fetch = fmd._fetch_json_with_retry
    real_sleep = fmd.time.sleep
    real_load = fmd._load_cache
    # ⚠️ `_write_json` 一定要換掉：`fetch_taiex` 抓完就會寫進 repo 裡真正的
    # `data/taiex.json`。第一版忘了換，跑一次測試就把真實的快取蓋成一筆假資料。
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
    """回一個非 None 的 dict 就會被上層算成「成功更新」。

    上層是 `if result is None: failures.append(...)`，沒有別的判斷。所以
    「什麼都沒抓到卻回了既有快取」＝ 報告上寫著一切正常，而台股指數停在兩週前。

    這裡給它一份兩週前的快取，然後讓每一個月都抓失敗——修好之前，它會回那份
    快取、`fetched_at` 蓋成今天，看起來完全正常。
    """
    stale = {"dates": ["2026-09-04"], "close": [20000.0],
             "volume_shares": [1.0], "value_twd": [1.0]}
    result, _ = _run_taiex(months_fail=True, cached_rows=stale)
    assert result is None, (
        "一天新資料都沒拿到，卻回了一個非 None 的 dict。上層只看 None，"
        f"所以這會被算成「成功更新」：{str(result)[:200]}"
    )


def test_taiex_有抓到東西就正常回傳():
    """不要修過頭：抓得到的時候當然要回資料。"""
    result, _ = _run_taiex(months_fail=False, cached_rows=None)
    assert result is not None, "抓得到卻回了 None"
    assert result.get("dates"), f"回了東西但沒有日期：{str(result)[:200]}"


def test_taiex_沒有新交易日但也沒有失敗不算失敗():
    """增量模式下「這幾個月都抓過了、沒有新的交易日」也是空的——那是正常的。

    所以判斷是 `failed_months and not out_dates`，不是只看 `not out_dates`。
    只看後者的話，這條排程會在每個沒有新交易日的日子紅一次。
    """
    import fetch_market_data as fmd
    import inspect

    src = inspect.getsource(fmd.fetch_taiex)
    assert "failed_months and not out_dates" in src, (
        "判斷只看了 `out_dates`——沒有新交易日的日子會被當成失敗，每天紅一次"
    )


def test_上層把_None_算成失敗():
    """`fetch_taiex` 回 None 之後，還要有人把它算成失敗——不然等於沒改。"""
    import inspect

    import fetch_market_data as fmd

    src = inspect.getsource(fmd)
    main = src.split('if __name__ == "__main__":', 1)[1]
    assert "def _run(" in main, "找不到 `_run`"
    runner = main.split("def _run(", 1)[1].split("\n    print(", 1)[0]
    assert "if result is None" in runner and "failures.append" in runner, (
        "`_run` 沒有把 None 算成失敗，`fetch_taiex` 回 None 也沒有意義"
    )


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
