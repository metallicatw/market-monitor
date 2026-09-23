"""報告的分頁排版（2026-09-23）。

## 改了什麼

以前一打開是五條收合的橫幅（重點摘要／台股／美股／日股總經／日股觀察），展開
哪一條，哪一條就把其他四條推到一兩個螢幕以外。現在：

* 最上面一排**分頁**，〔重點摘要〕預設打開、不收合——第一眼就是預警清單＋各市場
  速覽（點一列直接跳到那一頁）。
* 台股／美股／日股三頁裡再一排**子分頁**（台股加權指數｜台股資金面與景氣領先
  指標……）。
* 指標的**數字**攤開，**趨勢圖**收在 `<details class="fold chart-fold">` 裡，
  點一下才展開。
* 〔日股觀察〕不拆子分頁（收合的個股卡標題列本身就是總覽），管理表單收進
  〔⚙️ 管理追蹤名單〕，狀態列留在外面；〔全部展開〕〔全部收合〕在〔追蹤中 N 檔〕
  旁邊，只對個股卡作用；電腦版展開之後仍是一列兩張。

## 這裡守什麼

版面本身要真的瀏覽器才量得到。這裡守的是結構：每一頁、每一個子分頁都接得上
（id／aria／hidden 一致）、每一張指標圖都真的收在摺疊裡、頁面上沒有重複的 id、
分頁的 JS 放在跟圖表分開的那個 script 區塊裡、送出去的每一段 JS 語法都是對的。
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generate_report_local as grl  # noqa: E402

_HTML = None


def _report():
    """用 repo 裡的 data/ 產生一份報告（--local：不寄信、不動正式的 index.html）。"""
    global _HTML
    if _HTML is None:
        subprocess.run([sys.executable, "generate_report_local.py", "--local"],
                       cwd=ROOT, check=True, capture_output=True, timeout=300)
        _HTML = (ROOT / "local_test" / "index.html").read_text("utf-8")
    return _HTML


# ── 小零件 ────────────────────────────────────────────────────────────

def test_分頁第一頁打開其餘收著():
    html = grl.render_tabs([("summary", "重點摘要", "", "S"),
                            ("tw", "台股", "", "T"), ("us", "美股", "", "U")])
    tabs = re.findall(r'<button type="button" role="tab" class="mm-tab"[^>]*>', html)
    assert len(tabs) == 3, tabs
    assert 'aria-selected="true"' in tabs[0] and "tabindex" not in tabs[0]
    for t in tabs[1:]:
        assert 'aria-selected="false"' in t and 'tabindex="-1"' in t, t
    panes = re.findall(r'<section class="mm-pane"[^>]*>', html)
    assert "hidden" not in panes[0], "〔重點摘要〕要預設打開"
    assert all(" hidden" in p for p in panes[1:]), panes
    for pid in ("summary", "tw", "us"):
        assert f'aria-controls="pane-{pid}"' in html and f'id="pane-{pid}"' in html
        assert f'aria-labelledby="tab-{pid}"' in html


def test_子分頁接得上():
    html = grl.sub_tabs("tw", [("taiex", "台股加權指數", "A"), ("twmacro", "資金面", "B")])
    assert "mmShowSub('tw', 'taiex')" in html and "mmShowSub('tw', 'twmacro')" in html
    subs = re.findall(r'<div class="mm-subpane"[^>]*>', html)
    assert len(subs) == 2 and "hidden" not in subs[0] and "hidden" in subs[1], subs
    assert grl.sub_tabs("tw", []) == ""


def test_趨勢圖外面那一層是收合的():
    s = grl.fold_open("加權指數走勢圖") + "X" + grl.FOLD_CLOSE
    assert s.startswith('<details class="fold chart-fold">'), s
    assert " open" not in s.split(">", 1)[0], "趨勢圖要預設收合"
    assert s.endswith("</details>")


# ── 整份報告 ──────────────────────────────────────────────────────────

def test_五個分頁照順序():
    html = _report()
    got = re.findall(r'class="mm-tab" id="tab-(\w+)"', html)
    assert got == ["summary", "tw", "us", "jp", "jpstock"], got
    assert "block-card" not in html.split("<body>", 1)[1], "舊的橫幅還在"


def test_重點摘要直接展開而且有各市場速覽():
    html = _report()
    pane = html[html.index('id="pane-summary"'):html.index('id="pane-tw"')]
    head = pane.split(">", 1)[0]
    assert "hidden" not in head, "〔重點摘要〕被收起來了"
    assert "summary-box" in pane, "預警清單不在〔重點摘要〕裡"
    for gid in ("tw", "us", "jp", "jpstock"):
        assert f"mmShowTab('{gid}')" in pane, f"速覽少了 {gid} 那一列"


def test_子分頁照使用者要的切法():
    html = _report()
    want = {"tw": ["taiex", "twmacro"], "us": ["usidx", "usmacro", "macro"],
            "jp": ["nikkei", "murata"]}
    for tab, subs in want.items():
        start = html.index(f'id="pane-{tab}"')
        end = html.index("</section>", start)
        got = re.findall(r'class="mm-subtab" id="sub-(\w+)"', html[start:end])
        assert got == subs, f"{tab}：{got}"
    pane = html[html.index('id="pane-jpstock"'):]
    assert "mm-subtab" not in pane.split("</section>", 1)[0], "〔日股觀察〕不拆子分頁"


def test_每一張指標圖都收在摺疊裡():
    """使用者要的是「預設收合，點擊後展開趨勢圖」——數字攤開、圖收著。"""
    html = _report()
    for cid in ("taiexChart", "twPmiChart", "twMcM1bChart", "usIdxChart",
                "vixChart", "michiganChart", "nikkeiChart", "murataChart"):
        i = html.index(f'<canvas id="{cid}"')
        opened = html.rfind('<details class="fold chart-fold">', 0, i)
        closed = html.rfind("</details>", 0, i)
        assert opened > closed, f"{cid} 沒有收在趨勢圖的摺疊裡"


def test_數字不在摺疊裡():
    """反過來：摺疊只包圖。數字方塊被包進去的話，點進分頁會什麼都看不到。"""
    html = _report()
    for fold in re.findall(r'<details class="fold chart-fold">(.*?)</details>', html, re.S):
        assert "stat-value" not in fold and "fin-value" not in fold, fold[:200]


def test_頁面上沒有重複的_id():
    html = _report()
    ids = re.findall(r'\sid="([^"]+)"', html)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert not dup, f"重複的 id：{dup[:10]}"
    assert 'data-mirror="mm-watch-count"' in html, "速覽列上的「追蹤中 N 檔」沒有掛副本"
    assert '[data-mirror="mm-watch-count"]' in grl.render_manage_bar(), (
        "隱藏一檔之後只改了〔日股觀察〕那一頁的數字，速覽列上那個不會跟著變")


def test_管理表單收起來但狀態列在外面():
    html = _report()
    pane = html[html.index('id="pane-jpstock"'):]
    fold_at = pane.index('<details class="fold manage-fold">')
    fold_end = pane.index("</details>", pane.index('<details class="manage-token">'))
    fold_end = pane.index("</details>", fold_end + 1)
    status_at = pane.index('id="mmStatus"')
    assert status_at > fold_end, "狀態列被收進〔管理追蹤名單〕了——卡片上的垃圾桶會沒有地方講話"
    assert pane.index('class="jp-stock-grid"') > status_at
    assert fold_at < status_at
    assert html.count('id="mmStatus"') == 1


def test_全部展開也打開趨勢圖但不打開管理表單():
    src = grl.SHARED_JS
    body = src[src.index("function setAllCards"):src.index("function setInitialCardStates")]
    assert "details.fold:not(.manage-fold)" in body, body


def test_日股觀察的全部展開收合在追蹤中旁邊():
    html = _report()
    pane = html[html.index('id="pane-jpstock"'):]
    chips = pane[pane.index('<div class="pane-chips">'):]
    chips = chips[:chips.index('<details class="fold manage-fold">')]
    assert "追蹤中" in chips
    assert "mmStockCards(false)" in chips and "全部展開" in chips, "〔全部展開〕不在〔追蹤中〕旁邊"
    assert "mmStockCards(true)" in chips and "全部收合" in chips
    assert chips.index("追蹤中") < chips.index("全部展開")
    js = grl.TABS_JS
    fn = js[js.index("function mmStockCards"):]
    fn = fn[:fn.index("\n  }\n") + 4]
    assert ".jp-stock-grid > .section-card[data-card]" in fn, "只該動個股卡：" + fn


def test_電腦版展開之後仍是一列兩張():
    """使用者指定（2026-09-23）：展開的個股卡不要佔滿整列。"""
    css = re.sub(r"/\*.*?\*/", "", grl.CSS, flags=re.S)
    assert "grid-column:1 / -1" not in css, "展開的個股卡又被拉成整列了"
    assert "grid-template-columns:1fr 1fr" in css


def test_分頁的_JS_跟圖表分開放():
    """圖表那一塊任何一行出錯，都不該讓讀者連分頁都切不了。"""
    html = _report()
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    owner = [b for b in blocks if "function mmShowTab" in b]
    assert len(owner) == 1, "mmShowTab 不見了或出現兩次"
    assert "new Chart(" not in owner[0], "分頁的 JS 跟圖表放在同一個 script 區塊"
    assert "mmRestoreTab();" in owner[0], "重新整理之後不會回到原本那一頁"


def test_送出去的每一段_JS_語法都對():
    node = shutil.which("node")
    if not node:
        print("  （這台機器沒有 node，跳過；CI 上有）")
        return
    html = _report()
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    with tempfile.TemporaryDirectory() as tmp:
        for n, b in enumerate(blocks):
            f = Path(tmp) / f"b{n}.js"
            f.write_text(b, "utf-8")
            r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
            assert r.returncode == 0, f"第 {n} 段 script 語法錯誤：{r.stderr[:400]}"


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
