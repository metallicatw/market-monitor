"""💡說明在手機上按得到、讀得完、關得掉。

## 量到的

2026-09-20 那份報告，390×844 的無頭瀏覽器（把卡片展開之後逐顆按）：

    三十八顆 💡 **全部**小於 36px，最小的是 15×12（日股那格沒有文字的那顆）
    四段說明比一整頁還長，最長 1282px ＝ 1.52 個螢幕
    展開當下看得到的比例：中位 77%

小於 36px 的按鈕在觸控上不是「有點難按」，是按不準——手指的接觸面大約 45px 寬，
而它旁邊就是別的字。而 1282px 的一段展開之後，它底下那一整頁內容被推到一個半
螢幕以外，讀完還要往回捲一整頁才找得到原來那顆 💡 把它關掉。

改完再量同一份：

    觸控小於 36px：0／38，最小 36×36
    最長的說明 506px ＝ 0.6 螢幕
    展開當下看得到：中位 100%，最低 100%
    〔收起 ▲〕看得到：38／38

## 這裡守什麼

版面要真的瀏覽器才量得到，CI 上沒有。所以守的是那些量測背後的規則：三條手機
規則存在而且兩份（@media 與 force-mobile）一字不差、那顆沒有文字的 💡 有撐出
可以按的範圍、`toggleInfo()` 會塞〔收起〕並把說明捲進可視範圍。

另外守〔全部展開／收合〕併進時間戳那一列之後，舊的那條空列真的消失了。
"""
import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import generate_report_local as grl  # noqa: E402

#: 註解先拿掉。這份樣式表的註解裡本來就會提到 `@media`、`{`、選擇器名稱，
#: 而下面那兩個函式是靠字串和括號配對在切的——留著註解等於讓它們去配註解裡的字。
CSS = re.sub(r"/\*.*?\*/", "", grl.CSS, flags=re.DOTALL)
SRC = inspect.getsource(grl)

#: 手機上那幾條。@media 與 html.force-mobile 兩份必須一字不差——
#: 〔切換為手機版〕按下去的時候視窗可能是 1400px 寬，@media 不會命中。
MOBILE_TIP_RULES = (
    (".info-btn", "min-height:36px; padding:7px 12px; font-size:11.5px;"),
    (".fin-info-btn", "min-width:36px; min-height:36px;"),
    (".expand-btn", "min-height:36px; padding:7px 14px;"),
    (".info-popup", "max-height:60vh; max-height:60dvh;\n"
                    "                  overflow-y:auto; overscroll-behavior:contain;"),
)


def _block(start_marker):
    """把某一段 CSS 挑出來（@media 區塊，或整份樣式表）。"""
    i = CSS.index(start_marker)
    depth, j = 0, i
    while j < len(CSS):
        if CSS[j] == "{":
            depth += 1
        elif CSS[j] == "}":
            depth -= 1
            if depth == 0:
                return CSS[i:j + 1]
        j += 1
    raise AssertionError(f"{start_marker} 沒有收尾")


def _base():
    """把所有 @media 區塊挖掉，剩下的就是「所有寬度都吃」的那一份。

    不挖的話 `.fin-info-btn` 會同時撈到基準那條和 @media 裡的覆寫那條，
    而兩條本來就該長得不一樣。
    """
    out, i = [], 0
    while True:
        j = CSS.find("@media", i)
        if j < 0:
            out.append(CSS[i:])
            return "".join(out)
        out.append(CSS[i:j])
        depth, k = 0, j
        while k < len(CSS):
            if CSS[k] == "{":
                depth += 1
            elif CSS[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        i = k + 1


def _decl(css, selector):
    """挑出某一條規則的宣告。

    選擇器要從**行首**開始配。不然 `.fin-info-btn` 會連
    `html.force-mobile .fin-info-btn` 一起撈到——而那正是這份樣式表裡最容易
    搞混的兩條（一條是基準、一條是切換手機版時才生效的覆寫）。
    """
    found = re.findall(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert found, f"找不到規則 {selector}"
    assert len(found) == 1, f"{selector} 在這一段裡出現 {len(found)} 次"
    return re.sub(r"\s+", " ", found[0]).strip()


def test_手機上每一顆說明鈕都按得到():
    """36px 是觸控的下限。改之前三十八顆全部不到，最小的只有 15×12。"""
    media = _block("@media (max-width:768px)")
    for sel in (".info-btn", ".fin-info-btn", ".expand-btn"):
        d = _decl(media, sel)
        assert "min-height:36px" in d, f"{sel} 在手機上沒有 36px 的高度：{d}"
    assert "min-width:36px" in _decl(media, ".fin-info-btn"), (
        "那顆沒有文字的 💡 只有字寬（量到 15px），要自己撐出寬度"
    )


def test_那顆沒有文字的燈泡在桌機上也撐得開():
    """15×12 在滑鼠上也是難按的，而且它就擠在標籤文字旁邊。"""
    base = _decl(_base(), ".fin-info-btn")
    for prop in ("min-width", "min-height"):
        m = re.search(re.escape(prop) + r":(\d+)px", base)
        assert m and int(m.group(1)) >= 32, f"{prop} 不足 32px：{base}"
    assert "inline-flex" in base, "沒有 inline-flex 的話那個 min-width 撐不出置中的圖示"


def test_手機上一段說明不會超過六成螢幕():
    """1282px 的一段（＝1.52 個螢幕）會把底下一整頁推走，而且讀完找不到路回去。

    夾住之後它自己是一塊可以捲的區域，頁面的其他部分留在原地。
    `overscroll-behavior:contain`：捲到說明的底端不會接著把整頁一起帶著捲。
    """
    d = _decl(_block("@media (max-width:768px)"), ".info-popup")
    assert "max-height" in d and "overflow-y:auto" in d, d
    assert "dvh" in d, (
        "高度沒有補一條 dvh。vh 量的是網址列收起來之後那個比較大的高度，"
        "只寫 vh 的話網址列還在時底部會被切掉"
    )
    assert "overscroll-behavior:contain" in d, d


def test_兩份手機規則一字不差():
    """`@media (max-width:768px)` 和 `html.force-mobile` 各有一份。

    〔切換為手機版〕按下去的時候視窗可能是 1400px 寬——那個寬度 @media 不會
    命中，所以那一份非有不可。而兩份長得不一樣的症狀是「手機上好好的，按了
    切換手機版反而壞掉」，沒有人會去那裡找。
    """
    media = _block("@media (max-width:768px)")
    for sel, _ in MOBILE_TIP_RULES:
        a = _decl(media, sel)
        b = _decl(_base(), "html.force-mobile " + sel)
        assert a == b, f"{sel} 兩份不一樣：\n  @media       {a}\n  force-mobile {b}"


def test_toggleInfo_會把說明捲進可視範圍():
    """說明在按鈕正下方，而按鈕常常已經在畫面下緣——不捲的話展開了也看不到。

    `block:'nearest'`：只挪到剛好看得到。用 `'start'` 會把按鈕本身推出畫面，
    讀者失去「我剛剛按的是哪一顆」。
    `behavior:'instant'`：這一頁有 scroll-behavior:smooth，而平滑捲動配上剛剛
    才變高的版面會停在一個中途的位置。
    """
    fn = SRC[SRC.index("function toggleInfo(id)"):]
    fn = fn[:fn.index("\n  }") + 4]
    assert "scrollIntoView" in fn, "展開之後沒有把說明捲進來"
    assert "block: 'nearest'" in fn, fn
    assert "behavior: 'instant'" in fn, "沒有指定 instant，會被 scroll-behavior:smooth 接手"


def test_toggleInfo_會補一顆收起鈕():
    """三十八段說明散在六個產生點上，手工加會漏；漏掉的那幾段沒有任何症狀，

    直到有人在手機上讀到底、然後找不到路回去。所以由 JS 統一塞。
    """
    fn = SRC[SRC.index("function toggleInfo(id)"):]
    fn = fn[:fn.index("\n  }") + 4]
    assert "querySelector('.info-close')" in fn, "沒有先確認有沒有，會重複塞"
    assert "createElement" in fn
    # 類別名要和 CSS 那條對得上。對不上的症狀是：鈕塞進去了、但沒有樣式、
    # 不 sticky、而且每展開一次就再塞一顆（那個 querySelector 也找不到它）。
    assert "className = 'info-close'" in fn, (
        "塞進去的那顆鈕不叫 info-close，CSS 那條（sticky、尺寸）等於沒作用"
    )
    d = _decl(_base(), ".info-close")
    assert "position:sticky" in d, (
        "沒有 sticky 的話它只在說明的最底端——而說明被夾成一塊可以捲的區域之後，"
        "那等於要先捲到底才看得到出口"
    )
    m = re.search(r"min-height:(\d+)px", d)
    assert m and int(m.group(1)) >= 34, f"收起鈕太小：{d}"


def test_展開收合併進時間戳那一列():
    """那兩顆原本自己佔一整條，而條上只有右端兩顆小鈕。

    這份報告打開時是全部收合的，所以第一眼的畫面上，那條空列就擠在時間戳和
    第一張卡片中間。
    """
    # 不帶點：HTML 裡是 class="expand-all-bar"，CSS 裡才是 .expand-all-bar。
    # 只檢查帶點的那一種，等於只檢查樣式有沒有刪掉，而把標籤放回去照樣綠。
    assert "expand-all-bar" not in SRC, "舊的那條空列還在"
    assert 'class="header-actions"' in SRC
    top = SRC[SRC.index('<div class="page-header-top">'):]
    top = top[:top.index("</div>\n</div>")]
    for txt in ("報告生成時間", "全部展開", "全部收合", "modeToggleBtn"):
        assert txt in top, f"〔{txt}〕沒有和時間戳在同一列裡"
    assert "align-items:center" in _decl(_base(), ".page-header-top"), (
        "右邊變成三顆按鈕之後，時間戳那一行字要和它們對齊在同一條中線上"
    )


def test_說明鈕會說自己是開是關():
    """`aria-expanded`。讀螢幕的人按下去之後要知道發生了什麼。"""
    fn = SRC[SRC.index("function toggleInfo(id)"):]
    fn = fn[:fn.index("\n  }") + 4]
    assert "aria-expanded" in fn, fn


def test_找得到說明對應的那顆鈕():
    """三十八個呼叫點都是 `onclick="toggleInfo('xxx')"`，其中十五個在 f-string 裡。

    把按鈕當參數傳進去要改三十八個地方，所以改成從 onclick 回推。
    """
    assert "function infoBtnFor(id)" in SRC
    fn = SRC[SRC.index("function infoBtnFor(id)"):]
    fn = fn[:fn.index("\n  }") + 4]
    assert ".info-btn, .fin-info-btn" in fn, "只找其中一類的話，另一類永遠回 null"
    # 呼叫點的寫法要和 infoBtnFor 的比對方式對得上，不然它一輩子回 null，
    # 而且**不會報錯**——只是 aria-expanded 永遠沒人設。
    #
    # 原始碼裡的呼叫點只有幾個（多數按鈕是同一個 f-string 跑迴圈產出來的），
    # 所以這裡不數數量，改成逐一檢查每一個呼叫點都用單引號：
    # 純 HTML 字串裡是 toggleInfo('x')，f-string 裡是 toggleInfo(\\'{k}Info\\')。
    # 雙引號那一種會讓比對（找 "('id')"）整個對不上。
    sites = list(re.finditer(r"toggleInfo\(", SRC))
    assert len(sites) >= 4, f"只找到 {len(sites)} 個 toggleInfo(，是不是改名了？"
    bad = []
    for m in sites:
        tail = SRC[m.end():m.end() + 3]
        if tail.startswith("id)") or tail.startswith(")"):
            continue                        # 函式定義本身，或註解裡提到的 toggleInfo()
        if tail.startswith("'") or tail.startswith("\\'"):
            continue
        bad.append(SRC[m.start():m.end() + 24].replace("\n", " "))
    assert not bad, "這些呼叫點沒有用單引號，infoBtnFor 會對不上：" + repr(bad[:3])



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
