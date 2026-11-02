# -*- coding: utf-8 -*-
"""融資餘額與信用交易（tw_margin.py）：解析、抓取的禮貌與改正、判讀規則、報告頁。完全不打網路。"""
import gzip
import json
import os
import sys
import tempfile
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(BASE_DIR, "reference", "samples")
sys.path.insert(0, BASE_DIR)

import tw_margin as M  # noqa: E402


def sample(name):
    with gzip.open(os.path.join(SAMPLES, f"{name}.raw.gz"), "rb") as f:
        return json.loads(f.read().decode("utf-8"))


MS = sample("twse_mi_margn_ms_20261030")
ALL = sample("twse_mi_margn_all_20261030")
TP = sample("tpex_margin_balance_20261030")
TPC = sample("tpex_close_20261030")
OA = sample("twse_openapi_stock_day_all_20261030")


def test_證交所彙總表_金額換成億元_今日與前日():
    got = M.parse_twse_ms(MS)
    assert round(got["today"]["amt"], 2) == 6234.68 and round(got["prev"]["amt"], 2) == 6339.11
    assert got["today"]["lots"] == 9555729 and got["today"]["short"] == 197359


def test_櫃買表的合計列():
    got = M.parse_tpex_bal(TP)
    assert round(got["today"]["amt"], 2) == 2053.01 and round(got["prev"]["amt"], 2) == 2099.59
    assert got["today"]["lots"] == 2307268 and got["today"]["short"] == 36178
    assert len(got["lots"]) > 800


def test_融資維持率估算_用實際的10月30日資料():
    tw = M.maintenance(M.parse_twse_all(ALL), M.parse_twse_openapi(OA, date(2026, 10, 30)),
                       M.parse_twse_ms(MS)["today"]["amt"])
    tp = M.parse_tpex_bal(TP)
    otc = M.maintenance(tp["lots"], M.parse_tpex_close(TPC), tp["today"]["amt"])
    assert 171 < tw < 172.5 and 166.5 < otc < 167.5
    # openapi 的日期不是那一天就不用（寧可不算，也不要拿錯天的收盤價）
    assert M.parse_twse_openapi(OA, date(2026, 10, 29)) == {}
    # 收盤價對不上太多檔：不算
    assert M.maintenance(tp["lots"], {"0050": 100.0}, tp["today"]["amt"]) is None


class FakeNet(M.Net):
    def __init__(self, pages, block_twse_after=None):
        self.pages, self.calls, self.n_twse = pages, [], 0
        self.block_after = block_twse_after
        super().__init__(get=self._fake, sleep=lambda s: None, clock=lambda: 0.0)

    def _fake(self, url):
        self.calls.append(url)
        if "twse.com.tw" in url and "openapi" not in url:
            self.n_twse += 1
            if self.block_after is not None and self.n_twse > self.block_after:
                return "<html>因為安全性考量，您所執行的頁面無法呈現。FOR SECURITY REASONS</html>".encode()
        for key, payload in self.pages.items():
            if key in url:
                return json.dumps(payload).encode()
        return b"{}"


def _ms(today, prev):
    return {"stat": "OK", "tables": [{"data": [
        ["融資(交易單位)", "0", "0", "0", f"{prev * 1000:,.0f}", f"{today * 1000:,.0f}"],
        ["融券(交易單位)", "0", "0", "0", "100", "100"],
        ["融資金額(仟元)", "0", "0", "0", f"{prev * 1e5:,.0f}", f"{today * 1e5:,.0f}"]]}]}


def _tp(today, prev):
    t = json.loads(json.dumps(TP))
    s = t["tables"][0]["summary"]
    s[1][2], s[1][6] = f"{prev * 1e5:,.0f}", f"{today * 1e5:,.0f}"
    return t


def test_抓第d天時用前日餘額改正前一天_回補隔天抓一次就好():
    tmp = tempfile.mkdtemp()
    cal = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]
    pages = {f"date={d.replace('-', '')}&selectType=MS": _ms(6000 + i * 10, 5999 + i * 10)
             for i, d in enumerate(cal)}
    pages.update({f"date={d[:4]}%2F{d[5:7]}%2F{d[8:]}&id=": _tp(2000 + i, 1999 + i) for i, d in enumerate(cal)})
    net = FakeNet(pages)
    st = M.fetch(tmp, calendar=cal, today=date(2026, 11, 2), max_days=60, mr_days=0, net=net, log=lambda *a: None)
    doc = json.load(open(os.path.join(tmp, M.FILE), encoding="utf-8"))
    assert doc["dates"] == cal
    # 10/30 抓到時，10/29 用的是 10/30 表上的「前日餘額」（6039），不是 10/29 當天的「今日餘額」（6030）
    assert doc["twse_amt"][3] == 6039.0 and doc["final"][3] is True
    assert doc["final"][4] is False                  # 最新一天要等隔天的表才算定案
    ms_calls = [u for u in net.calls if "selectType=MS" in u]
    assert len(ms_calls) == 3, ms_calls              # 5 天只要抓 30、28、26 三天
    assert st["days"] == 3


def test_證交所擋下就整趟不再連_櫃買照補_下次接著補():
    tmp = tempfile.mkdtemp()
    cal = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]
    pages = {f"date={d.replace('-', '')}&selectType=MS": _ms(6000, 6000) for d in cal}
    pages.update({f"date={d[:4]}%2F{d[5:7]}%2F{d[8:]}&id=": _tp(2000, 2000) for d in cal})
    net = FakeNet(pages, block_twse_after=1)
    st = M.fetch(tmp, calendar=cal, today=date(2026, 11, 2), max_days=60, mr_days=0, net=net, log=lambda *a: None)
    assert any("www.twse.com.tw" in b for b in st["blocked"])
    assert net.n_twse == 2                           # 第二次被擋，之後一次都不再連
    doc = json.load(open(os.path.join(tmp, M.FILE), encoding="utf-8"))
    assert all(v is not None for v in doc["tpex_amt"][-2:])
    assert st["missing"] > 0


def _series(n, tot, idx, mr=None):
    dates = [f"2021-{1 + i // 28:02d}-{1 + i % 28:02d}" if i < 336 else f"20{22 + (i - 336) // 336}-{1 + (i % 336) // 28:02d}-{1 + i % 28:02d}"
             for i in range(n)]
    margin = {"dates": dates, "twse_amt": [t * 0.75 for t in tot], "tpex_amt": [t * 0.25 for t in tot],
              "twse_lots": [1000] * n, "tpex_lots": [500] * n, "twse_short": [10] * n, "tpex_short": [5] * n,
              "mr_total": mr or [None] * n}
    return margin, {"dates": dates, "close": idx, "value_twd": [3e11] * n}


def test_判讀_籌碼清洗_過熱_接刀_法人主導():
    n = 400
    up = [5000 + i * 5 for i in range(n)]
    # 籌碼清洗：最後 20 天融資砍 15%、指數跌 10%
    tot = up[:-20] + [up[-21] * (1 - 0.0075 * k) for k in range(1, 21)]
    idx = [20000 + i * 10 for i in range(n - 20)] + [(20000 + (n - 21) * 10) * (1 - 0.005 * k) for k in range(1, 21)]
    a = M.analyze(*_series(n, tot, idx))
    assert a["snap"]["state"] == "purge", a["snap"]
    # 維持率 ≤140 也算清洗
    mg, tx = _series(n, up, [20000 + i * 10 for i in range(n)], [None] * (n - 1) + [138.0])
    assert M.analyze(mg, tx)["snap"]["state"] == "purge"
    # 過熱：水位高、年增 >40%、融資漲得比指數快很多
    hot = [1500 + i * 4 for i in range(n - 20)] + [(1500 + (n - 21) * 4) * (1 + 0.01 * k) for k in range(1, 21)]
    a = M.analyze(*_series(n, hot, [20000 + i for i in range(n)]))
    assert a["snap"]["state"] == "hot", a["snap"]
    # 接刀：指數跌、融資增
    tot = [5000] * (n - 20) + [5000 * (1 + 0.002 * k) for k in range(1, 21)]
    idx = [20000] * (n - 20) + [20000 * (1 - 0.003 * k) for k in range(1, 21)]
    assert M.analyze(*_series(n, tot, idx))["snap"]["state"] == "catch"
    # 法人主導：指數漲 6%、融資只增 1%
    tot = [5000] * (n - 20) + [5000 * (1 + 0.0005 * k) for k in range(1, 21)]
    idx = [20000] * (n - 20) + [20000 * (1 + 0.003 * k) for k in range(1, 21)]
    a = M.analyze(*_series(n, tot, idx))
    assert a["snap"]["state"] == "healthy"
    assert M.alerts(a) == []                         # 健康就不吵
    assert a["snap"]["episodes"]                     # 有歷史驗證


def test_報告頁與說明():
    import explanations
    import generate_report_local as G
    n = 400
    a = M.analyze(*_series(n, [5000 + i for i in range(n)], [20000 + i for i in range(n)], [None] * (n - 1) + [165.0]))
    html, script = G.render_tw_margin_section(a)
    assert "融資餘額與信用交易" in html and "mgAmtChart" in html and "mgSetRange" in script
    assert "tw_margin" in explanations.TIPS


def test_設定檔的門檻跟程式的預設一致():
    import config_loader
    t = config_loader.load_thresholds()
    assert all(t[k] == v for k, v in M.DEFAULTS.items())


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
