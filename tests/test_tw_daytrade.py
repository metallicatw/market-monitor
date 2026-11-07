import json
from datetime import date

import tw_daytrade as TD

TW = {"stat": "OK", "tables": [
    {"fields": ["當日沖銷交易總成交股數", "當日沖銷交易總成交股數占市場比重%", "當日沖銷交易總買進成交金額",
                "當日沖銷交易總買進成交金額占市場比重%", "當日沖銷交易總賣出成交金額", "當日沖銷交易總賣出成交金額占市場比重%"],
     "data": [["5,979,501,000", "30.91", "551,956,674,690", "41.78", "557,067,170,700", "42.16"]]},
    {"fields": ["證券代號", "證券名稱", "暫停現股賣出後現款買進當沖註記", "當日沖銷交易成交股數", "當日沖銷交易買進成交金額", "當日沖銷交易賣出成交金額"],
     "data": [["2330", "台積電", "", "12,345,000", "1", "1"]]}]}
TP = {"tables": [
    {"fields": ["當日沖銷交易總成交股數", "當日沖銷交易總成交股數占市場比重", "當日沖銷交易總買進成交金額",
                "當日沖銷交易總買進成交金額占市場比重", "當日沖銷交易總賣出成交金額", "當日沖銷交易總賣出成交金額占市場比重"],
     "data": [["597,141,000", "22.18%", "83,607,106,430", "46.22%", "84,244,719,570", "46.58%"]]},
    {"fields": ["證券代號", "證券名稱", "暫停現股賣出後現款買進當沖註記", "當日沖銷交易成交股數", "當日沖銷交易買進成交金額", "當日沖銷交易賣出成交金額"],
     "data": [["6488", "環球晶", " ", "1,551,000", "1", "1"]]}]}


def test_parse_and_combine():
    tw, tp = TD.parse(TW), TD.parse(TP)
    assert tw["buy_pct"] == 41.78 and tp["buy_pct"] == 46.22
    assert tw["stocks"]["2330"] == 12345000 and tp["stocks"]["6488"] == 1551000
    r, rs = TD.combine(tw, tp)
    # Σ買進 ÷ Σ（買進 ÷ 比重）
    mkt = 551956674690 / 0.4178 + 83607106430 / 0.4622
    assert abs(r - (551956674690 + 83607106430) / mkt * 100) < 0.01
    assert 41.78 < r < 46.22 and 22.18 < rs < 30.91


def test_fetch_writes_series_and_stocks(tmp_path):
    def get(url):
        return json.dumps(TW if "twse" in url else TP).encode()

    net = TD.Net(get=get, sleep=lambda s: None)
    st = TD.fetch(str(tmp_path), calendar=["2026-11-05", "2026-11-06"], today=date(2026, 11, 6), net=net,
                  log=lambda *_: None)
    assert st["days"] == 2
    doc = json.loads((tmp_path / TD.FILE).read_text(encoding="utf-8"))
    assert doc["dates"] == ["2026-11-05", "2026-11-06"] and doc["ratio"][-1] is not None
    sd = json.loads((tmp_path / TD.STOCK_FILE).read_text(encoding="utf-8"))
    assert sd["stocks"]["2330"]["dt"] == [12345000, 12345000]
    a = TD.analyze(doc)
    assert a["zone"][0] == "偏熱" and a["ma20"] == doc["ratio"][-1]


def test_zone_bounds():
    assert TD.zone(20)[0] == "冷清" and TD.zone(30)[0] == "常態" and TD.zone(40)[0] == "偏熱" and TD.zone(50)[0] == "過熱"
