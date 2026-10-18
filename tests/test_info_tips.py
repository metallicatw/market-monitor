import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import generate_report_local as grl  # noqa: E402

CSS = re.sub(r"/\*.*?\*/", "", grl.CSS, flags=re.DOTALL)
SRC = inspect.getsource(grl)

MOBILE_TIP_RULES = (
    (".info-btn", "min-width:36px; min-height:36px;"),
    (".fin-info-btn", "min-width:36px; min-height:36px;"),
    (".expand-btn", "min-height:36px; padding:7px 14px;"),
    (".info-popup", "max-height:60vh; max-height:60dvh;\n"
                    "                  overflow-y:auto; overscroll-behavior:contain;"),
)


def _block(start_marker):
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
    found = re.findall(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert found, f"找不到規則 {selector}"
    assert len(found) == 1, f"{selector} 在這一段裡出現 {len(found)} 次"
    return re.sub(r"\s+", " ", found[0]).strip()


def test_手機上每一顆說明鈕都按得到():
    media = _block("@media (max-width:768px)")
    for sel in (".info-btn", ".fin-info-btn", ".expand-btn"):
        d = _decl(media, sel)
        assert "min-height:36px" in d, f"{sel} 在手機上沒有 36px 的高度：{d}"
    assert "min-width:36px" in _decl(media, ".fin-info-btn"), (
        "那顆沒有文字的 💡 只有字寬（量到 15px），要自己撐出寬度"
    )


def test_那顆沒有文字的燈泡在桌機上也撐得開():
    base = _decl(_base(), ".fin-info-btn")
    for prop in ("min-width", "min-height"):
        m = re.search(re.escape(prop) + r":(\d+)px", base)
        assert m and int(m.group(1)) >= 32, f"{prop} 不足 32px：{base}"
    assert "inline-flex" in base, "沒有 inline-flex 的話那個 min-width 撐不出置中的圖示"


def test_手機上一段說明不會超過六成螢幕():
    d = _decl(_block("@media (max-width:768px)"), ".info-popup")
    assert "max-height" in d and "overflow-y:auto" in d, d
    assert "dvh" in d, (
        "高度沒有補一條 dvh。vh 量的是網址列收起來之後那個比較大的高度，"
        "只寫 vh 的話網址列還在時底部會被切掉"
    )
    assert "overscroll-behavior:contain" in d, d


def test_手機規則都在():
    media = _block("@media (max-width:768px)")
    for sel, decl in MOBILE_TIP_RULES:
        assert _decl(media, sel) == " ".join(decl.split()), sel


def test_toggleInfo_會把說明捲進可視範圍():
    fn = SRC[SRC.index("function toggleInfo(id)"):]
    fn = fn[:fn.index("\n  }") + 4]
    assert "scrollIntoView" in fn, "展開之後沒有把說明捲進來"
    assert "block: 'nearest'" in fn, fn
    assert "behavior: 'instant'" in fn, "沒有指定 instant，會被 scroll-behavior:smooth 接手"


def test_toggleInfo_會補一顆收起鈕():
    fn = SRC[SRC.index("function toggleInfo(id)"):]
    fn = fn[:fn.index("\n  }") + 4]
    assert "querySelector('.info-close')" in fn, "沒有先確認有沒有，會重複塞"
    assert "createElement" in fn
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


def test_展開收合只留在日股觀察():
    assert "expand-all-bar" not in SRC, "舊的那條空列還在"
    top = SRC[SRC.index('<div class="page-header-top">'):]
    top = top[:top.index("</div>\n</div>")]
    assert "報告生成時間" in top and "modeToggleBtn" not in top
    for txt in ("全部展開", "全部收合"):
        assert txt not in top, f"〔{txt}〕還在時間戳那一列"


def test_說明鈕會說自己是開是關():
    fn = SRC[SRC.index("function toggleInfo(id)"):]
    fn = fn[:fn.index("\n  }") + 4]
    assert "aria-expanded" in fn, fn


def test_找得到說明對應的那顆鈕():
    assert "function infoBtnFor(id)" in SRC
    fn = SRC[SRC.index("function infoBtnFor(id)"):]
    fn = fn[:fn.index("\n  }") + 4]
    assert ".info-btn, .fin-info-btn" in fn, "只找其中一類的話，另一類永遠回 null"
    sites = list(re.finditer(r"toggleInfo\(", SRC))
    assert len(sites) >= 4, f"只找到 {len(sites)} 個 toggleInfo(，是不是改名了？"
    bad = []
    for m in sites:
        tail = SRC[m.end():m.end() + 3]
        if tail.startswith("id)") or tail.startswith(")"):
            continue
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
