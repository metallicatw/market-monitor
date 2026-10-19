import copy
import gzip
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import auto_financials as A

FIX = os.path.join(ROOT, "tests", "fixtures")


def _doc(name):
    with gzip.open(os.path.join(FIX, name), "rt", encoding="utf-8") as f:
        return A.parse_summary(f.read())


def _yaskawa():
    with open(os.path.join(ROOT, "data", "stock_yaskawa_quarterly_financials.json"), encoding="utf-8") as f:
        d = json.load(f)
    i = d["fiscal_years"].index("FY27Q1")
    for k in ["fiscal_years", "fiscal_year_end_dates"] + A.FIELDS:
        d[k] = d[k][: i + 1]
    return d


def test_IFRS中間期_用差分還原第二季():
    doc = _doc("tdnet_6506_q2_summary.htm.gz")
    assert doc["period"] == 2 and A._end_date(doc) == "2026-08-31"
    row, why = A.derive_quarter(_yaskawa(), doc, 2)
    assert why is None, why
    assert row["label"] == "FY27Q2"
    assert row["revenue_oku_jpy"] == round(2855.98 - 1389.82, 2)
    assert row["business_profit_oku_jpy"] == round(220.58 - 84.86, 2)
    assert row["net_income_oku_jpy"] == round(189.88 - 54.45, 2)
    assert row["eps_jpy"] == round(73.21 - 21.0, 2)
    assert abs(row["bvps_jpy"] - 504101e6 / (266690497 - 7251147)) < 0.01


def test_去年同期對不上就不寫():
    d = _yaskawa()
    i = d["fiscal_years"].index("FY26Q2")
    d["business_profit_oku_jpy"][i] += 5
    row, why = A.derive_quarter(d, _doc("tdnet_6506_q2_summary.htm.gz"), 2)
    assert row is None and "對不上" in why


def test_中間缺季就不寫():
    d = _yaskawa()
    for k in ["fiscal_years", "fiscal_year_end_dates"] + A.FIELDS:
        d[k] = d[k][:-1]
    row, why = A.derive_quarter(d, _doc("tdnet_6506_q2_summary.htm.gz"), 2)
    assert row is None and "缺季" in why


def test_已經有這一季就不寫():
    d = _yaskawa()
    row, _ = A.derive_quarter(copy.deepcopy(d), _doc("tdnet_6506_q2_summary.htm.gz"), 2)
    d["fiscal_years"].append(row["label"])
    d["fiscal_year_end_dates"].append(row["endDate"])
    for f in A.FIELDS:
        d[f].append(row[f])
    row2, _why = A.derive_quarter(d, _doc("tdnet_6506_q2_summary.htm.gz"), 2)
    assert row2 is None


def _fy_store(doc):
    vals = {"revenue_oku_jpy": (A.REV_TAGS, 1e8), "business_profit_oku_jpy": (A.PROFIT_TAGS, 1e8),
            "net_income_oku_jpy": (A.NI_TAGS, 1e8), "eps_jpy": (A.EPS_TAGS, 1)}
    prior = {f: A._pick(doc, t, "prior", "Duration")[1] / u for f, (t, u) in vals.items()}
    cur = {f: A._pick(doc, t, "cur", "Duration")[1] / u for f, (t, u) in vals.items()}
    rows = [("FY25Q1", "2024-11-30", prior, 1), ("FY25Q2", "2025-02-28", prior, 1),
            ("FY25Q3", "2025-05-31", prior, 1), ("FY25Q4", "2025-08-31", prior, 4),
            ("FY26Q1", "2025-11-30", cur, 1), ("FY26Q2", "2026-02-28", cur, 1),
            ("FY26Q3", "2026-05-31", cur, 1)]
    d = {"fiscal_years": [], "fiscal_year_end_dates": []}
    d.update({f: [] for f in A.FIELDS})
    for lb, end, tot, q in rows:
        d["fiscal_years"].append(lb)
        d["fiscal_year_end_dates"].append(end)
        for f in vals:
            part = round(tot[f] / 4, 2)
            d[f].append(part if q < 4 else round(tot[f] - 3 * part, 2))
        d["operating_margin_pct"].append(None)
        d["bvps_jpy"].append(None)
    return d, cur


def test_年度決算_第四季等於全年減前三季():
    doc = _doc("tdnet_2735_fy_summary.htm.gz")
    assert doc["period"] == 4 and A._end_date(doc) == "2026-08-31"
    d, cur = _fy_store(doc)
    row, why = A.derive_quarter(d, doc, 8)
    assert why is None, why
    assert row["label"] == "FY26Q4"
    assert abs(row["revenue_oku_jpy"] - (cur["revenue_oku_jpy"] - 3 * round(cur["revenue_oku_jpy"] / 4, 2))) < 0.011
    assert row["bvps_jpy"] == 1047.63


def test_寫入時欄位一起加_而且有來源紀錄():
    tmp = tempfile.mkdtemp()
    old = A.DATA_DIR
    try:
        A.DATA_DIR = tmp
        d = _yaskawa()
        row, _ = A.derive_quarter(d, _doc("tdnet_6506_q2_summary.htm.gz"), 2)
        ok, why = A.append_row("yaskawa", d, row, "TDnet 測試", "https://www.release.tdnet.info/x.zip", "2026-10-09")
        assert ok, why
        with open(os.path.join(tmp, "stock_yaskawa_quarterly_financials.json"), encoding="utf-8") as f:
            back = json.load(f)
        n = len(back["fiscal_years"])
        assert back["fiscal_years"][-1] == "FY27Q2"
        assert all(len(back[k]) == n for k in A.FIELDS + ["fiscal_year_end_dates"])
        assert back["auto_updates"][-1]["label"] == "FY27Q2"
    finally:
        A.DATA_DIR = old
        shutil.rmtree(tmp)


def test_快照只往前更新():
    tmp = tempfile.mkdtemp()
    old = A.DATA_DIR
    try:
        A.DATA_DIR = tmp
        snap = {"fiscal_period": "FY27Q1（2026年3-5月）実績", "note": "此資料為最新一季（FY27Q1，2026年3-5月）官方決算短信數字。其他說明。"}
        p = os.path.join(tmp, "stock_x_financials.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
        row = {"label": "FY27Q2", "endDate": "2026-08-31", "revenue_oku_jpy": 1.0,
               "net_income_oku_jpy": 2.0, "operating_margin_pct": 3.0}
        A._update_snapshot("x", row, "src", "u", "2026-10-09")
        with open(p, encoding="utf-8") as f:
            got = json.load(f)
        assert got["fiscal_period"].startswith("FY27Q2（2026年6-8月）")
        assert got["note"].startswith("此資料為最新一季（FY27Q2，2026年6-8月）") and got["note"].endswith("其他說明。")
        row["label"] = "FY27Q1"
        A._update_snapshot("x", row, "older", "u", "2026-07-10")
        with open(p, encoding="utf-8") as f:
            assert json.load(f)["source"] == "src"
    finally:
        A.DATA_DIR = old
        shutil.rmtree(tmp)


def test_何時該去找新季報():
    from datetime import date

    d = {"fiscal_year_end_dates": ["2026-03-31"]}
    assert not A.needs_update(d, 3, date(2026, 7, 15))
    assert A.needs_update(d, 3, date(2026, 7, 20))
    d = {"fiscal_year_end_dates": ["2026-05-31"]}
    assert not A.needs_update(d, 2, date(2026, 9, 10))
    assert A.needs_update(d, 2, date(2026, 9, 20))


def test_TDnet清單只留決算短信():
    old = A._get
    try:
        items = {"items": [
            {"Tdnet": {"title": "2027年3月期 第1四半期決算短信〔日本基準〕（連結）", "pubdate": "2026-07-30 16:00:00",
                       "url_xbrl": "https://webapi.yanoshin.jp/rd.php?https://www.release.tdnet.info/inbs/a.zip"}},
            {"Tdnet": {"title": "（訂正）決算短信の一部訂正", "pubdate": "2026-08-01 16:00:00",
                       "url_xbrl": "https://webapi.yanoshin.jp/rd.php?https://www.release.tdnet.info/inbs/b.zip"}},
            {"Tdnet": {"title": "自己株式の取得", "pubdate": "2026-08-02 16:00:00", "url_xbrl": None}},
            {"Tdnet": {"title": "2026年3月期 決算短信", "pubdate": "2026-03-01 16:00:00",
                       "url_xbrl": "https://webapi.yanoshin.jp/rd.php?https://www.release.tdnet.info/inbs/c.zip"}},
        ]}
        A._get = lambda url, timeout=30: json.dumps(items).encode()
        got = A.tdnet_candidates("8035", "2026-03-31")
        assert got == [("2026-07-30", items["items"][0]["Tdnet"]["title"],
                        "https://www.release.tdnet.info/inbs/a.zip")]
    finally:
        A._get = old


def test_JQuants備援_既有數字不一致就不寫():
    import build_financial_history as bfh

    d = _yaskawa()
    d["source"] = "J-Quants API"
    fake = {k: list(d[k]) for k in ["fiscal_years", "fiscal_year_end_dates"] + A.FIELDS}
    fake["fiscal_years"].append("FY27Q2")
    fake["fiscal_year_end_dates"].append("2026-08-31")
    for f in A.FIELDS:
        fake[f].append(1.0)
    saved = {n: getattr(bfh, n) for n in ("_get_cred", "fetch_statements", "pick_disclosures",
                                           "to_quarterly", "build_payload")}
    wrote = []
    old_append = A.append_row
    try:
        bfh._get_cred = lambda *a, **k: "k"
        bfh.fetch_statements = lambda *a, **k: []
        bfh.pick_disclosures = lambda *a, **k: []
        bfh.to_quarterly = lambda *a, **k: []
        bfh.build_payload = lambda *a, **k: fake
        A.append_row = lambda key, dd, row, *a: (wrote.append(row["label"]) or dd["fiscal_years"].append(row["label"]) or dd["fiscal_year_end_dates"].append(row["endDate"]) or True, "")
        assert A.try_jquants({"code": "6506.T", "key": "yaskawa", "name": "x"}, copy.deepcopy(d), lambda *a: None) == 1
        assert wrote == ["FY27Q2"]
        wrote.clear()
        fake["revenue_oku_jpy"][-2] += 50
        assert A.try_jquants({"code": "6506.T", "key": "yaskawa", "name": "x"}, copy.deepcopy(d), lambda *a: None) == 0
        assert wrote == []
    finally:
        for n, v in saved.items():
            setattr(bfh, n, v)
        A.append_row = old_append


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
