# -*- coding: utf-8 -*-
import os
import re
import shutil
import subprocess
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


PRELUDE = r"""
function El(tag) {
  this.tagName = String(tag || 'div').toUpperCase();
  this.children = [];
  this.parentNode = null;
  this.dataset = {};
  this._class = '';
  this._text = '';
  this.hidden = false;
  this.id = '';
  this.title = '';
  this.type = '';
  this.onclick = null;
}
Object.defineProperty(El.prototype, 'className', {
  get: function () { return this._class; },
  set: function (v) { this._class = v; },
});
Object.defineProperty(El.prototype, 'textContent', {
  get: function () {
    return this._text + this.children.map(function (c) { return c.textContent; }).join('');
  },
  // 真的 DOM 裡指定 textContent 會把子節點清掉。chip 就是先設文字再 appendChild
  // 一個 <span> 進去，這個順序要是反過來壞掉，這裡要跟著壞。
  set: function (v) { this._text = String(v); this.children.length = 0; },
});
Object.defineProperty(El.prototype, 'classList', {
  get: function () {
    var self = this;
    return {
      contains: function (c) { return self._class.split(/\s+/).indexOf(c) >= 0; },
      add: function (c) { if (!this.contains(c)) self._class = (self._class + ' ' + c).trim(); },
      remove: function (c) {
        self._class = self._class.split(/\s+/).filter(function (x) { return x && x !== c; }).join(' ');
      },
    };
  },
});
Object.defineProperty(El.prototype, 'nextSibling', {
  get: function () {
    if (!this.parentNode) return null;
    var i = this.parentNode.children.indexOf(this);
    return this.parentNode.children[i + 1] || null;
  },
});
El.prototype.appendChild = function (c) {
  if (c.parentNode) c.parentNode.removeChild(c);
  c.parentNode = this; this.children.push(c); return c;
};
El.prototype.removeChild = function (c) {
  var i = this.children.indexOf(c);
  if (i >= 0) this.children.splice(i, 1);
  c.parentNode = null; return c;
};
El.prototype.insertBefore = function (c, ref) {
  if (c.parentNode) c.parentNode.removeChild(c);
  c.parentNode = this;
  var i = ref ? this.children.indexOf(ref) : -1;
  if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
  return c;
};
El.prototype.querySelector = function (sel) {
  var cls = sel.replace(/^\./, '');
  for (var i = 0; i < this.children.length; i++) {
    var c = this.children[i];
    if (c.classList.contains(cls)) return c;
    var d = c.querySelector(sel);
    if (d) return d;
  }
  return null;
};

var REG = {};
var document = {
  getElementById: function (id) { return REG[id] || null; },
  createElement: function (tag) { return new El(tag); },
  addEventListener: function () {},
};
function mk(id, tag, cls) {
  var e = new El(tag);
  e.id = id; e.className = cls || '';
  if (id) REG[id] = e;
  return e;
}
var localStorage = {
  _v: {},
  getItem: function (k) { return this._v[k] || null; },
  setItem: function (k, v) { this._v[k] = String(v); },
  removeItem: function (k) { delete this._v[k]; },
};
var location = { pathname: '/', hash: '', replace: function () {} };
"""

DRIVER = r"""
var grid = mk('grid', 'div', 'jp-stock-grid');
['a', 'b', 'c'].forEach(function (k) {
  var card = mk('card-' + k, 'div', 'section-card');
  grid.appendChild(card);
});
var row = mk('mm-hidden-row', 'div', 'hidden-row');
row.hidden = true;
mk('mmStatus', 'div', 'manage-status');
var count = mk('mm-watch-count', 'span', 'chip-v');
count.textContent = '3 檔';

function order() { return grid.children.map(function (c) { return c.id; }); }
function chips() {
  return row.children
    .filter(function (c) { return c.classList.contains('hidden-chip'); })
    .map(function (c) { return { code: c.dataset.code, text: c.textContent }; });
}
function snap(label) {
  return {
    label: label,
    order: order(),
    chips: chips(),
    rowHidden: !!row.hidden,
    count: count.textContent,
  };
}

var out = [snap('起點')];

var hideBtn = new El('button');
hideBtn.dataset.code = 'b';
hideBtn.dataset.name = 'B公司';
hideBtn.dataset.ticker = '2222.T';

var undo = mmLocalApply('隱藏個股', hideBtn);
out.push(snap('隱藏之後'));

mmLocalRevert(undo);
out.push(snap('還原之後'));

// 移除走的是同一條路，差別只在不長還原鈕出來——沒有這個差別，一顆按下去就回不
// 來的動作會在畫面上留下一顆看起來叫得回來的眼睛。
var rmBtn = new El('button');
rmBtn.dataset.code = 'c';
rmBtn.dataset.name = 'C公司';
rmBtn.dataset.ticker = '3333.T';
mmLocalApply('移除個股', rmBtn);
out.push(snap('移除之後'));

console.log(JSON.stringify(out));
"""


def _extract_js():
    import generate_report_local as grl

    bar = grl.render_manage_bar()
    m = re.search(r"<script>(.*?)</script>", bar, re.S)
    assert m, "render_manage_bar() 裡找不到 <script>"
    return m.group(1)


def test_hiding_a_card_happens_on_screen_and_undoes_exactly():
    if not shutil.which("node"):
        print("  ⚠️ 這台機器沒有 node，跳過。CI 的 ubuntu runner 內建 node，"
              "那裡會跑到。")
        return

    import json

    js = PRELUDE + _extract_js() + DRIVER
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "drive.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(js)
        p = subprocess.run([shutil.which("node"), path],
                           capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"node 跑不起來：\n{p.stderr[-2000:]}"
    start, hidden, reverted, removed = json.loads(p.stdout)

    assert start["order"] == ["card-a", "card-b", "card-c"], start
    assert start["rowHidden"] is True, "一開始沒有隱藏個股，那一列不該露出來"

    assert hidden["order"] == ["card-a", "card-c"], hidden["order"]
    assert [c["code"] for c in hidden["chips"]] == ["b"], hidden["chips"]
    assert "B公司" in hidden["chips"][0]["text"], hidden["chips"][0]
    assert "2222.T" in hidden["chips"][0]["text"], "還原鈕上看不到代號"
    assert hidden["rowHidden"] is False, "長出第一顆還原鈕，那一列卻還藏著"
    assert hidden["count"] == "2 檔", hidden["count"]

    assert reverted["order"] == ["card-a", "card-b", "card-c"], (
        f"還原之後順序變了：{reverted['order']}　"
        "（用 appendChild 而不是 insertBefore(card, next) 就會長這樣）"
    )
    assert reverted["chips"] == [], "還原了卻留著一顆還原鈕"
    assert reverted["rowHidden"] is True, "最後一顆被收走，那一列沒有跟著藏回去"
    assert reverted["count"] == "3 檔", reverted["count"]

    assert removed["order"] == ["card-a", "card-b"], removed["order"]
    assert removed["chips"] == [], "移除卻長了一顆看起來叫得回來的眼睛"
    assert removed["count"] == "2 檔", removed["count"]
    print("  隱藏當場生效、還原回原位、移除不留假的還原鈕")


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
    print(f"✅ {len(tests)} 個測試全部通過")
