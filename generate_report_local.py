# -*- coding: utf-8 -*-

import argparse
import json
import os
import subprocess
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    TAIPEI_TZ = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI_TZ = timezone(timedelta(hours=8))

from config_loader import (load_thresholds, load_jp_stocks, effective_per_buy,
                           load_us_indices, load_fred_series, load_us_indicator_groups)
from explanations import TIPS, OVERVIEW_TABLE

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")

_TH = load_thresholds()
TAIEX_BUY_THRESHOLD = _TH["taiex_buy"]
VOLUME_BUY_THRESHOLD_BIL = _TH["taiex_volume_buy_bil"]
NIKKEI_BUY_THRESHOLD = _TH["nikkei_buy"]
VIX_WARN_THRESHOLD = _TH["vix_warn"]
VIX_PANIC_THRESHOLD = _TH["vix_panic"]
MICHIGAN_WARN_THRESHOLD = _TH["michigan_warn"]
MURATA_BB_WARN_THRESHOLD = _TH["murata_bb_warn"]
PER_BUY_DEFAULT = _TH["per_buy_default"]
PMI_NEUTRAL = _TH["pmi_neutral"]
TW_MC_M1B_HIGH = _TH["tw_marketcap_m1b_high"]
TW_MC_M1B_LOW = _TH["tw_marketcap_m1b_low"]
TW_MC_M1B_PCT_HIGH = _TH["tw_marketcap_m1b_pct_high"]
TW_MC_M1B_PCT_LOW = _TH["tw_marketcap_m1b_pct_low"]
TW_MC_M1B_PCT_WINDOW = _TH.get("tw_marketcap_m1b_pct_window", 60)

TW_MC_M1B_NORMAL_LAG = 2

US_INDEX_CONFIG = load_us_indices()
US_FRED_CONFIG = load_fred_series()
US_GROUP_CONFIG = load_us_indicator_groups()

JP_STOCK_CONFIG = load_jp_stocks()
JP_STOCK_BUY_THRESHOLD = {s["key"]: s["price_buy"] for s in JP_STOCK_CONFIG}
JP_STOCK_PER_THRESHOLD = {s["key"]: effective_per_buy(s, _TH) for s in JP_STOCK_CONFIG}

PBR_EXPLAIN_TEXT = """股價淨值比（PBR，Price-to-Book Ratio）是用來衡量股票價格相對於公司「每股淨值」倍數的財務指標。計算公式為每股市場價格除以每股淨值。它可以幫助投資人判斷目前的股價是便宜還是昂貴，常見於重資產或獲利起伏較大的產業評估。

股價淨值比的基本意義
大於 1 倍：代表股價高於帳面價值（溢價），市場願意用高於資產的價格買入，通常見於成長股。
等於 1 倍：代表股價與帳面價值相同，投資人以成本價購入資產。
小於 1 倍：代表股價低於帳面價值（折價），可能代表市場不看好，或是遇到了低買的價值投資機會。

適用與不適用的產業
適合使用：
金融業：資產與負債透明且變現性高。
重資產或傳統產業：如鋼鐵、航運等擁有大量廠房與固定設備的公司。
虧損或獲利不穩的公司：因本益比（PER）此時會失效，PBR 可作為替代的評估工具。
不適合使用：
科技或輕資產軟體業：公司多數價值來自無形資產、研發能力或未來潛力，帳面淨值無法反映真實價值。

使用注意事項
不能只看數字 1：低於 1 倍不一定是撿便宜，有可能是公司營運出現結構性危機的「價值陷阱」。
應與同業及歷史比較：拿不同產業的 PBR 互相比較沒有意義，應和該公司過去的區間或同類型的競爭對手相比。"""


def load_json(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def alert_badge(triggered, label, kind="warn"):
    if not triggered:
        return ""
    css_kind = "buy" if kind == "buy" else "warn"
    return f'<span class="alert-badge {css_kind}">{label}</span>'


def stat_box_cls(triggered, kind="warn"):
    if not triggered:
        return "stat-box"
    return f"stat-box alert-{'buy' if kind == 'buy' else 'warn'}"


def updown(diff):
    if diff > 0:
        return "#ef4444", "▲"
    if diff < 0:
        return "#10b981", "▼"
    return "#94a3b8", ""


def fmt_diff(diff, decimals=2, pct=None):
    color, arrow = updown(diff)
    if not arrow:
        return "持平", color
    head = f"{arrow} "
    txt = f"{head}{abs(diff):,.{decimals}f}"
    if pct is not None:
        txt += f" ({abs(pct):.2f}%)"
    return txt, color


CSS = """
  :root {
    --bg-primary:#0b0f19; --bg-card:#151d30; --text-main:#f8fafc; --text-muted:#94a3b8;
    --border-color:#243049; --accent-red:#ef4444; --accent-green:#10b981; --accent-blue:#3b82f6;
  }
  * { box-sizing:border-box; margin:0; padding:0; font-family:-apple-system,"Microsoft JhengHei",sans-serif; }
  html { scroll-behavior:smooth; }
  body { background:var(--bg-primary); color:var(--text-main); padding:24px; transition:padding .2s; }
  .wrap { max-width:1280px; margin:0 auto; display:flex; flex-direction:column; align-items:stretch; gap:18px; width:100%; }
  .wrap > .section-card,
  .wrap > .jp-stock-grid { margin-bottom:0; width:100%; }
  .section-card { background:var(--bg-card); border:1px solid var(--border-color); border-radius:14px; padding:18px 20px;
                   margin-bottom:16px; box-shadow:0 4px 18px rgba(0,0,0,0.22); transition:box-shadow .2s, transform .2s;
                   width:100%; }

  /* ---- 可折疊卡片 ---- */
  .section-card.collapsed { padding:14px 18px; }
  .card-head { display:flex; align-items:center; gap:12px; width:100%; background:none; border:none;
               padding:0; margin:0 0 14px 0; cursor:pointer; text-align:left; color:inherit; font:inherit;
               min-height:30px; }
  .section-card.collapsed .card-head { margin-bottom:0; }
  .card-head:focus-visible { outline:2px solid #22d3ee; outline-offset:4px; border-radius:8px; }
  /* 預設不換行，字太多時由 JS 逐級縮小；真的塞不下才允許換行，寧可變高也不裁掉資訊 */
  .card-head-main { flex:1; min-width:0; display:flex; flex-wrap:nowrap; align-items:center;
                    gap:0.7em 0.85em; overflow:hidden; font-size:16px; }
  .card-head-main.allow-wrap { flex-wrap:wrap; overflow:visible; }
  /* 極窄寬度時的兩列排法：標題一列、摘要一列，每張卡片結構相同，列高才會齊 */
  .card-head-main.allow-wrap > .card-title { flex:1 0 100%; }
  .card-title { font-size:1em; font-weight:800; color:var(--text-main); letter-spacing:0.2px;
                border-left:3px solid #22d3ee; padding-left:0.56em; line-height:1.35;
                white-space:nowrap; flex:none; }
  .card-head-main.allow-wrap .card-title { white-space:normal; }
  .card-summary { display:flex; flex-wrap:nowrap; align-items:center; gap:0.42em; min-width:0; min-height:1.75em; }
  .card-head-main.allow-wrap > .card-summary { flex:1 0 100%; flex-wrap:nowrap; min-width:0;
                                               overflow:hidden; height:26px; }
  .card-head-main.allow-wrap > .card-title { line-height:22px; }
  .card-chev { flex:none; font-size:20px; line-height:1; color:var(--text-muted);
               transition:transform .22s; }
  .section-card.collapsed .card-chev { transform:rotate(-90deg); }
  .card-head:hover .card-chev { color:#22d3ee; }
  .section-card.collapsed .card-body { display:none; }

  /* ---- 摘要列的小資訊格 ---- */
  .chip { display:inline-flex; align-items:baseline; gap:0.42em; font-size:0.75em;
          background:rgba(148,163,184,0.10); border:1px solid rgba(148,163,184,0.18);
          border-radius:6px; padding:0.25em 0.66em; white-space:nowrap; }
  .chip-k { color:var(--text-muted); font-size:0.92em; }
  .chip-v { font-weight:700; color:var(--text-main); font-variant-numeric:tabular-nums; }
  .chip.price .chip-v { font-size:1.25em; }
  .chip.price.up .chip-v, .chip.price.up .chip-k { color:#ef4444; }
  /* 美股三大指數那一列：名稱在前、灰字，只有點數與漲跌上色。 */
  .chip-n { color:var(--text-muted); font-size:0.92em; }
  .chip.price.down .chip-v, .chip.price.down .chip-k { color:#10b981; }
  .chip.buy { border-color:rgba(34,211,238,0.45); background:rgba(34,211,238,0.10); }
  .chip.buy .chip-v { color:#22d3ee; }
  .chip.warn { border-color:rgba(239,68,68,0.45); background:rgba(239,68,68,0.10); }
  .chip.warn .chip-v { color:#ef4444; }
  .chip.solid { font-weight:700; font-size:0.92em; padding:0.25em 0.75em; }
  .chip.buy.solid { color:#22d3ee; }
  .chip.warn.solid { color:#ef4444; }

  /* ---- 全部展開／收合 ----
     原本在時間戳那一列，對整份報告作用。改成分頁之後（2026-09-23）那兩顆就沒有
     對象了：一次只看得到一頁，而其他幾頁的趨勢圖是一張一張點開的。現在只剩
     〔日股觀察〕需要它們——十幾張個股卡要一起攤開或收起——所以搬到那一頁的
     〔追蹤中 N 檔〕旁邊，只對個股卡作用。時間戳那一列現在只有時間戳。 */
  .expand-btn { font-size:11.5px; font-weight:600; color:var(--text-muted); background:rgba(148,163,184,0.08);
                border:1px solid var(--border-color); border-radius:7px; padding:5px 12px; cursor:pointer; }
  .expand-btn:hover { color:var(--text-main); border-color:#22d3ee; }

  /* 〔日股觀察〕那一格上面的管理列。
     這是「在手機上新增一檔個股」唯一的入口——以前它只存在於 GitHub 的 Actions
     分頁裡，而那個分頁沒有任何地方會告訴你它在。按鈕做成綠色（和這一塊的色系
     一致），旁邊那行小字列出七個動作，這樣不必點進去就知道那裡能做什麼。 */
  .manage-bar { margin:0 0 14px 0; padding:11px 12px; border-radius:9px;
                background:rgba(16,185,129,0.07); border:1px solid rgba(16,185,129,0.28); }
  /* 說明寫在欄位**上面**，不是塞進 placeholder。
     
     第一版是塞 placeholder 的：一列五格橫排，每格的說明就是 workflow 的
     description。問題是那幾句話都很長，而格子很窄——「本益比布局參考線（選填，
     留空用預設 20）」在 200px 的格子裡被截成「本益比布局參考線（選填，留空用預」，
     而被截掉的正是「預設 20」，也就是那句話唯一有資訊的部分。
     
     而且 placeholder 一打字就消失。這幾格是「偶爾用一次」的東西，每次都要重新
     想「這一格填什麼單位」——那正是說明該一直在的理由。
     
     所以照 Actions 那張 Run workflow 表單的排法：一格一列，說明在上、輸入在下，
     欄寬夠就並排、不夠就自己折。 */
  .manage-form { display:grid; gap:10px 14px;
        grid-template-columns:repeat(auto-fit,minmax(228px,1fr)); align-items:end; }
  .mm-field { display:flex; flex-direction:column; gap:4px; min-width:0; }
  .mm-lab { font-size:11.5px; line-height:1.5; color:var(--text-muted); }
  .mm-lab .req { color:#f87171; margin-left:3px; }
  .manage-form select, .manage-form input {
        font:inherit; font-size:12.5px; color:var(--text-main); min-width:0; width:100%;
        background:rgba(2,6,23,0.45); border:1px solid var(--border-color);
        border-radius:7px; padding:6px 9px; }
  .manage-form select:focus, .manage-form input:focus {
        outline:2px solid #10b981; outline-offset:1px; border-color:#10b981; }
  /* 送出自己佔一格，和最後一個欄位切齊底部；但它不跟著格子一起變寬——
     一顆橫跨 280px 的「送出」看起來像一條橫幅，不像一顆按鈕。 */
  /* `align-self`（不是 justify-self）：按鈕的父層 .mm-field 是縱向 flex，
     而縱向 flex 的 stretch 拉的是**橫向**——justify-self 在那裡沒有作用。 */
  .manage-form button { align-self:start; font:inherit; font-size:12.5px; font-weight:700;
        color:#052e21; background:#10b981; border:1px solid #10b981;
        border-radius:7px; padding:7px 16px; cursor:pointer; }
  .manage-form button:hover:not(:disabled) { background:#34d399; border-color:#34d399; }
  .manage-form button:disabled { opacity:.5; cursor:progress; }

  /* 狀態列。空的時候不佔高度——一條永遠在那裡的空白列會讓版面看起來壞掉。 */
  .manage-status:not(:empty) { margin-top:8px; font-size:12px; line-height:1.6;
        color:var(--text-muted); }
  .manage-status.ok   { color:#34d399; }
  .manage-status.warn { color:#f59e0b; }
  .manage-status.bad  { color:#f87171; }

  .manage-token { margin-top:9px; font-size:11.5px; }
  .manage-token > summary { cursor:pointer; color:var(--text-muted); list-style:none;
        display:inline-flex; align-items:center; gap:5px; }
  .manage-token > summary::-webkit-details-marker { display:none; }
  .manage-token > summary::before { content:'\\25B8'; transition:transform .15s;
        display:inline-block; }
  .manage-token[open] > summary::before { transform:rotate(90deg); }
  .manage-token-body { margin-top:7px; color:var(--text-muted); line-height:1.7; }
  .manage-token-body p { margin:0 0 6px; }
  .manage-token-body b { color:var(--text-main); }
  .manage-token-body code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
        font-size:11px; color:var(--text-main); }
  .manage-token-row { display:flex; flex-wrap:wrap; gap:7px; margin-top:6px; }
  .manage-token-row input { flex:1 1 220px; min-width:0; font:inherit; font-size:12px;
        color:var(--text-main); background:rgba(2,6,23,0.45);
        border:1px solid var(--border-color); border-radius:7px; padding:5px 9px; }
  .manage-token-row button { font:inherit; font-size:11.5px; color:var(--text-muted);
        background:rgba(148,163,184,0.08); border:1px solid var(--border-color);
        border-radius:7px; padding:5px 11px; cursor:pointer; }
  .manage-token-row button:hover { color:var(--text-main); border-color:#10b981; }
  .manage-token-state { margin-top:5px; color:var(--text-muted); }
  .manage-token-how { margin:7px 0 0; }
  .manage-token-how a { color:var(--text-muted); }

  /* 個股卡右上角的操作鈕。`.card-head` 是一顆 <button>，所以這一排是它的
     兄弟、絕對定位疊上去——按鈕裡面塞按鈕在 HTML 上無效。
     留 34px 給右邊那個 ⌄，不然兩個會重疊。 */
  .section-card { position:relative; }
  .card-acts { position:absolute; top:12px; right:36px; display:flex; gap:5px;
        z-index:2; }
  .section-card.collapsed .card-acts { top:9px; }
  /* 固定寬高。兩顆按鈕的總寬度是 .card-head 那條 padding-right 算出來的，
     所以它們**不能**隨狀態變寬——按下去之後變寬會把摘要列擠掉。 */
  .card-act { font:inherit; font-size:13px; line-height:1; cursor:pointer;
        width:28px; height:26px; padding:0; display:inline-flex;
        align-items:center; justify-content:center;
        background:rgba(148,163,184,0.10); border:1px solid var(--border-color);
        border-radius:7px; color:var(--text-muted); }
  /* 裡面是一張 16px 的 inline SVG（見 ICON_EYE_OFF／ICON_TRASH）。`display:block`
     是必要的：inline 的 SVG 會照文字基線排，底下留一條 descender 的空隙，
     28×26 的按鈕裡看起來就是整個圖示往上偏 2px。線條顏色吃 `currentColor`，
     所以 hover 和 .armed 只要換 `color` 就好，不必再為圖示寫一份規則。 */
  .card-act svg { display:block; }
  .card-act:hover { border-color:#10b981; background:rgba(16,185,129,0.14); }
  .card-act.danger:hover { border-color:#f87171; background:rgba(248,113,113,0.14); }
  /* 待確認：只換顏色，寬度一格不動。要再按一次這件事寫在狀態列上。 */
  .card-act.armed { color:#fca5a5; border-color:#f87171;
        background:rgba(248,113,113,0.22); }
  /* 給那兩顆按鈕和 ⌄ 讓出位置。不留的話摘要列會從它們底下穿過去——
     在 1,300px 寬的兩欄版面上，被蓋住的正是最右邊那個「可布局」徽章。 */
  .section-card.has-acts > .card-head { padding-right:102px; }
  @media (max-width:520px) {
    .card-acts { right:32px; gap:4px; }
    .section-card.has-acts > .card-head { padding-right:94px; }
  }

  /* 〔隱藏中〕那一列：〔恢復顯示〕唯一的家。隱藏起來的個股照定義沒有卡片，
     沒有這一列就等於隱藏是單向操作。 */
  .hidden-row { display:flex; flex-wrap:wrap; align-items:center; gap:7px;
        margin-top:14px; padding-top:12px; border-top:1px dashed var(--border-color); }
  /* `display:flex` 比 `[hidden]` 的預設 `display:none` 強，所以沒有這一條的話，
     空的那一列會照樣佔一條虛線出來。 */
  .hidden-row[hidden] { display:none; }
  .hidden-label { font-size:11.5px; color:var(--text-muted); }
  .hidden-chip { font:inherit; font-size:11.5px; cursor:pointer; color:var(--text-muted);
        background:rgba(148,163,184,0.08); border:1px solid var(--border-color);
        border-radius:999px; padding:4px 11px; display:inline-flex; align-items:center;
        gap:6px; }
  /* 這一顆的字是 11.5px，16px 的圖示會比字高出一截；縮到 13px 才和字齊。
     `flex:0 0 auto` 擋的是名字太長時 flex 去壓縮圖示——被壓扁的眼睛比沒有還糟。 */
  .hidden-chip svg { width:13px; height:13px; flex:0 0 auto; display:block; }
  .hidden-chip:hover { color:var(--text-main); border-color:#10b981;
        background:rgba(16,185,129,0.12); }
  .hidden-code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
        font-size:10.5px; opacity:.7; }

  /* ---- 分頁（2026-09-23） ----
     五個分頁各一個色系，色相由 --blk 帶進來（BLOCK_TONES），其餘規則共用。
     選中的那一顆實心，其餘是同色的淡底加框——跟 tw-six-metrics 外層那一排的
     規則一樣：一排同色系按鈕裡，填滿是唯一不必比較就看得出來的差別。
     一律一列、放不下就橫向捲（手機上五顆放不下），捲軸不藏，只調細。 */
  .mm-tabs { display:flex; gap:8px; flex-wrap:nowrap; overflow-x:auto; overscroll-behavior-x:contain;
             -webkit-overflow-scrolling:touch; scrollbar-width:thin; padding:2px 2px 8px; }
  .mm-tabs::-webkit-scrollbar { height:5px; }
  .mm-tabs::-webkit-scrollbar-thumb { background:var(--border-color); border-radius:3px; }
  .mm-tab { flex:0 0 auto; display:inline-flex; align-items:center; gap:7px; white-space:nowrap;
            font:inherit; font-size:14px; font-weight:700; letter-spacing:0.3px; cursor:pointer;
            padding:9px 16px; border-radius:10px; color:var(--blk);
            background:color-mix(in srgb, var(--blk) 10%, transparent);
            border:1.5px solid color-mix(in srgb, var(--blk) 45%, transparent);
            transition:background .12s, color .12s, box-shadow .12s; }
  .mm-tab:hover { background:color-mix(in srgb, var(--blk) 20%, transparent); }
  .mm-tab[aria-selected=true] { background:var(--blk); border-color:var(--blk); color:#0b0f19;
            box-shadow:0 3px 12px color-mix(in srgb, var(--blk) 35%, transparent); }
  .mm-tab:focus-visible, .mm-subtab:focus-visible { outline:2px solid var(--blk, #22d3ee); outline-offset:2px; }
  .tab-badge { display:inline-block; min-width:19px; padding:1px 6px; border-radius:9px; font-size:11px;
               line-height:1.45; text-align:center; font-weight:800; color:#fff; }
  .tab-badge.warn { background:#ef4444; }
  .tab-badge.buy { background:#0891b2; }
  .mm-tab[aria-selected=true] .tab-badge { box-shadow:0 0 0 1.5px rgba(11,15,25,0.55); }

  .mm-pane { background:linear-gradient(180deg, color-mix(in srgb, var(--blk) 8%, transparent) 0%, var(--bg-card) 160px);
             border:1px solid var(--border-color); border-top:3px solid var(--blk); border-radius:14px;
             padding:18px 20px; box-shadow:0 4px 18px rgba(0,0,0,0.22); width:100%; min-width:0; }
  .mm-pane[hidden], .mm-subpane[hidden] { display:none; }
  .mm-pane > .summary-box:first-child { margin-top:0; }
  /* 這一頁的數字速覽：原本收合的橫幅標題旁邊那一排。 */
  .pane-chips { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 14px; font-size:15px; }
  /* 〔衰退警戒〕那種實心徽章在標題列裡是放大一號的；這裡跟旁邊的數字一樣大就好。 */
  .pane-chips .chip.solid { font-size:0.75em; }

  /* 子分頁：和金股道全站頁內分頁同一套（2026-10-07 使用者要求）——圓角方塊（7px）、
     每一顆自己一個色調（--tc，見 sub_tabs 的 SUBTAB_TONES），色調混進 55% 的灰降彩度；
     沒選中是半透明框＋淡底＋同色字，選中整顆實心、字用底色、一點陰影。
     第三層所以字小一號（12.5px）。 */
  .mm-subtabs { display:flex; gap:6px; flex-wrap:nowrap; overflow-x:auto; scrollbar-width:thin;
                margin:0 0 16px; padding:2px 0 10px; border-bottom:1px solid var(--border-color); }
  .mm-subtabs::-webkit-scrollbar { height:4px; }
  .mm-subtabs::-webkit-scrollbar-thumb { background:var(--border-color); border-radius:3px; }
  .mm-subtab { --tc:#5f6b78; --tk:color-mix(in srgb, var(--tc) 45%, #8a929b);
               flex:0 0 auto; white-space:nowrap; font:inherit; font-size:12.5px; font-weight:600; line-height:1.2;
               cursor:pointer; padding:5px 10px; border-radius:7px; color:var(--tk);
               border:1.5px solid color-mix(in srgb, var(--tk) 50%, transparent);
               background:color-mix(in srgb, var(--tk) 9%, transparent);
               transition:background .12s, color .12s, box-shadow .12s; }
  .mm-subtab:hover { background:color-mix(in srgb, var(--tk) 18%, transparent); }
  .mm-subtab[aria-selected=true] { color:#0b0f19; background:var(--tk); border-color:var(--tk);
               box-shadow:0 2px 6px color-mix(in srgb, var(--tk) 35%, transparent); }
  .mm-subtab:focus-visible { outline:2px solid var(--tk); }
  .mm-subpane > .sub-title:first-child { margin-top:2px; }
  /* 同一個子分頁裡有兩個指標（PMI 與市值貨幣比、VIX 與密大）：上一個的來源列和
     下一個的標題之間要看得出是換了一個指標。 */
  .mm-subpane .chart-source-box + .title-row, .mm-subpane .chart-source-box + .sub-title { margin-top:28px; }

  /* 一個指標一塊（ind_block，2026-10-07）：同一個子分頁裡的指標各自一個底色、左側
     一條色條，中間留空——看得出這裡換了一個指標。趨勢圖（.chart-block）緊接在自己的
     數字底下、直接展開。 */
  .ind-block { --ind:#38bdf8; position:relative; margin:0 0 18px; padding:14px 16px 12px;
               border:1px solid var(--border-color); border-left:4px solid var(--ind); border-radius:12px;
               background:linear-gradient(180deg, color-mix(in srgb, var(--ind) 7%, transparent) 0%, rgba(11,15,25,0.35) 120px); }
  .ind-block:last-child { margin-bottom:0; }
  .ind-block > .title-row:first-child, .ind-block > .sub-title:first-child { margin-top:0; }
  .ind-block .section-title, .ind-block > .title-row .sub-title { color:color-mix(in srgb, var(--ind) 55%, #f8fafc); }
  .mm-subpane .ind-block .chart-source-box + .title-row { margin-top:0; }
  .chart-block { margin:12px 0 10px; }
  .chart-cap { font-size:12.5px; font-weight:700; color:#cbd5e1; margin:0 0 6px; }
  /* 美股經濟指標：一組裡每一個指標一塊（數字卡＋自己的趨勢圖），電腦版兩欄。 */
  .ind-grid { display:grid; grid-template-columns:1fr; gap:12px; margin:0 0 6px; }
  @media (min-width:900px) { .ind-grid { grid-template-columns:1fr 1fr; } }
  .ind-grid .ind-block { margin:0; padding:12px 14px 10px; }
  .ind-grid .ind-block .fin-box { background:none; border:0; padding:0; text-align:left; }
  .us-group { margin:22px 0 0; padding-top:16px; border-top:1px dashed var(--border-color); }
  .us-group:first-child { margin-top:4px; padding-top:0; border-top:0; }

  /* 趨勢圖外面那一層（fold_open）：數字攤開、圖收著。 */
  details.fold > summary .fold-hint { margin-left:auto; font-size:11px; font-weight:500; color:var(--text-muted); }
  details.chart-fold[open] > summary .fold-hint { display:none; }
  details.chart-fold { margin-top:14px; }
  details.chart-fold > .fold-body { padding-top:4px; }
  /* 〔⚙️ 管理追蹤名單〕：預設收著的表單。裡面那張 .manage-bar 自己有框，這一層
     只是一條可以點的列，所以不要兩層框。 */
  details.manage-fold { margin:0 0 12px; border-color:rgba(16,185,129,0.35); }
  details.manage-fold > summary { color:#6ee7b7; }
  details.manage-fold > .fold-body { padding:0 12px 12px; }
  details.manage-fold .manage-bar { margin:0; }
  #mmStatus:not(:empty) { margin:0 0 12px; }
  @media (max-width:640px) { details.manage-fold > summary .fold-hint { display:none; } }
  /* 〔追蹤中 N 檔〕那一列右邊的〔全部展開〕〔全部收合〕。 */
  .pane-acts { display:inline-flex; gap:6px; margin-left:6px; align-items:center; }
  /* 速覽表：預設收合。用 <details> 不寫 JS —— 少一個會壞的東西。 */
  details.fold { margin-top:18px; border:1px solid var(--border-color); border-radius:10px;
                 background:rgba(11,15,25,0.5); overflow:hidden; }
  details.fold > summary { cursor:pointer; list-style:none; padding:11px 14px; font-size:13px; font-weight:700;
                           color:#cbd5e1; display:flex; align-items:center; gap:8px; }
  details.fold > summary::-webkit-details-marker { display:none; }
  details.fold > summary::before { content:'⌄'; font-size:18px; line-height:1; color:var(--text-muted);
                                   transform:rotate(-90deg); transition:transform .18s; }
  details.fold[open] > summary::before { transform:rotate(0deg); }
  details.fold > summary:hover { color:#f8fafc; }
  details.fold > .fold-body { padding:0 14px 14px 14px; }
  .section-title { font-size:20px; font-weight:800; margin-bottom:14px; color:#f8fafc; letter-spacing:0.3px; }
  .sub-title { font-size:13px; font-weight:700; margin:18px 0 10px 0; color:#cbd5e1; display:flex; align-items:center; gap:8px; }
  .sub-title::before { content:''; width:3px; height:14px; background:var(--accent-blue); border-radius:2px; }
  .stat-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:14px; }
  .stat-box { background:rgba(11,15,25,0.6); border:1px solid var(--border-color); border-radius:8px; padding:11px 14px; transition:background .2s,border-color .2s; }
  .stat-box.alert-buy { border-color:#22d3ee; background:rgba(34,211,238,0.10); box-shadow:0 0 0 1px rgba(34,211,238,0.25) inset; }
  .stat-box.alert-warn { border-color:#ef4444; background:rgba(239,68,68,0.10); box-shadow:0 0 0 1px rgba(239,68,68,0.25) inset; }
  .stat-label { color:var(--text-muted); font-size:12px; margin-bottom:6px; }
  .stat-value { font-size:26px; font-weight:700; }
  .stat-chg { font-size:14px; font-weight:600; margin-left:8px; }
  .stat-sub { font-size:11.5px; margin-top:5px; color:var(--text-muted); }
  .alert-badge { display:inline-block; font-size:11px; font-weight:700; padding:2px 9px; border-radius:10px; margin-left:8px; vertical-align:middle; white-space:nowrap; }
  .alert-badge.buy { background:rgba(34,211,238,0.18); color:#22d3ee; border:1px solid rgba(34,211,238,0.45); }
  .alert-badge.warn { background:rgba(239,68,68,0.18); color:#f87171; border:1px solid rgba(239,68,68,0.45); }
  .zone-badge { display:inline-block; font-size:11px; font-weight:700; padding:2px 9px; border-radius:10px; margin-left:8px; vertical-align:middle; }
  .tf-bar { display:flex; align-items:center; gap:6px; margin:4px 0 16px 0; flex-wrap:wrap; }
  .tf-btn { background:rgba(36,48,73,.5); border:1px solid var(--border-color); color:var(--text-muted);
             padding:4px 12px; border-radius:20px; font-size:12px; font-weight:600; cursor:pointer; }
  .tf-btn:hover { background:rgba(59,130,246,0.2); color:#fff; }
  .tf-btn.active { background:#2563eb; color:#fff; border-color:#3b82f6; }
  .tf-btn.disabled { opacity:0.35; cursor:not-allowed; }
  .tf-btn.disabled:hover { background:rgba(36,48,73,.5); color:var(--text-muted); }
  .custom-legend { display:flex; flex-wrap:wrap; align-items:center; justify-content:center; gap:14px;
                     margin-bottom:10px; padding:6px 8px; background:rgba(11,15,25,0.45); border-radius:6px;
                     font-size:12px; color:var(--text-muted); }
  .legend-item { display:inline-flex; align-items:center; cursor:pointer; padding:2px 4px; border-radius:4px; }
  .legend-item:hover { background:rgba(36,48,73,0.6); color:#f8fafc; }
  .legend-item.hidden-ds { text-decoration:line-through; opacity:0.35; }
  .legend-icon-solid { display:inline-block; width:18px; height:0; border-top-width:3px; border-top-style:solid; margin-right:5px; }
  .legend-icon-dashed { display:inline-block; width:18px; height:0; border-top-width:2px; border-top-style:dashed; margin-right:5px; }
  .legend-icon-bar { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; }
  .chart-container { position:relative; width:100%; min-width:0; height:380px; }
  .chart-container.short { height:260px; }
  .chart-source-box { margin-top:8px; padding:3px 10px; background:rgba(11,15,25,0.7); border-radius:5px;
                        border:1px solid rgba(36,48,73,0.7); font-size:10px; color:#64748b;
                        white-space:nowrap; overflow:hidden; text-overflow:ellipsis; line-height:1.9; }
  .chart-source-box a { color:#38bdf8; text-decoration:underline; margin:0 3px; }
  @media (max-width:520px) {
    /* 手機寬度不夠時縮字而不是截斷，來源與日期都要看得到 */
    .chart-source-box { font-size:9px; padding:3px 8px; }
    /* 手機寬度放不下時允許折行。像密大那條要標示資料月份與下次發布日，
       內容本來就比較長，寧可占兩行也不要把發布日切掉。 */
    .chart-source-box { white-space:normal; text-overflow:clip; line-height:1.7; }
  }
  @media (max-width:400px) {
    /* 極窄螢幕連第二個來源都放不下，先收起來；主要來源與日期優先保留 */
    .chart-source-box .src-extra { display:none; }
  }
  .explain-box { margin:10px 0 4px 0; padding:12px 14px; background:rgba(239,68,68,0.06); border:1px solid rgba(239,68,68,0.3);
                  border-radius:8px; font-size:12px; line-height:1.7; color:#cbd5e1; }
  .explain-box b { color:#f87171; }
  .fin-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }
  .fin-box { background:rgba(11,15,25,0.6); border:1px solid var(--border-color); border-radius:8px; padding:10px 12px; text-align:center; transition:background .2s,border-color .2s; }
  .fin-box.alert-buy { border-color:#22d3ee; background:rgba(34,211,238,0.10); box-shadow:0 0 0 1px rgba(34,211,238,0.25) inset; }
  .fin-box.alert-warn { border-color:#ef4444; background:rgba(239,68,68,0.10); box-shadow:0 0 0 1px rgba(239,68,68,0.25) inset; }
  .fin-box.alert-buy .fin-value { color:#22d3ee; }
  .fin-box .fin-label { font-size:11px; color:var(--text-muted); margin-bottom:4px; }
  .fin-box .fin-value { font-size:18px; font-weight:700; }
  .fin-box .fin-sub { font-size:11px; margin-top:3px; color:var(--text-muted); }
  .vintage { display:inline-block; font-size:11px; padding:1px 7px; border-radius:9px;
             background:rgba(148,163,184,0.12); border:1px solid rgba(148,163,184,0.28); color:#94a3b8; }
  .vintage.stale { background:rgba(245,158,11,0.10); border-color:rgba(245,158,11,0.45); color:#f59e0b; }
  .ov-wrap { overflow-x:auto; margin-top:4px; }
  .ov-table { width:100%; border-collapse:collapse; font-size:12.5px; min-width:520px; }
  .ov-table th { text-align:left; padding:8px 10px; color:var(--text-muted); font-weight:700;
                 border-bottom:1px solid var(--border-color); white-space:nowrap; }
  .ov-table td { padding:8px 10px; border-bottom:1px solid rgba(38,51,77,0.5); color:#cbd5e1; vertical-align:top; }
  .ov-table tr:last-child td { border-bottom:none; }
  .ov-name { font-weight:700; color:#f8fafc; white-space:nowrap; }
  .ov-freq { color:var(--text-muted); white-space:nowrap; }
  .ov-lead { display:inline-block; font-size:11px; font-weight:700; padding:1px 8px;
             border-radius:9px; border:1px solid; white-space:nowrap; }
  @media (max-width: 640px) {
    .fin-grid { grid-template-columns:repeat(2,1fr); }
  }
  .fin-box .fin-sub { font-size:10.5px; color:var(--text-muted); margin-top:3px; }
  .fin-empty { background:rgba(250,204,21,0.05); border:1px dashed rgba(250,204,21,0.35);
               border-radius:8px; padding:14px 16px; }
  .fin-empty-title { font-size:12.5px; font-weight:700; color:#facc15; margin-bottom:5px; }
  .fin-empty-body { font-size:11.5px; color:var(--text-muted); line-height:1.75; }
  .fin-box.pending { border-style:dashed; opacity:0.75; }
  .fin-box.pending .fin-value { color:var(--text-muted); font-weight:600; }
  .fin-pending-note { margin-top:8px; font-size:11px; color:#facc15; line-height:1.7;
                      background:rgba(250,204,21,0.06); border-radius:6px; padding:7px 10px; }
  .fin-box .fin-updated { font-size:9.5px; color:#64748b; margin-top:3px; }
  .fin-box.has-info { position:relative; }
  .fin-label-row { display:flex; align-items:center; justify-content:center; gap:4px; }
  /* 那顆 💡 以前是 15×12 px。那不是「有點小」，那是按不到——手指的接觸面
     大約 45px 寬，而它旁邊就是標籤文字。min-width/min-height 撐出可以按的
     範圍，字還是 12px（畫面上看起來一樣，變大的是**可以按的地方**）。 */
  .fin-info-btn { background:none; border:none; color:#facc15; font-size:12px; cursor:pointer;
                  padding:0; line-height:1; display:inline-flex; align-items:center;
                  justify-content:center; min-width:32px; min-height:32px; margin:-8px 0; }
  .page-header { max-width:1280px; margin:0 auto 20px auto; }
  /* `center` 而不是 `flex-start`：右邊現在是三顆按鈕，時間戳那一行字要和它們
     對齊在同一條中線上，不然字會貼著按鈕的上緣。 */
  .page-header-top { display:flex; justify-content:space-between; align-items:center; gap:12px 16px; flex-wrap:wrap; }
  .page-title { font-size:30px; font-weight:800; color:#f8fafc; letter-spacing:0.3px; }
  .page-subtitle { font-size:13px; color:var(--text-muted); margin-top:6px; }
  /* 標題拿掉之後它變成第一行，上面不再需要留白。 */
  .page-subtitle.stamp-lead { margin-top:0; }
  .summary-box { margin-top:16px; padding:16px 18px; border-radius:12px; border:1px solid var(--border-color); background:var(--bg-card); }
  .summary-box.has-alerts { border-color:#ef4444; background:rgba(239,68,68,0.08); }
  .summary-title { font-size:14px; font-weight:700; margin-bottom:10px; }
  .summary-title.alert { color:#f87171; }
  .summary-title.ok { color:#10b981; }
  .summary-list { font-size:12.5px; line-height:2; color:#e2e8f0; }
  .summary-list b { color:#facc15; }
  /* 〔重點摘要〕的預警清單：不再包一層紅框（外面那張分頁卡就是框，2026-10-07）。
     一則一列，中間一條細線；左邊小標籤固定寬，內容折行時對齊內容開頭。 */
  .summary-box.alert-list { margin-top:0; padding:0; border:0; background:none; }
  .alert-list .summary-title { font-size:15px; margin:2px 0 8px; }
  .alert-list .summary-list { line-height:1.6; font-size:13px; }
  .al { display:grid; grid-template-columns:auto 1fr; gap:10px; align-items:baseline;
        padding:9px 2px; border-top:1px solid rgba(148,163,184,0.14); }
  .al:first-child { border-top:0; }
  .al-tag { font-size:11.5px; font-weight:700; padding:1px 8px; border-radius:6px; white-space:nowrap; }
  .al-warn .al-tag { color:#fca5a5; background:rgba(239,68,68,0.14); border:1px solid rgba(239,68,68,0.45); }
  .al-buy .al-tag { color:#67e8f9; background:rgba(34,211,238,0.12); border:1px solid rgba(34,211,238,0.4); }
  .al-txt { color:#e2e8f0; min-width:0; }
  .jp-stock-grid { display:grid; grid-template-columns:1fr; gap:20px; align-items:start; width:100%; box-sizing:border-box; }
  .jp-stock-grid .section-card { margin-bottom:0; display:flex; flex-direction:column; min-width:0; }
  .jp-stock-grid .section-card:hover { box-shadow:0 8px 26px rgba(0,0,0,0.32); transform:translateY(-2px); }
  @media (min-width:1180px) {
    .jp-stock-grid { grid-template-columns:1fr 1fr; }
  }
  /* 💡：只有圖示，貼在標題右邊（2026-10-07）。和金股道的燈泡同一個樣子：小圓角方塊、
     淡框，滑過才亮。說明文字的短標題在 title 裡。 */
  .info-btn { flex:none; display:inline-flex; align-items:center; justify-content:center; min-width:28px; height:26px;
              background:rgba(148,163,184,0.08); border:1px solid var(--border-color);
              font-size:13px; line-height:1; padding:0 6px; border-radius:7px; cursor:pointer; margin-left:8px; vertical-align:middle; }
  .info-btn:hover, .info-btn[aria-expanded=true] { background:rgba(250,204,21,0.16); border-color:rgba(250,204,21,0.5); }
  .info-popup { display:none; margin:10px 0; padding:14px 16px; background:rgba(250,204,21,0.06); border:1px solid rgba(250,204,21,0.35);
                border-radius:8px; font-size:12px; line-height:1.8; color:#e2e8f0; white-space:pre-line; }
  .info-popup.open { display:block; }
  /* 〔收起 ▲〕。由 toggleInfo() 在第一次展開時塞進去，所以三十八段說明一次到齊
     ——它們散在六個不同的產生點上，手工加會漏。
     sticky 在說明的底端：說明被 max-height 夾住之後是一塊可以捲的區域，而
     「捲到哪裡都看得到出口」是這顆鈕唯一的意義。不然讀完要往回捲一整頁去找
     原來那顆 💡。 */
  .info-close { position:sticky; bottom:-14px; float:right; margin:6px -6px -6px 0;
                background:rgba(250,204,21,0.14); border:1px solid rgba(250,204,21,0.4);
                color:#facc15; font-family:inherit; font-size:11.5px; font-weight:600;
                padding:6px 12px; min-height:34px; border-radius:14px; cursor:pointer; }
  .info-close:hover { background:rgba(250,204,21,0.26); }
  /* 標題＋💡 同一行，不折行（燈泡永遠在標題右邊）。 */
  .title-row { display:flex; align-items:center; flex-wrap:nowrap; margin-bottom:14px; }
  .title-row > div:first-child { min-width:0; margin-top:0; }
  /* 由 JS 依卡片實際寬度加上，收起次要資訊只留股價與警示標籤 */
  .card-summary.compact .chip:not(.price):not(.solid) { display:none; }

  @media (max-width:768px) {
    .stat-grid { grid-template-columns:1fr; }
    .fin-grid { grid-template-columns:1fr 1fr; }
    .stat-value { font-size:21px; }
    .chart-container { height:280px; }
    .card-head-main { font-size:14.5px; }
    .mm-tab { font-size:13px; padding:8px 12px; }
    .mm-pane { padding:14px 14px; }
    .section-card { padding:14px 14px; }
    .section-card.collapsed { padding:12px 14px; }
    /* ── 💡說明在手機上的可視範圍 ────────────────────────────────
       量 2026-09-20 那份報告，390×844：

         三十八顆 💡 全部小於 36px，最小的是 15×12（那顆沒有文字的）
         四段說明比一整頁還長，最長 1282px ＝ 1.52 個螢幕

       小於 36px 的按鈕在觸控上不是「有點難按」，是**按不準**——手指的接觸面
       大約 45px 寬，而它旁邊就是別的字。字級不動，撐大的是可以按的範圍。

       說明用 max-height 夾住：1282px 的一段展開之後，它底下那一整頁內容會被
       推到一個半螢幕以外，而讀完要往回捲一整頁才找得到原來那顆 💡。夾成 60%
       螢幕之後它自己是一塊可以捲的區域，頁面的其他部分留在原地。
       寫兩次，第二次用 dvh：vh 量的是網址列收起來之後那個比較大的高度。 */
    .info-btn { min-width:36px; min-height:36px; }
    .fin-info-btn { min-width:36px; min-height:36px; }
    .expand-btn { min-height:36px; padding:7px 14px; }
    .info-popup { max-height:60vh; max-height:60dvh;
                  overflow-y:auto; overscroll-behavior:contain; }
  }

"""

SHARED_JS = """
  // Chart.js 由 CDN 載入。若使用者當下沒有網路，這裡先擋住，
  // 讓折疊、切換版型等互動仍然可用，不會整份報告變成死頁。
  if (typeof Chart === 'undefined') {
    window.Chart = null;
    console.warn('Chart.js 未載入（可能是沒有網路），圖表將無法顯示，其餘功能不受影響。');
  } else {
    Chart.defaults.color = '#94a3b8';
    Chart.defaults.font.family = "-apple-system, 'Microsoft JhengHei', sans-serif";
  }
  const chartRegistry = {};

  function fmtLabel(iso) {
    const d = new Date(iso + 'T00:00:00');
    return d.getFullYear() + '/' + String(d.getMonth() + 1).padStart(2,'0');
  }
  function fmtLabelShort(iso) {
    const d = new Date(iso + 'T00:00:00');
    return (d.getMonth() + 1) + '/' + d.getDate();
  }
  function fmtFullDate(iso) {
    if (!iso) return '';
    const d = new Date(iso + 'T00:00:00');
    return d.getFullYear() + '/' + String(d.getMonth() + 1).padStart(2,'0') + '/' + String(d.getDate()).padStart(2,'0');
  }
  function tooltipFullDateTitle(key) {
    return (items) => {
      if (!items.length) return '';
      const entry = chartRegistry[key];
      if (!entry) return items[0].label;
      const arr = entry.currentDates || entry.dates;
      const iso = arr ? arr[items[0].dataIndex] : null;
      return iso ? fmtFullDate(iso) : items[0].label;
    };
  }
  function gradientFill(c, rgb) {
    const g = c.chart.ctx.createLinearGradient(0, 0, 0, c.chart.height);
    g.addColorStop(0, `rgba(${rgb},0.30)`);
    g.addColorStop(1, `rgba(${rgb},0.02)`);
    return g;
  }
  function filterByRange(dates, tf) {
    const lastDate = new Date(dates[dates.length - 1] + 'T00:00:00');
    let fromDate;
    const daysMap = { '1M':30, '3M':90, '6M':182, '1Y':365, '3Y':365*3,
                      '5Y':365*5, '10Y':365*10, '20Y':365*20 };
    if (tf === 'ALL') {
      return 0;                       // 全部：不裁切
    } else if (tf === 'YTD') {
      fromDate = new Date(lastDate.getFullYear(), 0, 1);
    } else {
      fromDate = new Date(lastDate);
      fromDate.setDate(fromDate.getDate() - daysMap[tf]);
    }
    let idx = dates.findIndex(d => new Date(d + 'T00:00:00') >= fromDate);
    return idx === -1 ? 0 : idx;
  }
  function buildLegend(chart, boxId) {
    const box = document.getElementById(boxId);
    box.innerHTML = '';
    chart.data.datasets.forEach((ds, i) => {
      const item = document.createElement('span');
      item.className = 'legend-item';
      let icon = '';
      if (ds.type === 'bar') icon = `<span class="legend-icon-bar" style="background:${ds.backgroundColor}"></span>`;
      else if (ds.borderDash) icon = `<span class="legend-icon-dashed" style="border-color:${ds.borderColor}"></span>`;
      else icon = `<span class="legend-icon-solid" style="border-color:${ds.borderColor}"></span>`;
      item.innerHTML = icon + ds.label;
      item.onclick = () => {
        const meta = chart.getDatasetMeta(i);
        meta.hidden = meta.hidden === null ? !chart.data.datasets[i].hidden : !meta.hidden;
        item.classList.toggle('hidden-ds');
        chart.update();
      };
      box.appendChild(item);
    });
  }
  /* ---- 💡說明 ----
     三件事：展開／收起、把說明捲進可視範圍、在說明底端放一顆〔收起 ▲〕。

     那顆〔收起〕是 JS 塞的，不是每一段自己帶的。三十八段說明散在六個不同的
     產生點上（總經四組、美股總覽、村田、每一檔日股的 PBR 與年報方法），
     手工加會漏，而漏掉的那幾段不會有任何症狀——直到有人在手機上讀到底、
     然後找不到路回去。 */
  function infoBtnFor(id) {
    /* 呼叫端一律是 onclick="toggleInfo('xxx')"，所以從那裡回推。
       把按鈕當參數傳進來要改三十八個呼叫點，其中十五個在 f-string 裡。 */
    const needle = "('" + id + "')";
    for (const b of document.querySelectorAll('.info-btn, .fin-info-btn')) {
      if ((b.getAttribute('onclick') || '').indexOf(needle) >= 0) return b;
    }
    return null;
  }
  function toggleInfo(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const open = el.classList.toggle('open');
    const btn = infoBtnFor(id);
    if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (!open) {
      /* 收起之後把焦點還給那顆 💡。用鍵盤的人不會掉回文件開頭，
         用手機的人會看到頁面停在那顆鈕旁邊而不是跳走。 */
      if (btn) btn.focus({preventScroll: true});
      return;
    }
    if (!el.querySelector('.info-close')) {
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'info-close';
      x.textContent = '收起 ▲';
      x.addEventListener('click', () => toggleInfo(id));
      el.appendChild(x);
    }
    /* 'nearest'：說明就在按鈕正下方，多數時候只要往上挪一點點。用 'start'
       會把按鈕整個推出畫面，讀者失去「我剛剛按的是哪一顆」的線索。
       'instant'：這一頁有 scroll-behavior:smooth，而平滑捲動配上剛剛才變高的
       版面會捲到一個中途的位置。 */
    el.scrollIntoView({block: 'nearest', behavior: 'instant'});
  }

  /* ---- 折疊卡片 ----
     Chart.js 在 display:none 的容器裡會算出 0 寬，
     所以展開後一定要叫它重新量一次尺寸，否則圖會是空白的。 */
  function resizeChartsIn(el) {
    if (!el) return;
    el.querySelectorAll('canvas').forEach((cv) => {
      try {
        const inst = (window.Chart && typeof Chart.getChart === 'function')
          ? Chart.getChart(cv) : null;
        if (inst) inst.resize();
      } catch (e) { /* 個別圖失敗不影響其他 */ }
    });
  }

  /* ---- 標題列自動縮字 ----
     卡片收合後只剩一列，列高一致才好掃視。字太多時整列等比縮小，
     縮到下限仍塞不下就改成換行——寧可那一列高一點，也不要把資訊裁掉。 */
  function fitCardHead(head) {
    const main = head.querySelector('.card-head-main');
    const sum = head.querySelector('.card-summary');
    if (!main) return;

    main.classList.remove('allow-wrap');
    main.style.removeProperty('font-size');
    if (sum) {
      sum.classList.remove('compact');
      sum.style.removeProperty('font-size');
    }

    const overflowing = () => main.scrollWidth > main.clientWidth + 1;

    // 手機這種極窄寬度，硬塞成一列會縮到看不清。
    // 索性統一成「標題一列、摘要一列」，並把摘要縮到剛好一行，
    // 每張卡片結構相同，列高就會齊，字也還讀得到。
    if (main.clientWidth < 420) {
      main.classList.add('allow-wrap');
      if (sum) {
        sum.classList.add('compact');
        sum.style.removeProperty('font-size');
        let s = 100;
        while (sum.scrollWidth > sum.clientWidth + 1 && s > 62) {
          s -= 3;
          sum.style.setProperty('font-size', s + '%', 'important');
        }
      }
      return;
    }

    if (!overflowing()) return;

    // 每張卡片依自己的實際寬度調整，不靠螢幕斷點猜測——
    // 同樣的螢幕寬度下，單欄與雙欄的卡片可用寬度差很多。
    const shrink = (floor) => {
      let scale = 100;
      // 用 important 寫入，否則會被樣式表裡的 !important 規則蓋掉
      while (overflowing() && scale > floor) {
        scale -= 2;
        main.style.setProperty('font-size', scale + '%', 'important');
      }
    };

    shrink(84);                       // 第一步：小幅縮字，維持可讀性
    if (!overflowing()) return;

    if (sum) sum.classList.add('compact');   // 第二步：收起次要資訊，只留股價與警示
    main.style.removeProperty('font-size');
    if (!overflowing()) return;

    shrink(64);                       // 第三步：再縮一點
    if (overflowing()) {
      main.style.removeProperty('font-size');
      main.classList.add('allow-wrap');      // 最後手段：換行，絕不裁掉資訊
    }
  }

  function fitAllCardHeads() {
    document.querySelectorAll('.card-head').forEach(fitCardHead);
  }

  /* 版型、字型、捲軸出現都會改變可用寬度，靠固定時機量測容易量到還沒定案的尺寸。
     改用 ResizeObserver：寬度一有變動就重算，時機由瀏覽器決定，不會有競態。 */
  let fitting = false;
  function watchCardHeads() {
    if (typeof ResizeObserver === 'undefined') { fitAllCardHeads(); return; }
    const ro = new ResizeObserver(() => {
      if (fitting) return;            // 縮字本身會觸發尺寸變化，擋掉避免無限循環
      fitting = true;
      requestAnimationFrame(() => {
        fitAllCardHeads();
        requestAnimationFrame(() => { fitting = false; });
      });
    });
    document.querySelectorAll('.card-head').forEach((h) => ro.observe(h));
  }

  let fitTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(fitTimer);
    fitTimer = setTimeout(fitAllCardHeads, 150);
  });

  function toggleCard(id) {
    const card = document.querySelector('[data-card="' + id + '"]');
    if (!card) return;
    const opening = card.classList.contains('collapsed');
    card.classList.toggle('collapsed', !opening);
    const head = card.querySelector('.card-head');
    if (head) head.setAttribute('aria-expanded', String(opening));
    if (opening) setTimeout(() => resizeChartsIn(card), 30);
  }

  function setAllCards(collapsed) {
    document.querySelectorAll('.section-card[data-card]').forEach((card) => {
      card.classList.toggle('collapsed', collapsed);
      const head = card.querySelector('.card-head');
      if (head) head.setAttribute('aria-expanded', String(!collapsed));
    });
    /* 趨勢圖、歷史趨勢、速覽表都是 <details class="fold">。〔管理追蹤名單〕不算：
       它是表單，不是內容，〔全部展開〕把一張表單攤開不是任何人要的。 */
    document.querySelectorAll('details.fold:not(.manage-fold)').forEach((d) => {
      d.open = !collapsed;
    });
    if (!collapsed) setTimeout(() => resizeChartsIn(document.body), 40);
  }

  /* 打開報告時：兩層全部收合。第一眼是五條橫幅，展開哪一塊、
     那一塊裡面再看哪一張，都由讀者自己決定。 */
  function setInitialCardStates() {
    setAllCards(true);
  }

  /* 每次打開報告都從全部收合開始，先看摘要再決定要展開哪幾張。
     刻意不記住上次的展開狀態——若記住，久了會回到一打開就一長串的狀態。
     另外清掉舊版留下的紀錄，避免升級後還照著舊資料展開。 */
  function clearSavedCardStates() {
    try { localStorage.removeItem('mm_open_cards'); } catch (e) { /* 不支援就算了 */ }
  }
  function simpleSetRange(key, tf, btn) {
    document.querySelectorAll('#tf-' + key + ' .tf-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const entry = chartRegistry[key];
    let dates, close, vol;
    if (tf === '5D') {
      dates = entry.dates.slice(-5); close = entry.close.slice(-5);
      vol = entry.volume ? entry.volume.slice(-5) : null;
    } else {
      const idx = filterByRange(entry.dates, tf);
      dates = entry.dates.slice(idx); close = entry.close.slice(idx);
      vol = entry.volume ? entry.volume.slice(idx) : null;
    }
    const short = (tf === '5D' || tf === '1M' || tf === '3M');
    entry.chart.data.labels = dates.map(short ? fmtLabelShort : fmtLabel);
    entry.chart.data.datasets[0].data = close;
    entry.currentDates = dates;
    let nextIdx = 1;
    if (entry.warnLevels) {
      entry.warnLevels.forEach((lvl) => {
        entry.chart.data.datasets[nextIdx].data = dates.map(() => lvl);
        nextIdx++;
      });
    }
    if (entry.hasVolumeDataset && vol) {
      entry.chart.data.datasets[nextIdx].data = vol;
    }
    entry.chart.update();
  }
"""


TABS_JS = """
  function mmSetSelected(bar, attr, id) {
    let hit = false;
    bar.querySelectorAll('[role=tab]').forEach((b) => {
      const on = b.dataset[attr] === id;
      if (on) hit = true;
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
    });
    return hit;
  }
  function mmActiveTab() {
    const b = document.querySelector('.mm-tabs [aria-selected=true]');
    return b ? b.dataset.tab : '';
  }
  function mmActiveSub(tab) {
    const b = document.querySelector('#pane-' + tab + ' .mm-subtabs [aria-selected=true]');
    return b ? b.dataset.sub : '';
  }
  /* 記在網址的 # 後面（#tw/twmacro）。兩個用處：重新整理之後回到同一頁，以及
     〔新增個股〕跑完之後 mmWatch 會 location.replace 帶著 hash 回來——沒有這個，
     讀者會被丟回〔重點摘要〕，要自己再點回〔日股觀察〕看剛加的那一檔。 */
  function mmRemember() {
    const t = mmActiveTab(), s = mmActiveSub(t);
    try { history.replaceState(null, '', '#' + t + (s ? '/' + s : '')); } catch (e) {}
  }
  function mmShown(el) {
    if (!el) return;
    try {
      resizeChartsIn(el);
      requestAnimationFrame(fitAllCardHeads);   // 隱藏時量到的標題列寬度是 0
    } catch (e) { /* 上面那個 script 區塊壞掉的時候，分頁照樣要切得過去 */ }
  }
  function mmShowTab(id, sub, quiet) {
    const bar = document.querySelector('.mm-tabs');
    if (!bar || !mmSetSelected(bar, 'tab', id)) return false;
    document.querySelectorAll('.mm-pane').forEach((p) => { p.hidden = p.dataset.pane !== id; });
    if (sub) mmShowSub(id, sub, true);
    mmShown(document.getElementById('pane-' + id));
    if (!quiet) {
      mmRemember();
      /* 從〔重點摘要〕下面那幾列點過來的時候，分頁列可能已經捲出畫面上緣了。 */
      if (bar.getBoundingClientRect().top < 0) bar.scrollIntoView({block: 'start', behavior: 'instant'});
    }
    return true;
  }
  function mmShowSub(group, id, quiet) {
    const pane = document.getElementById('pane-' + group);
    const bar = pane && pane.querySelector('.mm-subtabs');
    if (!bar || !mmSetSelected(bar, 'sub', id)) return false;
    pane.querySelectorAll('.mm-subpane').forEach((p) => { p.hidden = p.dataset.subpane !== id; });
    mmShown(document.getElementById('subpane-' + id));
    if (!quiet) mmRemember();
    return true;
  }
  function mmRestoreTab() {
    let h = '';
    try { h = decodeURIComponent((location.hash || '').slice(1)); } catch (e) { return; }
    if (!h) return;
    const parts = h.split('/');
    mmShowTab(parts[0], parts[1], true);
  }
  /* 方向鍵在一排分頁裡移動（WAI-ARIA tabs 的慣例）。 */
  document.addEventListener('keydown', (ev) => {
    const t = ev.target;
    if (!t || t.getAttribute('role') !== 'tab') return;
    if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
    const all = Array.from(t.parentNode.querySelectorAll('[role=tab]'));
    const i = all.indexOf(t) + (ev.key === 'ArrowRight' ? 1 : -1);
    const next = all[(i + all.length) % all.length];
    if (next) { next.focus(); next.click(); ev.preventDefault(); }
  });
  /* 〔日股觀察〕的〔全部展開〕〔全部收合〕：只動個股卡，不動別頁的趨勢圖。 */
  function mmStockCards(collapsed) {
    document.querySelectorAll('.jp-stock-grid > .section-card[data-card]').forEach((card) => {
      card.classList.toggle('collapsed', collapsed);
      const head = card.querySelector('.card-head');
      if (head) head.setAttribute('aria-expanded', String(!collapsed));
    });
    if (!collapsed) setTimeout(() => mmShown(document.getElementById('pane-jpstock')), 40);
  }
  /* 趨勢圖收在 <details> 裡：打開的那一刻圖的容器才有寬度，量一次。 */
  document.addEventListener('toggle', (ev) => {
    if (ev.target && ev.target.open) setTimeout(() => resizeChartsIn(ev.target), 20);
  }, true);
"""


def render_taiex_section(taiex):
    dates_json = json.dumps(taiex["dates"], ensure_ascii=False)
    close_json = json.dumps(taiex["close"], ensure_ascii=False)
    value_json = json.dumps([round(v / 1e8, 2) for v in taiex["value_twd"]])
    source_note = taiex.get("source", "")
    fetched_at = taiex.get("fetched_at", "")

    dates = taiex["dates"]
    close = taiex["close"]
    value_bil = [round(v / 1e8, 2) for v in taiex["value_twd"]]

    last_close = close[-1]
    prev_close = close[-2] if len(close) > 1 else last_close
    diff = round(last_close - prev_close, 2)
    pct = round(diff / prev_close * 100, 2) if prev_close else 0.0
    last_date_disp = dates[-1].replace("-", "/")

    last_vol = value_bil[-1]
    avg10_vol = round(sum(value_bil[-10:]) / len(value_bil[-10:]), 2) if value_bil else 0
    diff_txt, chg_color = fmt_diff(diff, 2, pct)

    idx_buy = last_close < TAIEX_BUY_THRESHOLD
    vol_buy = avg10_vol < VOLUME_BUY_THRESHOLD_BIL

    last_data_date = datetime.strptime(dates[-1], "%Y-%m-%d").date()
    today_taipei = datetime.now(TAIPEI_TZ).date()
    gap_days = (today_taipei - last_data_date).days
    expected = today_taipei
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    if expected == today_taipei and datetime.now(TAIPEI_TZ).hour < 17:
        expected -= timedelta(days=1)
        while expected.weekday() >= 5:
            expected -= timedelta(days=1)
    stale = last_data_date < expected

    if stale:
        vintage_note = (f"⚠️ 最後資料 {dates[-1]}，TWSE 官方統計為盤後彙整報表，"
                        f"通常傍晚後才會有當天資料，這不代表抓取失敗")
    else:
        vintage_note = f"資料截至 {dates[-1]}"

    taiex_summary = (
        f'<span class="chip price {"up" if diff >= 0 else "down"}">'
        f'<span class="chip-v">{last_close:,.0f}</span><span class="chip-k">{diff_txt}</span></span>'
        + chip("成交", f"{last_vol:,.0f} 億")
        + ('<span class="chip buy solid">指數可布局</span>' if idx_buy else "")
        + ('<span class="chip buy solid">量能可布局</span>' if vol_buy else "")
    )
    taiex_body = f"""
  <div class="stat-grid">
    <div class="{stat_box_cls(idx_buy, 'buy')}">
      <div class="stat-label">最新加權指數 ({last_date_disp} 收盤){alert_badge(idx_buy, '可以考慮布局', 'buy')}</div>
      <div>
        <span class="stat-value" style="color:{chg_color};">{last_close:,.2f}</span>
        <span class="stat-chg" style="color:{chg_color};">{diff_txt}</span>
      </div>
      <div class="stat-sub">布局參考：&lt; {TAIEX_BUY_THRESHOLD:,} 點</div>
    </div>
    <div class="{stat_box_cls(vol_buy, 'buy')}">
      <div class="stat-label">當日成交金額 / 10日均量{alert_badge(vol_buy, '可以考慮布局', 'buy')}</div>
      <div class="stat-value">{last_vol:,.2f} 億 <span style="font-size:14px;color:var(--text-muted);font-weight:500;">/ 均量 {avg10_vol:,.2f} 億</span></div>
      <div class="stat-sub">布局參考：均量 &lt; {VOLUME_BUY_THRESHOLD_BIL:,} 億</div>
    </div>
  </div>

{fold_open("加權指數走勢圖")}
  <div class="tf-bar" id="tf-taiex">
    <span style="font-size:11px;color:#64748b;margin-right:2px;">週期切換:</span>
    <button class="tf-btn disabled" title="需要盤中即時逐筆資料，目前資料源（TWSE 每日收盤 API）只有日頻資料，暫不支援" onclick="return false;">1D</button>
    <button class="tf-btn" onclick="taiexSetRange('5D',this)">5D</button>
    <button class="tf-btn" onclick="taiexSetRange('1M',this)">1M</button>
    <button class="tf-btn" onclick="taiexSetRange('3M',this)">3M</button>
    <button class="tf-btn" onclick="taiexSetRange('6M',this)">6M</button>
    <button class="tf-btn" onclick="taiexSetRange('YTD',this)">YTD</button>
    <button class="tf-btn" onclick="taiexSetRange('1Y',this)">1Y</button>
    <button class="tf-btn" onclick="taiexSetRange('3Y',this)">3Y</button>
    <button class="tf-btn active" onclick="taiexSetRange('5Y',this)">5Y</button>
  </div>

  <div class="custom-legend" id="taiexLegend"></div>
  <div class="chart-container"><canvas id="taiexChart"></canvas></div>
{FOLD_CLOSE}

  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="https://www.google.com/finance/beta/quote/IX0001:TPE?type=area" target="_blank">Google</a>　｜　<a href="https://www.twse.com.tw/zh/trading/historical/fmtqik.html" target="_blank">TWSE</a>　｜　{vintage_note}
  </div>
"""
    if stale:
        taiex_summary += '<span class="chip warn">資料尚未更新到今天</span>'
    del taiex_summary
    section_html = taiex_body

    script = f"""
  const taiexDates = {dates_json};
  const taiexClose = {close_json};
  const taiexVol = {value_json};
  const TAIEX_BUY = {TAIEX_BUY_THRESHOLD};

  const taiexChart = new Chart(document.getElementById('taiexChart'), {{
    type: 'line',
    data: {{
      labels: taiexDates.map(fmtLabel),
      datasets: [
        {{
          label: '台股加權指數', data: taiexClose, borderColor: '#10b981',
          backgroundColor: (c) => gradientFill(c, '16,185,129'),
          fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4, borderWidth: 1.6,
          yAxisID: 'y', order: 1
        }},
        {{
          label: TAIEX_BUY.toLocaleString() + ' 布局參考線', data: taiexDates.map(() => TAIEX_BUY),
          borderColor: '#22d3ee', borderDash: [6,4], borderWidth: 1.5, pointRadius: 0,
          fill: false, yAxisID: 'y', order: 2
        }},
        {{
          label: '成交金額 (億元)', data: taiexVol, type: 'bar',
          backgroundColor: 'rgba(59,130,246,0.4)', borderRadius: 1,
          barPercentage: 0.85, categoryPercentage: 0.8, yAxisID: 'yVol', order: 3
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: 'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1',
          borderColor: '#334155', borderWidth: 1, padding: 10, boxPadding: 4,
          filter: (item) => !item.dataset.borderDash,
          callbacks: {{
            title: (items) => {{
              if (!items.length) return '';
              const iso = taiexCurrentDates[items[0].dataIndex];
              return iso ? iso.replace(/-/g, '/') : items[0].label;
            }},
            label: (item) => item.dataset.label.includes('成交金額')
              ? '成交金額：' + item.formattedValue + ' 億元' : '加權指數：' + item.formattedValue
          }}
        }}
      }},
      scales: {{
        x: {{ type: 'category', ticks: {{ maxTicksLimit: 8, maxRotation: 0, color: '#94a3b8' }}, grid: {{ color: 'rgba(38,51,77,0.35)' }} }},
        y: {{ position: 'left', title: {{ display:true, text:'加權指數 (點)', font:{{size:9.5}} }}, grid: {{ color:'rgba(38,51,77,0.35)' }} }},
        yVol: {{ position: 'right', title: {{ display:true, text:'成交金額 (億元)', font:{{size:9.5}} }}, grid: {{ drawOnChartArea:false }} }}
      }}
    }}
  }});
  buildLegend(taiexChart, 'taiexLegend');
  let taiexCurrentDates = taiexDates.slice();

  function taiexSetRange(tf, btn) {{
    document.querySelectorAll('#tf-taiex .tf-btn').forEach(b => {{ if (!b.classList.contains('disabled')) b.classList.remove('active'); }});
    btn.classList.add('active');
    let dates, close, vol;
    if (tf === '5D') {{
      dates = taiexDates.slice(-5); close = taiexClose.slice(-5); vol = taiexVol.slice(-5);
    }} else {{
      const idx = filterByRange(taiexDates, tf);
      dates = taiexDates.slice(idx); close = taiexClose.slice(idx); vol = taiexVol.slice(idx);
    }}
    const short = (tf === '5D' || tf === '1M' || tf === '3M');
    taiexChart.data.labels = dates.map(short ? fmtLabelShort : fmtLabel);
    taiexChart.data.datasets[0].data = close;
    taiexChart.data.datasets[1].data = dates.map(() => TAIEX_BUY);
    taiexChart.data.datasets[2].data = vol;
    taiexCurrentDates = dates;
    taiexChart.update();
  }}
"""
    return section_html, script


def michigan_zone(v):
    if v > 95:
        return "極度狂熱", "#ef4444"
    if v >= 75:
        return "安全常態", "#10b981"
    if v >= 60:
        return "觀望停滯", "#f59e0b"
    if v >= 50:
        return "景氣衰退", "#f97316"
    return "系統危機", "#ef4444"


def render_vix_section(vix):
    dates_json = json.dumps(vix["dates"], ensure_ascii=False)
    close_json = json.dumps(vix["close"], ensure_ascii=False)
    fetched_at = vix.get("fetched_at", "")
    dates, close = vix["dates"], vix["close"]

    last_val = close[-1]
    prev_val = close[-2] if len(close) > 1 else last_val
    diff = round(last_val - prev_val, 2)
    last_date_disp = dates[-1].replace("-", "/")
    pct = round(diff / prev_val * 100, 2) if prev_val else None
    diff_txt, chg_color = fmt_diff(diff, 2, pct)
    warn = last_val > VIX_WARN_THRESHOLD
    panic = last_val > VIX_PANIC_THRESHOLD

    zone_label = "高度恐慌" if panic else ("波動升溫" if warn else "市場平穩")
    zone_color = "#ef4444" if panic else ("#f59e0b" if warn else "#10b981")

    html = f"""
  <div class="sub-title">VIX 恐慌指數</div>
  <div class="{stat_box_cls(warn, 'warn')}" style="margin-bottom:14px;">
    <div class="stat-label">最新收盤 ({last_date_disp})
      <span class="zone-badge" style="background:rgba(0,0,0,0.25);color:{zone_color};border:1px solid {zone_color};">{zone_label}</span>
    </div>
    <div>
      <span class="stat-value" style="color:{chg_color};">{last_val:,.2f}</span>
      <span class="stat-chg" style="color:{chg_color};">{diff_txt}</span>
    </div>
    <div class="stat-sub">&lt;20 平穩｜&gt;20 不穩定・避險情緒上升｜&gt;30 高度恐慌</div>
  </div>

{fold_open("VIX 走勢圖")}
  <div class="tf-bar" id="tf-vix">
    <span style="font-size:11px;color:#64748b;margin-right:2px;">週期切換:</span>
    <button class="tf-btn" onclick="simpleSetRange('vix','5D',this)">5D</button>
    <button class="tf-btn" onclick="simpleSetRange('vix','1M',this)">1M</button>
    <button class="tf-btn" onclick="simpleSetRange('vix','3M',this)">3M</button>
    <button class="tf-btn" onclick="simpleSetRange('vix','6M',this)">6M</button>
    <button class="tf-btn" onclick="simpleSetRange('vix','YTD',this)">YTD</button>
    <button class="tf-btn" onclick="simpleSetRange('vix','1Y',this)">1Y</button>
    <button class="tf-btn" onclick="simpleSetRange('vix','3Y',this)">3Y</button>
    <button class="tf-btn active" onclick="simpleSetRange('vix','5Y',this)">5Y</button>
  </div>
  <div class="custom-legend" id="vixLegend"></div>
  <div class="chart-container short"><canvas id="vixChart"></canvas></div>
{FOLD_CLOSE}
  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="https://www.cboe.com/tradable_products/vix/vix_historical_data/" target="_blank">CBOE</a>　｜　{fetched_at}
  </div>
"""

    script = f"""
  const vixDates = {dates_json};
  const vixClose = {close_json};
  const vixChart = new Chart(document.getElementById('vixChart'), {{
    type: 'line',
    data: {{
      labels: vixDates.map(fmtLabel),
      datasets: [
        {{
          label: 'VIX 恐慌指數', data: vixClose, borderColor: '#f43f5e',
          backgroundColor: (c) => gradientFill(c, '244,63,94'),
          fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4, borderWidth: 1.6, order: 1
        }},
        {{
          label: '20 波動升溫', data: vixDates.map(() => {VIX_WARN_THRESHOLD}),
          borderColor: '#38bdf8', borderDash: [6,4], borderWidth: 1.4, pointRadius: 0, fill:false, order: 2
        }},
        {{
          label: '30 高度恐慌', data: vixDates.map(() => {VIX_PANIC_THRESHOLD}),
          borderColor: '#facc15', borderDash: [3,3], borderWidth: 1.6, pointRadius: 0, fill:false, order: 3
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: 'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1',
          borderColor: '#334155', borderWidth: 1, padding: 10, boxPadding: 4,
          filter: (item) => !item.dataset.borderDash,
          callbacks: {{ title: tooltipFullDateTitle('vix') }}
        }}
      }},
      scales: {{
        x: {{ type: 'category', ticks: {{ maxTicksLimit: 8, maxRotation: 0, color: '#94a3b8' }}, grid: {{ color: 'rgba(38,51,77,0.35)' }} }},
        y: {{ grid: {{ color: 'rgba(38,51,77,0.35)' }} }}
      }}
    }}
  }});
  buildLegend(vixChart, 'vixLegend');
  chartRegistry['vix'] = {{ chart: vixChart, dates: vixDates, close: vixClose, currentDates: vixDates.slice(), warnLevels: [{VIX_WARN_THRESHOLD}, {VIX_PANIC_THRESHOLD}] }};
"""
    return html, script


def _last_friday(year, month):
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = nxt - timedelta(days=1)
    return last_day - timedelta(days=(last_day.weekday() - 4) % 7)


def michigan_next_release(last_date_str):
    try:
        y, m = int(last_date_str[:4]), int(last_date_str[5:7])
    except (ValueError, IndexError):
        return None, None

    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    ry, rm = (ny + 1, 1) if nm == 12 else (ny, nm + 1)

    today = date.today()
    for _ in range(24):
        rel = _last_friday(ry, rm)
        if rel >= today:
            return (ny, nm), rel
        ry, rm = (ry + 1, 1) if rm == 12 else (ry, rm + 1)
    return (ny, nm), _last_friday(ry, rm)


def michigan_is_prelim(data):
    dates = (data or {}).get("dates") or []
    return bool(dates) and dates[-1] in set((data or {}).get("prelim") or [])


def michigan_vintage(michigan):
    dates = michigan["dates"]
    ym = dates[-1][:7]
    prelim = michigan_is_prelim(michigan)
    nxt = michigan.get("next_release") or None
    if nxt and nxt.get("date"):
        try:
            when = date.fromisoformat(nxt["date"])
        except ValueError:
            when = None
        if when and when >= date.today() - timedelta(days=1):
            kind = "終值" if nxt.get("what") == "final" else "初值"
            return (f"資料截至 {ym}{'（初值，公布後仍會修正）' if prelim else '（終值）'}"
                    f"｜{nxt.get('month')}月{kind}將於 {when.strftime('%m/%d')} 公布")
    if michigan.get("official_source"):
        return f"資料截至 {ym}{'（初值，公布後仍會修正）' if prelim else '（終值）'}"
    next_month, release_date = michigan_next_release(dates[-1])
    txt = f"資料截至 {ym}"
    if next_month and release_date:
        return txt + (f"（FRED 延遲一個月，{next_month[1]}月數據將於 "
                      f"{release_date.strftime('%m/%d')} 出現）")
    return txt + "（FRED 延遲一個月）"


def render_michigan_section(michigan):
    dates_json = json.dumps(michigan["dates"], ensure_ascii=False)
    close_json = json.dumps(michigan["close"], ensure_ascii=False)
    fetched_at = michigan.get("fetched_at", "")
    dates, close = michigan["dates"], michigan["close"]

    last_val = close[-1]
    prev_val = close[-2] if len(close) > 1 else last_val
    diff = round(last_val - prev_val, 2)
    last_date_disp = dates[-1][:7].replace("-", "/") + (" 初值" if michigan_is_prelim(michigan) else "")
    pct = round(diff / prev_val * 100, 2) if prev_val else None
    diff_txt, chg_color = fmt_diff(diff, 1, pct)
    warn = last_val < MICHIGAN_WARN_THRESHOLD
    zone_label, zone_color = michigan_zone(last_val)

    vintage_txt = michigan_vintage(michigan)

    html = f"""
  <div class="sub-title">密西根大學消費者信心指數</div>
  <div class="{stat_box_cls(warn, 'warn')}" style="margin-bottom:14px;">
    <div class="stat-label">最新值 ({last_date_disp})
      <span class="zone-badge" style="background:rgba(0,0,0,0.25);color:{zone_color};border:1px solid {zone_color};">{zone_label}</span>
    </div>
    <div>
      <span class="stat-value" style="color:{chg_color};">{last_val:,.1f}</span>
      <span class="stat-chg" style="color:{chg_color};">{diff_txt}</span>
    </div>
    <div class="stat-sub">警戒水位：&gt;95 過熱｜75-95 安全常態｜60-75 觀望停滯｜&lt;60 衰退警戒｜&lt;50 系統危機</div>
  </div>

{fold_open("消費者信心走勢圖")}
  <div class="tf-bar" id="tf-michigan">
    <span style="font-size:11px;color:#64748b;margin-right:2px;">週期切換:</span>
    <button class="tf-btn" onclick="simpleSetRange('michigan','1M',this)">1M</button>
    <button class="tf-btn" onclick="simpleSetRange('michigan','3M',this)">3M</button>
    <button class="tf-btn" onclick="simpleSetRange('michigan','6M',this)">6M</button>
    <button class="tf-btn" onclick="simpleSetRange('michigan','YTD',this)">YTD</button>
    <button class="tf-btn" onclick="simpleSetRange('michigan','1Y',this)">1Y</button>
    <button class="tf-btn" onclick="simpleSetRange('michigan','3Y',this)">3Y</button>
    <button class="tf-btn active" onclick="simpleSetRange('michigan','5Y',this)">5Y</button>
    <button class="tf-btn" onclick="simpleSetRange('michigan','10Y',this)">10Y</button>
    <button class="tf-btn" onclick="simpleSetRange('michigan','ALL',this)">全部</button>
  </div>
  <div class="custom-legend" id="michiganLegend"></div>
  <div class="chart-container short"><canvas id="michiganChart"></canvas></div>
{FOLD_CLOSE}
  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="https://www.sca.isr.umich.edu/" target="_blank">密西根大學 Surveys of Consumers</a>
    <span class="src-extra">　｜　<a href="https://fred.stlouisfed.org/series/UMCSENT" target="_blank">FRED</a></span>　｜　{vintage_txt}
  </div>
"""

    band_js = "".join([
        f"""
        {{ label: '{lbl}', data: miDates.map(() => {lvl}), borderColor: '{col}',
           borderDash: [5,4], borderWidth: 1.1, pointRadius: 0, fill:false, order: {i+2} }},"""
        for i, (lvl, col, lbl) in enumerate([
            (95, "#ef4444", "95 過熱警戒"), (75, "#10b981", "75 安全下緣"),
            (60, "#f59e0b", "60 衰退警戒"), (50, "#be123c", "50 系統危機"),
        ])
    ])

    script = f"""
  const miDates = {dates_json};
  const miClose = {close_json};
  function miZone(v) {{
    if (v > 95) return ['極度狂熱','#ef4444'];
    if (v >= 75) return ['安全常態','#10b981'];
    if (v >= 60) return ['觀望停滯','#f59e0b'];
    if (v >= 50) return ['景氣衰退','#f97316'];
    return ['系統危機','#ef4444'];
  }}
  const michiganChart = new Chart(document.getElementById('michiganChart'), {{
    type: 'line',
    data: {{
      labels: miDates.map(fmtLabel),
      datasets: [
        {{
          label: '密大消費者信心指數', data: miClose, borderColor: 'rgb(168,85,247)',
          backgroundColor: (c) => gradientFill(c, '168,85,247'),
          fill: true, tension: 0,
          // 點半徑跟著「目前顯示幾個點」走。視窗放寬到 25 年之後，固定 2px
          // 在「全部」那一檔會把線壓成一條由圓點組成的帶子。
          pointRadius: (ctx) => (ctx.chart.data.labels.length > 90 ? 0
                                 : (ctx.chart.data.labels.length > 36 ? 1.5 : 2)),
          pointHoverRadius: 5, borderWidth: 2, order: 1
        }},{band_js}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: 'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1',
          borderColor: '#334155', borderWidth: 1, padding: 10, boxPadding: 4,
          filter: (item) => !item.dataset.borderDash,
          callbacks: {{
            title: tooltipFullDateTitle('michigan'),
            afterLabel: (item) => {{
              if (item.dataset.borderDash) return '';
              const zInfo = miZone(item.parsed.y);
              return '目前區間：' + zInfo[0];
            }}
          }}
        }}
      }},
      scales: {{
        x: {{ type: 'category', ticks: {{ maxTicksLimit: 8, maxRotation: 0, color: '#94a3b8' }}, grid: {{ color: 'rgba(38,51,77,0.35)' }} }},
        y: {{ suggestedMin: 40, suggestedMax: 105, grid: {{ color: 'rgba(38,51,77,0.35)' }} }}
      }}
    }}
  }});
  buildLegend(michiganChart, 'michiganLegend');
  chartRegistry['michigan'] = {{ chart: michiganChart, dates: miDates, close: miClose, currentDates: miDates.slice(), warnLevels: [95,75,60,50] }};
"""
    return html, script


def render_nikkei_section(nikkei):
    dates_json = json.dumps(nikkei["dates"], ensure_ascii=False)
    close_json = json.dumps(nikkei["close"], ensure_ascii=False)
    fetched_at = nikkei.get("fetched_at", "")
    dates, close = nikkei["dates"], nikkei["close"]

    last_val = close[-1]
    prev_val = close[-2] if len(close) > 1 else last_val
    diff = round(last_val - prev_val, 2)
    pct = round(diff / prev_val * 100, 2) if prev_val else 0.0
    last_date_disp = dates[-1].replace("-", "/")
    diff_txt, chg_color = fmt_diff(diff, 2, pct)
    buy = last_val < NIKKEI_BUY_THRESHOLD

    nikkei_summary = (
        f'<span class="chip price {"up" if diff >= 0 else "down"}">'
        f'<span class="chip-v">{last_val:,.0f}</span><span class="chip-k">{diff_txt}</span></span>'
        + ('<span class="chip buy solid">可布局</span>' if buy else "")
    )
    nikkei_body = f"""
  <div class="{stat_box_cls(buy, 'buy')}" style="margin-bottom:16px;">
    <div class="stat-label">最新收盤 ({last_date_disp}){alert_badge(buy, '可以考慮布局', 'buy')}</div>
    <div>
      <span class="stat-value" style="color:{chg_color};">{last_val:,.2f}</span>
      <span class="stat-chg" style="color:{chg_color};">{diff_txt}</span>
    </div>
    <div class="stat-sub">布局參考：&lt; {NIKKEI_BUY_THRESHOLD:,}</div>
  </div>

{fold_open("日經225走勢圖")}
  <div class="tf-bar" id="tf-nikkei">
    <span style="font-size:11px;color:#64748b;margin-right:2px;">週期切換:</span>
    <button class="tf-btn" onclick="simpleSetRange('nikkei','5D',this)">5D</button>
    <button class="tf-btn" onclick="simpleSetRange('nikkei','1M',this)">1M</button>
    <button class="tf-btn" onclick="simpleSetRange('nikkei','3M',this)">3M</button>
    <button class="tf-btn" onclick="simpleSetRange('nikkei','6M',this)">6M</button>
    <button class="tf-btn" onclick="simpleSetRange('nikkei','YTD',this)">YTD</button>
    <button class="tf-btn" onclick="simpleSetRange('nikkei','1Y',this)">1Y</button>
    <button class="tf-btn" onclick="simpleSetRange('nikkei','3Y',this)">3Y</button>
    <button class="tf-btn active" onclick="simpleSetRange('nikkei','5Y',this)">5Y</button>
  </div>
  <div class="custom-legend" id="nikkeiLegend"></div>
  <div class="chart-container"><canvas id="nikkeiChart"></canvas></div>
{FOLD_CLOSE}
  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="https://finance.yahoo.com/quote/%5EN225/" target="_blank">Yahoo Finance</a>　｜　{fetched_at}
  </div>
"""
    del nikkei_summary
    section_html = nikkei_body

    script = f"""
  const nikkeiDates = {dates_json};
  const nikkeiClose = {close_json};
  const NIKKEI_BUY = {NIKKEI_BUY_THRESHOLD};
  const nikkeiChart = new Chart(document.getElementById('nikkeiChart'), {{
    type: 'line',
    data: {{
      labels: nikkeiDates.map(fmtLabel),
      datasets: [
        {{
          label: '日經225指數', data: nikkeiClose, borderColor: 'rgb(245,158,11)',
          backgroundColor: (c) => gradientFill(c, '245,158,11'),
          fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4, borderWidth: 1.6, order: 1
        }},
        {{
          label: NIKKEI_BUY.toLocaleString() + ' 布局參考線', data: nikkeiDates.map(() => NIKKEI_BUY),
          borderColor: '#3b82f6', borderDash: [6,4], borderWidth: 1.5, pointRadius: 0, fill:false, order: 2
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: 'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1',
          borderColor: '#334155', borderWidth: 1, padding: 10, boxPadding: 4,
          filter: (item) => !item.dataset.borderDash,
          callbacks: {{ title: tooltipFullDateTitle('nikkei') }}
        }}
      }},
      scales: {{
        x: {{ type: 'category', ticks: {{ maxTicksLimit: 8, maxRotation: 0, color: '#94a3b8' }}, grid: {{ color: 'rgba(38,51,77,0.35)' }} }},
        y: {{ grid: {{ color: 'rgba(38,51,77,0.35)' }} }}
      }}
    }}
  }});
  buildLegend(nikkeiChart, 'nikkeiLegend');
  chartRegistry['nikkei'] = {{ chart: nikkeiChart, dates: nikkeiDates, close: nikkeiClose, currentDates: nikkeiDates.slice(), warnLevels: [NIKKEI_BUY] }};
"""
    return section_html, script


def render_murata_bb_section(murata):
    quarters_json = json.dumps(murata["quarters"], ensure_ascii=False)
    bb_json = json.dumps(murata["bb_ratio"])
    mlcc_json = json.dumps(murata.get("bb_ratio_mlcc", [None] * len(murata["quarters"])))
    fetched_at = murata.get("fetched_at", "")
    source_url = murata.get("source_url", "")

    bb = murata["bb_ratio"]
    last_q, last_bb = murata["quarters"][-1], bb[-1]
    prev_bb = bb[-2] if len(bb) > 1 else last_bb
    diff = round(last_bb - prev_bb, 2)
    warn = last_bb > MURATA_BB_WARN_THRESHOLD
    bb_pct = round(diff / prev_bb * 100, 2) if prev_bb else None
    diff_txt, chg_color = fmt_diff(diff, 2, bb_pct)

    mlcc_series = murata.get("bb_ratio_mlcc", [])
    last_mlcc = next((v for v in reversed(mlcc_series) if v is not None), None)
    mlcc_warn = (last_mlcc is not None) and (last_mlcc > MURATA_BB_WARN_THRESHOLD)
    mlcc_html = f"""
    <div class="{stat_box_cls(mlcc_warn, 'warn')}" style="margin-top:12px;">
      <div class="stat-label">主力 MLCC 部門 B/B Ratio（官方最新單獨揭露值）{alert_badge(mlcc_warn, '反指標聖杯 ▼ 警示', 'warn')}</div>
      <div class="stat-value" style="color:{'#ef4444' if mlcc_warn else '#10b981'};">{last_mlcc:.2f}</div>
      <div class="stat-sub">&gt; {MURATA_BB_WARN_THRESHOLD} = 反指標聖杯警示 ｜ 官方僅在特定季度法說會口頭揭露 MLCC 部門單獨數字，非每季固定揭露</div>
    </div>""" if last_mlcc is not None else ""

    murata_body = f"""
  <div class="title-row">
    <div class="section-title" style="margin-bottom:0;">村田製作所 (6981.T) B/B Ratio（訂單出貨比）</div>
    <button class="info-btn" onclick="toggleInfo('murataInfo')" title="反指標聖杯" aria-label="說明：反指標聖杯">💡</button>
  </div>
  <div id="murataInfo" class="info-popup">為何 B/B Ratio 突破 1.2 會成為「反指標聖杯 ▼」？

正常景氣擴張期，B/B Ratio 上升代表產業復甦；但村田 MLCC 的 B/B Ratio 一旦突破 1.2，通常代表景氣已進入過熱甚至末端瘋狂階段。被動元件產量大、單價低，極易受下游廠商「重複下單（Double Booking）」扭曲——當下游怕拿不到貨而超額訂貨，B/B Ratio 暴衝到 1.2 以上時，往往也代表需求熱度已到臨界點，一旦供應鏈發現零組件過剩，訂單將斷崖式下修。歷史規律：村田 B/B Ratio 突破 1.2，往往領先台股指數與被動元件股價見到中期高點約 1～1.5 個月，是科技股投資人用來判斷「該不該逃頂」的關鍵指標，而非追價訊號。</div>

  <div class="{stat_box_cls(warn, 'warn')}">
    <div class="stat-label">最新季度 ({last_q}){alert_badge(warn, '反指標聖杯 ▼ 警示', 'warn')}</div>
    <div>
      <span class="stat-value" style="color:{'#ef4444' if warn else '#10b981'};">{last_bb:.2f}</span>
      <span class="stat-chg" style="color:{chg_color};">{diff_txt} 較上季</span>
    </div>
    <div class="stat-sub">1.0 = 訂單/出貨均衡 ｜ &gt; {MURATA_BB_WARN_THRESHOLD} = 反指標聖杯警示</div>
  </div>
  {mlcc_html}

{fold_open("B/B Ratio 走勢圖")}
  <div class="custom-legend" id="murataLegend"></div>
  <div class="chart-container" style="height:320px;"><canvas id="murataChart"></canvas></div>
{FOLD_CLOSE}

  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="{source_url}" target="_blank">村田法說會</a>　｜　人工登錄　｜　資料截至 {last_q}　｜　每季法說會後更新（約 4月底・7月底・10月底・2月初）
  </div>
"""
    murata_summary = (chip("B/B", f"{last_bb:.2f}")
                      + (chip("MLCC", f"{last_mlcc:.2f}") if last_mlcc is not None else "")
                      + ('<span class="chip warn solid">反指標警示</span>' if (warn or mlcc_warn) else ""))
    del murata_summary
    section_html = murata_body

    script = f"""
  const murataQuarters = {quarters_json};
  const murataBB = {bb_json};
  const murataMLCC = {mlcc_json};
  const MURATA_WARN = {MURATA_BB_WARN_THRESHOLD};

  const murataChart = new Chart(document.getElementById('murataChart'), {{
    type: 'bar',
    data: {{
      labels: murataQuarters,
      datasets: [
        {{
          label: '全公司 B/B Ratio', data: murataBB,
          backgroundColor: murataBB.map(v => v > MURATA_WARN ? 'rgba(239,68,68,0.7)' : (v >= 1.0 ? 'rgba(16,185,129,0.6)' : 'rgba(148,163,184,0.5)')),
          borderRadius: 3, barPercentage: 0.6, order: 1
        }},
        {{
          label: 'MLCC 部門 B/B Ratio', data: murataMLCC,
          type: 'line', borderColor: '#a855f7', backgroundColor: '#a855f7',
          borderWidth: 2, pointRadius: 5, pointStyle: 'rectRot', showLine: false, order: 0,
          spanGaps: false
        }},
        {{
          label: '1.0 均衡線', data: murataQuarters.map(() => 1.0),
          type: 'line', borderColor: '#94a3b8', borderDash: [6,4], borderWidth: 1.3, pointRadius: 0,
          fill: false, order: 2
        }},
        {{
          label: MURATA_WARN + ' 反指標聖杯', data: murataQuarters.map(() => MURATA_WARN),
          type: 'line', borderColor: '#ef4444', borderDash: [3,3], borderWidth: 1.5, pointRadius: 0,
          fill: false, order: 3
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: 'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1',
          borderColor: '#334155', borderWidth: 1, padding: 10, boxPadding: 4,
          filter: (item) => item.dataset.label.includes('B/B Ratio') && item.raw !== null
        }}
      }},
      scales: {{
        x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ display:false }} }},
        y: {{ suggestedMin: 0.6, suggestedMax: 1.4, ticks: {{ color: '#94a3b8' }}, grid: {{ color:'rgba(38,51,77,0.35)' }} }}
      }}
    }}
  }});
  buildLegend(murataChart, 'murataLegend');
"""
    return section_html, script


def short_host(url):
    host = url.split("//")[-1].split("/")[0]
    return host[4:] if host.startswith("www.") else host


def source_links(urls, limit=2):
    urls = [u for u in (urls or []) if u]
    if not urls:
        return ""
    first = urls[0]
    html = f'<a href="{first}" target="_blank">{short_host(first)}</a>'
    rest = urls[1:limit]
    if rest:
        extra = " ｜ ".join(f'<a href="{u}" target="_blank">{short_host(u)}</a>' for u in rest)
        html += f'<span class="src-extra">　｜　{extra}</span>'
    if len(urls) > limit:
        html += f'<span class="src-extra" style="opacity:.7"> +{len(urls) - limit}</span>'
    return html


def fold_open(label):
    return (f'<div class="chart-block"><div class="chart-cap">📈 {label}</div>')


FOLD_CLOSE = "</div>"


def ind_block(html, tone):
    return f'<div class="ind-block" style="--ind:{tone};">{html}</div>' if html else ""


IND_TONES = ("#38bdf8", "#f59e0b", "#a78bfa", "#34d399", "#f472b6", "#facc15")


def collapsible(card_id, title, summary_html, body_html, open_by_default=False,
                alert=False, actions_html=""):
    collapsed_cls = "" if open_by_default else " collapsed"
    acts = f'<span class="card-acts">{actions_html}</span>' if actions_html else ""
    if actions_html:
        collapsed_cls += " has-acts"
    return f"""
<div class="section-card{collapsed_cls}" id="card-{card_id}" data-card="{card_id}">
  <button class="card-head" type="button" onclick="toggleCard('{card_id}')" aria-expanded="{str(open_by_default).lower()}">
    <span class="card-head-main">
      <span class="card-title">{title}</span>
      <span class="card-summary">{summary_html}</span>
    </span>
    <span class="card-chev" aria-hidden="true">⌄</span>
  </button>
  {acts}
  <div class="card-body">
{body_html}
  </div>
</div>
"""


BLOCK_TONES = {
    "summary": "#f59e0b",
    "tw":      "#22d3ee",
    "us":      "#3b82f6",
    "jp":      "#a855f7",
    "jpstock": "#10b981",
}


MANAGE_WORKFLOW = "manage.yml"

MANAGE_ACTIONS = (
    "只更新報告", "新增個股", "建立或重建季報",
)

CARD_ACTIONS = (
    "隱藏個股",
    "恢復顯示",
    "移除個股",
)

LOCAL_FIRST_ACTIONS = ("隱藏個股", "移除個股")

REBUILD_ACTIONS = tuple(
    a for a in MANAGE_ACTIONS + CARD_ACTIONS if a not in LOCAL_FIRST_ACTIONS
)

MANAGE_FIELD_HINTS = {
    "action": "要做什麼",
    "code": "股票代號或檔名代號（例如 4063 或 shinetsu）",
    "price_buy": "股價布局參考線（選填，新增個股時用）",
    "per_buy": "本益比布局參考線（選填，留空用預設 20）",
    "years": "季報回溯年數（預設 2）",
}


def repo_slug():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        try:
            out = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                capture_output=True, text=True, timeout=5,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            ).stdout.strip()
        except Exception:
            out = ""
        if out:
            tail = out.split("github.com", 1)[-1].lstrip(":/")
            repo = tail[:-4] if tail.endswith(".git") else tail
    return repo if repo.count("/") == 1 else ""


def manage_url():
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        try:
            out = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                capture_output=True, text=True, timeout=5,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            ).stdout.strip()
        except Exception:
            out = ""
        if out:
            tail = out.split("github.com", 1)[-1].lstrip(":/")
            repo = tail[:-4] if tail.endswith(".git") else tail
    if not repo or repo.count("/") != 1:
        return ""
    return f"{server}/{repo}/actions/workflows/{MANAGE_WORKFLOW}"


def render_manage_bar(with_status=True):
    repo = repo_slug()
    if not repo:
        return ""
    actions = "".join(
        f'<option value="{a}">{a}</option>' for a in MANAGE_ACTIONS
    )
    pat_url = (
        "https://github.com/settings/personal-access-tokens/new"
    )
    h = MANAGE_FIELD_HINTS
    eye_js = json.dumps(ICON_EYE)
    local_first_js = json.dumps({a: 1 for a in LOCAL_FIRST_ACTIONS}, ensure_ascii=False)
    rebuild_js = json.dumps({a: 1 for a in REBUILD_ACTIONS}, ensure_ascii=False)
    return f"""
  <div class="manage-bar">
    <form class="manage-form" onsubmit="return mmDispatch(event)">
      <label class="mm-field"><span class="mm-lab">{h["action"]}<span class="req">*</span></span>
        <select id="mmAction">{actions}</select></label>
      <label class="mm-field"><span class="mm-lab">{h["code"]}</span>
        <input id="mmCode" type="text" inputmode="latin"></label>
      <label class="mm-field"><span class="mm-lab">{h["price_buy"]}</span>
        <input id="mmPrice" type="text" inputmode="decimal"></label>
      <label class="mm-field"><span class="mm-lab">{h["per_buy"]}</span>
        <input id="mmPer" type="text" inputmode="decimal"></label>
      <label class="mm-field"><span class="mm-lab">{h["years"]}</span>
        <input id="mmYears" type="text" inputmode="numeric" value="2"></label>
      <div class="mm-field"><button type="submit" id="mmGo">送出</button></div>
    </form>
    {render_manage_status() if with_status else ""}
    <details class="manage-token">
      <summary>輸入權杖</summary>
      <div class="manage-token-body">
        <div class="manage-token-row">
          <input id="mmToken" type="password" placeholder="github_pat_…"
                 autocomplete="off" aria-label="GitHub 權杖">
          <button type="button" onclick="mmSaveToken()">儲存</button>
          <button type="button" onclick="mmClearToken()">清除</button>
        </div>
        <div class="manage-token-state" id="mmTokenState"></div>
        <p class="manage-token-how"><a href="{pat_url}" target="_blank"
        rel="noopener" title="Only select repositories → {repo}；Permissions → Actions: Read and write；設一個到期日"
        >去 GitHub 建一把</a></p>
      </div>
    </details>
  </div>
  <script>
  // 這一塊的全部狀態：一把權杖，存在 localStorage。沒有別的。
  const MM_REPO  = {json.dumps(repo)};
  const MM_WF    = {json.dumps(MANAGE_WORKFLOW)};
  const MM_KEY   = 'mm.gh.token';

  function mmToken()  {{ try {{ return localStorage.getItem(MM_KEY) || ''; }} catch (e) {{ return ''; }} }}
  function mmSay(msg, kind) {{
    const el = document.getElementById('mmStatus');
    el.textContent = msg;
    el.className = 'manage-status' + (kind ? ' ' + kind : '');
  }}
  function mmTokenState() {{
    const el = document.getElementById('mmTokenState');
    if (!el) return;
    el.textContent = mmToken() ? '已存在這台裝置的瀏覽器裡。' : '尚未設定。';
  }}
  function mmSaveToken() {{
    const v = document.getElementById('mmToken').value.trim();
    try {{ v ? localStorage.setItem(MM_KEY, v) : localStorage.removeItem(MM_KEY); }} catch (e) {{}}
    document.getElementById('mmToken').value = '';
    mmTokenState();
    mmSay(v ? '權杖已儲存。' : '權杖已清除。', 'ok');
  }}
  function mmClearToken() {{
    try {{ localStorage.removeItem(MM_KEY); }} catch (e) {{}}
    mmTokenState();
    mmSay('權杖已清除。', 'ok');
  }}

  // 表單那條路：把五個欄位收成 inputs，交給 mmSend。
  function mmDispatch(ev) {{
    ev.preventDefault();
    const action = document.getElementById('mmAction').value;
    const code   = document.getElementById('mmCode').value.trim();
    // 只有「只更新報告」不需要代號。擋在這裡而不是讓 workflow 跑一趟再失敗：
    // 那一趟要兩分鐘，而錯誤訊息會出現在一個你已經離開的頁面上。
    if (!code && action !== '只更新報告') {{
      mmSay('這個動作要填代號。', 'warn');
      return false;
    }}
    const inputs = {{ action: action }};
    if (code) inputs.code = code;
    const price = document.getElementById('mmPrice').value.trim();
    const per   = document.getElementById('mmPer').value.trim();
    const years = document.getElementById('mmYears').value.trim();
    if (price) inputs.price_buy = price;
    if (per)   inputs.per_buy   = per;
    if (years) inputs.years     = years;
    mmSend(inputs, document.getElementById('mmGo'));
    return false;
  }}

  // ── 先在畫面上做掉，再讓雲端補存檔 ──────────────────────────────
  //
  // 〔隱藏個股〕與〔移除個股〕在畫面上是同一件事：把這張卡片拿掉。瀏覽器自己
  // 做得到，一毫秒的事。以前它要等雲端跑完整趟——而那一趟裡真正跟這顆按鈕有關
  // 的工作是「把 config.json 裡的一個布林值改掉」，其餘幾分鐘是在重抓 TAIEX
  // 五年、二十幾條 FRED 二十五年、還有另外十幾檔個股（見 manage.yml 那一段）。
  //
  // 所以順序倒過來：按下去先把畫面改好，dispatch 照送，雲端那一趟降級成背景的
  // 存檔動作。跑成功就什麼都不用做（畫面早就是對的），失敗才把畫面還原回去。
  //
  // 〔恢復顯示〕做不到同一件事，而且理由很硬：要還原的那張卡片**不在**這一頁
  // 上——隱藏中的個股根本沒有被畫出來，它的圖表、季報、布局線都沒有一起送下來。
  // 這種一定要伺服器重畫的動作，改成跑完之後自動重新整理（見 mmWatch）。
  const MM_LOCAL_FIRST = {local_first_js};
  const MM_NEEDS_REBUILD = {rebuild_js};

  function mmBumpCount(delta) {{
    const el = document.getElementById('mm-watch-count');
    if (!el) return;
    const n = parseInt(el.textContent, 10);
    if (isNaN(n)) return;
    el.textContent = (n + delta) + ' 檔';
    // 〔重點摘要〕的速覽列上有同一個數字的副本（id 不能重複，所以它掛的是
    // data-mirror）。只改一邊的話，兩頁會各說各話。
    const mirrors = document.querySelectorAll ? document.querySelectorAll('[data-mirror="mm-watch-count"]') : [];
    for (const m of mirrors) m.textContent = el.textContent;
  }}

  function mmHiddenRow() {{ return document.getElementById('mm-hidden-row'); }}

  // 回傳一個「怎麼還原回去」的小包裹，失敗時交給 mmLocalRevert。記下 next 是
  // 為了插回**原來的位置**：append 回去的話，還原之後卡片會跑到最後一張。
  function mmLocalApply(action, btn) {{
    const code = btn.dataset.code || '';
    const card = document.getElementById('card-' + code);
    if (!card || !card.parentNode) return null;
    const undo = {{ card: card, grid: card.parentNode, next: card.nextSibling, chip: null }};
    card.parentNode.removeChild(card);
    if (action === '隱藏個股') {{
      const row = mmHiddenRow();
      if (row) {{
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'hidden-chip';
        chip.dataset.code = code;
        const name = btn.dataset.name || code;
        chip.title = '恢復顯示 ' + name;
        // 圖示是一個寫死的常數（見 ICON_EYE），所以 innerHTML 這裡沒有注入面：
        // 唯一會變的是名字與代號，而那兩個都走 textContent。
        chip.innerHTML = {eye_js};
        const nm = document.createElement('span');
        nm.textContent = name;
        chip.appendChild(nm);
        const tick = document.createElement('span');
        tick.className = 'hidden-code';
        tick.textContent = btn.dataset.ticker || '';
        chip.appendChild(tick);
        chip.onclick = function () {{ return mmCardAct(chip, '恢復顯示'); }};
        row.appendChild(chip);
        row.hidden = false;
        undo.chip = chip;
      }}
    }}
    mmBumpCount(-1);
    return undo;
  }}

  function mmLocalRevert(undo) {{
    if (!undo) return;
    if (undo.chip && undo.chip.parentNode) undo.chip.parentNode.removeChild(undo.chip);
    const row = mmHiddenRow();
    if (row && !row.querySelector('.hidden-chip')) row.hidden = true;
    undo.grid.insertBefore(undo.card, undo.next);
    mmBumpCount(1);
  }}

  // 送出與盯梢。表單與卡片上那幾顆按鈕共用這一條——兩份實作會在其中一邊改了
  // 錯誤處理之後安靜地不一樣。
  async function mmSend(inputs, btn) {{
    const token = mmToken();
    if (!token) {{
      mmSay('還沒設定權杖——展開〔輸入權杖〕貼一次就好。', 'warn');
      return false;
    }}
    btn.disabled = true;
    const action = inputs.action || '';
    // 畫面先改。送不出去的三種情況（權杖壞、網路斷、GitHub 回非 204）在下面
    // 每一條 return 之前都會 mmLocalRevert，所以不會留下一張「看起來隱藏了、
    // 其實沒有」的畫面。
    const undo = MM_LOCAL_FIRST[action] ? mmLocalApply(action, btn) : null;
    mmSay(undo ? '已更新畫面，正在存回雲端…' : '送出中…');
    const since = new Date().toISOString();
    try {{
      const r = await fetch(
        'https://api.github.com/repos/' + MM_REPO + '/actions/workflows/' + MM_WF + '/dispatches',
        {{
          method: 'POST',
          headers: {{
            'Accept': 'application/vnd.github+json',
            'Authorization': 'Bearer ' + token,
            'X-GitHub-Api-Version': '2022-11-28',
            'Content-Type': 'application/json'
          }},
          body: JSON.stringify({{ ref: 'main', inputs: inputs }})
        }}
      );
      // 每一個錯誤碼講的是不同的事，而「失敗了」對修它沒有幫助。
      if (r.status === 401) {{ mmLocalRevert(undo); mmSay('權杖無效或已過期——重新設定一把。', 'bad'); btn.disabled = false; return false; }}
      if (r.status === 403) {{ mmLocalRevert(undo); mmSay('權杖權限不足：要 Actions 的 Read and write。', 'bad'); btn.disabled = false; return false; }}
      if (r.status === 404) {{ mmLocalRevert(undo); mmSay('找不到 ' + MM_REPO + ' 的 ' + MM_WF + '——權杖有沒有勾到這個 repo？', 'bad'); btn.disabled = false; return false; }}
      if (r.status !== 204) {{
        let msg = '';
        try {{ msg = (await r.json()).message || ''; }} catch (e) {{}}
        mmLocalRevert(undo);
        mmSay('送不出去（HTTP ' + r.status + '）' + (msg ? '：' + msg : ''), 'bad');
        btn.disabled = false; return false;
      }}
    }} catch (e) {{
      mmLocalRevert(undo);
      mmSay('連不上 GitHub：' + e.message, 'bad');
      btn.disabled = false; return false;
    }}
    if (!undo) mmSay('已送出，雲端開始跑了…');
    mmWatch(token, since, btn, {{ undo: undo, reload: !!MM_NEEDS_REBUILD[action] }});
    return false;
  }}

  // 盯著那一趟跑完沒有。
  //
  // dispatch 回的是 204、沒有 body，所以拿不到 run id——只能回頭去問「這個
  // workflow 最新一趟是什麼時候開始的」，並且只認**送出之後**才建立的那一趟。
  // 不比時間的話，畫面會立刻顯示上一次的結果，看起來像三秒就跑完了。
  //
  // `opts.reload`：這個動作改的東西只有伺服器畫得出來（新的一張卡、新的季報、
  // 重抓過的資料），所以跑完就自己重新整理，不再要求使用者手動按一次。
  // `opts.undo`：這個動作已經先在畫面上做掉了，跑失敗要還原回去。
  async function mmWatch(token, since, btn, opts) {{
    opts = opts || {{}};
    const started = Date.parse(since);
    for (let i = 0; i < 100; i++) {{            // 100 × 6 秒 ≈ 10 分鐘
      await new Promise(r => setTimeout(r, 6000));
      let run = null;
      try {{
        const r = await fetch(
          'https://api.github.com/repos/' + MM_REPO + '/actions/workflows/' + MM_WF + '/runs?per_page=5',
          {{ headers: {{ 'Accept': 'application/vnd.github+json',
                        'Authorization': 'Bearer ' + token,
                        'X-GitHub-Api-Version': '2022-11-28' }} }}
        );
        const j = await r.json();
        run = (j.workflow_runs || []).find(x => Date.parse(x.created_at) >= started - 5000);
      }} catch (e) {{ continue; }}
      if (!run) {{ if (!opts.undo) mmSay('已送出，排隊中…'); continue; }}
      if (run.status !== 'completed') {{
        mmSay(opts.undo ? '存回雲端中…（' + run.status + '）' : '執行中…（' + run.status + '）');
        continue;
      }}
      btn.disabled = false;
      if (run.conclusion === 'success') {{
        if (opts.reload) {{
          mmSay('完成了，重新整理…', 'ok');
          // 為什麼要帶一個時間戳：Pages 前面有 CDN，瀏覽器自己也快取 index.html。
          // 直接 location.reload() 有機會拿回剛剛那一份舊的，然後畫面看起來像
          // 「跑完了但什麼都沒變」——那比不自動重新整理更難解釋。
          // 展開了哪幾張卡片記在 localStorage 裡，換一個查詢字串不影響它。
          location.replace(location.pathname + '?t=' + Date.now() + location.hash);
          return;
        }}
        mmSay('完成了，已經存回雲端。', 'ok');
      }} else {{
        mmLocalRevert(opts.undo);
        mmSay('那一趟沒有成功（' + run.conclusion + '）。'
              + (opts.undo ? '畫面已還原成原本的樣子。' : '') + '到 Actions 看 log。', 'bad');
      }}
      return;
    }}
    btn.disabled = false;
    // 這裡**不**還原畫面：等太久不等於失敗，多半是 runner 在排隊。這時候把卡片
    // 變回來，而雲端過三分鐘又真的把它隱藏了，畫面與名單就對不上了。說清楚狀態
    // 是懸著的，讓使用者自己決定要不要重新整理。
    mmSay('等太久了，這一頁不再盯著'
          + (opts.undo ? '（畫面維持你剛剛操作後的樣子）' : '')
          + '。到 Actions 看它跑完了沒。', 'warn');
  }}

  // ── 貼在股票旁邊的那幾顆按鈕 ────────────────────────────────────
  //
  // 個股卡右上角的閉眼／垃圾桶，以及底下那一列隱藏中的股票上的睜眼。走的是和
  // 上面那張表單**完全一樣**的一條路（mmSend），差別只在代號從 data-code 來，
  // 不是從輸入框來——所以按鈕不可能把代號打錯。
  //
  // 垃圾桶要按兩下才會真的送出：隱藏按睜眼就還原得回來，移除不行。第一下把按鈕
  // 換成「再按一次」，四秒沒有第二下就自己變回去。不用 confirm()：那會鎖住整個
  // 分頁，而這一頁上還有十幾張圖在跑。
  function mmCardAct(btn, action) {{
    const code = btn.dataset.code || '';
    if (!code) return false;
    if (btn.classList.contains('danger') && !btn.dataset.armed) {{
      // 只換顏色，**不換文字**：按鈕變寬會把卡片的摘要列擠掉。要再按一次這件事
      // 寫在狀態列上，那裡本來就是這一塊講話的地方。
      btn.dataset.armed = '1';
      btn.classList.add('armed');
      mmSay('再按一次垃圾桶才會把 ' + code + ' 從名單移除。', 'warn');
      setTimeout(function () {{
        if (!btn.dataset.armed) return;
        delete btn.dataset.armed;
        btn.classList.remove('armed');
        mmSay('');
      }}, 4000);
      return false;
    }}
    delete btn.dataset.armed;
    btn.classList.remove('armed');
    mmSend({{ action: action, code: code }}, btn);
    return false;
  }}

  document.addEventListener('DOMContentLoaded', mmTokenState);
  </script>"""


def render_manage_status():
    return '<div class="manage-status" id="mmStatus" role="status"></div>'


def render_hidden_row(hidden):
    chips = "".join(
        '<button type="button" class="hidden-chip" '
        f'data-code="{s["key"]}" onclick="return mmCardAct(this,\'恢復顯示\')" '
        f'title="恢復顯示 {s["name"]}">{ICON_EYE}<span>{s["name"]}</span>'
        f'<span class="hidden-code">{s["code"]}</span></button>'
        for s in hidden
    )
    blank = "" if hidden else " hidden"
    return (
        f'<div class="hidden-row" id="mm-hidden-row"{blank}>'
        '<span class="hidden-label">隱藏中</span>'
        f'{chips}</div>'
    )


def render_tabs(panes):
    buttons, bodies = [], []
    for i, (pid, title, badge, body) in enumerate(panes):
        tone = BLOCK_TONES.get(pid, "#64748b")
        sel = "true" if i == 0 else "false"
        tab_index = "" if i == 0 else ' tabindex="-1"'
        buttons.append(
            f'<button type="button" role="tab" class="mm-tab" id="tab-{pid}" data-tab="{pid}" '
            f'aria-controls="pane-{pid}" aria-selected="{sel}"{tab_index} style="--blk:{tone};" '
            f'onclick="mmShowTab(\'{pid}\')">{title}{badge}</button>')
        hidden = "" if i == 0 else " hidden"
        bodies.append(
            f'<section class="mm-pane" id="pane-{pid}" data-pane="{pid}" role="tabpanel" '
            f'aria-labelledby="tab-{pid}" style="--blk:{tone};"{hidden}>\n{body}\n</section>')
    return (f'<div class="mm-tabs" role="tablist" aria-label="報告分頁">{"".join(buttons)}</div>\n'
            + "\n".join(bodies))


SUBTAB_TONES = ("#ffa94d", "#4fd6c4", "#6fb0f5", "#f783ac", "#b39cff", "#69db7c")


def sub_tabs(group, items):
    if not items:
        return ""
    buttons, bodies = [], []
    for i, (sid, title, body) in enumerate(items):
        tone = SUBTAB_TONES[i % len(SUBTAB_TONES)]
        sel = "true" if i == 0 else "false"
        tab_index = "" if i == 0 else ' tabindex="-1"'
        buttons.append(
            f'<button type="button" role="tab" class="mm-subtab" style="--tc:{tone};" id="sub-{sid}" data-sub="{sid}" '
            f'aria-controls="subpane-{sid}" aria-selected="{sel}"{tab_index} '
            f'onclick="mmShowSub(\'{group}\', \'{sid}\')">{title}</button>')
        hidden = "" if i == 0 else " hidden"
        bodies.append(
            f'<div class="mm-subpane" id="subpane-{sid}" data-subpane="{sid}" role="tabpanel" '
            f'aria-labelledby="sub-{sid}"{hidden}>\n{body}\n</div>')
    return (f'<div class="mm-subtabs" role="tablist">{"".join(buttons)}</div>\n'
            + "\n".join(bodies))


def pane_chips(chips):
    return f'<div class="pane-chips">{"".join(chips)}</div>' if chips else ""


_ICON = ('<svg viewBox="0 0 24 24" width="16" height="16" fill="none" '
         'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
         'stroke-linejoin="round" aria-hidden="true">{}</svg>')

ICON_EYE = _ICON.format(
    '<path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"/>'
    '<circle cx="12" cy="12" r="2.6"/>'
)

ICON_EYE_OFF = _ICON.format(
    '<path d="M2.6 9.8C4.9 13.2 8.2 15 12 15s7.1-1.8 9.4-5.2"/>'
    '<path d="M4.3 13.3 2.8 15.9"/>'
    '<path d="M8.6 15 7.9 17.9"/>'
    '<path d="M15.4 15l.7 2.9"/>'
    '<path d="M19.7 13.3l1.5 2.6"/>'
)

ICON_TRASH = _ICON.format(
    '<path d="M4 7h16"/>'
    '<path d="M9.5 7V5.2A1.2 1.2 0 0 1 10.7 4h2.6a1.2 1.2 0 0 1 1.2 1.2V7"/>'
    '<path d="M6.4 7.9 7.2 19a1.6 1.6 0 0 0 1.6 1.5h6.4a1.6 1.6 0 0 0 1.6-1.5l.8-11.1"/>'
    '<path d="M10.4 11v6"/><path d="M13.6 11v6"/>'
)


def chip(label, value, tone="", vid=""):
    cls = f"chip {tone}".strip()
    vattr = f' id="{vid}"' if vid else ""
    return (f'<span class="{cls}"><span class="chip-k">{label}</span>'
            f'<span class="chip-v"{vattr}>{value}</span></span>')


def _price_on_or_before(dates, closes, target_date):
    result = None
    for d, c in zip(dates, closes):
        if d <= target_date:
            result = c
        else:
            break
    return result


def ttm_eps_at(eps_list, labels, i):
    if not eps_list or not labels or i < 0 or i >= len(eps_list) or i >= len(labels):
        return None
    if "Q" in labels[i]:
        if i >= 3 and all(e is not None for e in eps_list[i - 3:i + 1]):
            return sum(eps_list[i - 3:i + 1])
        return None
    return eps_list[i]


def _latest_ttm_per(stock, annual):
    if not annual:
        return None
    eps_list = annual.get("eps_jpy") or []
    labels = annual.get("fiscal_years") or []
    closes = stock.get("close") or []
    if not closes:
        return None
    ttm = ttm_eps_at(eps_list, labels, len(eps_list) - 1)
    if not ttm:
        return None
    price = closes[-1]
    return round(price / ttm, 2) if price is not None else None


def render_jp_stock_section(stock, fin, key, quarterly=None, annual=None):
    dates_json = json.dumps(stock["dates"], ensure_ascii=False)
    close_json = json.dumps(stock["close"], ensure_ascii=False)
    volume = stock.get("volume")
    has_volume = bool(volume) and any(v is not None for v in volume)
    volume_json = json.dumps([v if v is not None else None for v in volume]) if has_volume else "null"
    fetched_at = stock.get("fetched_at", "")
    name = stock.get("name", stock.get("code", ""))
    code = stock.get("code", "")
    dates, close = stock["dates"], stock["close"]

    last_val = close[-1]
    prev_val = close[-2] if len(close) > 1 else last_val
    diff = round(last_val - prev_val, 2)
    pct = round(diff / prev_val * 100, 2) if prev_val else 0.0
    last_date_disp = dates[-1].replace("-", "/")
    diff_txt, chg_color = fmt_diff(diff, 1, pct)

    buy_threshold = JP_STOCK_BUY_THRESHOLD.get(key)
    buy = (buy_threshold is not None) and (last_val < buy_threshold)

    if annual and not ("fiscal_years" in annual and "fiscal_year_end_dates" in annual):
        print(f"⚠️ {key} 的財經指標趨勢資料格式不正確（缺少 fiscal_years/fiscal_year_end_dates 欄位），本次跳過這張圖，不會讓整份報告失敗。")
        annual = None

    per_series, pbr_series = [], []
    if annual:
        fy_prices = [_price_on_or_before(dates, close, d) for d in annual["fiscal_year_end_dates"]]
        eps_list = annual.get("eps_jpy", [])
        labels = annual["fiscal_years"]
        is_quarterly = ["Q" in lbl for lbl in labels]

        for i, (price, eps) in enumerate(zip(fy_prices, eps_list)):
            if price is None:
                per_series.append(None)
                continue
            if is_quarterly[i]:
                if i >= 3 and all(e is not None for e in eps_list[i-3:i+1]):
                    ttm_eps = sum(eps_list[i-3:i+1])
                    per_series.append(round(price / ttm_eps, 2) if ttm_eps else None)
                else:
                    per_series.append(None)
            else:
                per_series.append(round(price / eps, 2) if eps else None)
        for price, bvps in zip(fy_prices, annual.get("bvps_jpy", [])):
            pbr_series.append(round(price / bvps, 2) if (price is not None and bvps) else None)

    fin_html = ""
    snap_per_for_chip = None
    snap_margin_for_chip = None
    per_buy_for_chip = False
    if not fin and not annual:
        fin_html = """
  <div class="sub-title">財務指標</div>
  <div class="fin-grid">
    <div class="fin-box pending"><div class="fin-label">本益比 PER (倍)</div><div class="fin-value">—</div></div>
    <div class="fin-box pending"><div class="fin-label">每股盈餘 EPS (日圓)</div><div class="fin-value">—</div></div>
    <div class="fin-box pending"><div class="fin-label">股價淨值比 PBR (倍)</div><div class="fin-value">—</div></div>
    <div class="fin-box pending"><div class="fin-label">營業利益率 (%)</div><div class="fin-value">—</div></div>
  </div>
  <div class="fin-pending-note">
    尚未建立季報資料，因此這四項無法計算。到控制台「追蹤個股」分頁，點這一檔的「建立季報」即可自動抓取。
  </div>
"""
    if fin or annual:
        fin = fin or {}
        if annual:
            latest_quarter_label = annual["fiscal_years"][-1]
            snap_eps = annual.get("eps_jpy", [None])[-1]
            snap_margin = annual.get("operating_margin_pct", [None])[-1]
            snap_per = _latest_ttm_per(stock, annual)
            snap_pbr = pbr_series[-1] if pbr_series else None
        else:
            latest_quarter_label = fin.get('fiscal_period', '')
            snap_eps = fin.get('eps_jpy')
            snap_margin = fin.get('operating_margin_pct')
            snap_per = fin.get('per_x')
            snap_pbr = fin.get('pbr_x')

        eps_disp = f"{snap_eps:.1f}" if snap_eps is not None else "N/A"
        margin_disp = f"{snap_margin:.1f}" if snap_margin is not None else "N/A（銀行不適用）"
        per_disp = f"{snap_per:.1f}" if snap_per is not None else "N/A"
        pbr_disp = f"{snap_pbr:.2f}" if snap_pbr is not None else "N/A"

        per_threshold = JP_STOCK_PER_THRESHOLD.get(key)
        per_buy = (snap_per is not None) and (per_threshold is not None) and (snap_per < per_threshold)
        per_badge = alert_badge(per_buy, 'PER 可布局', 'buy')
        per_sub = (f'<div class="fin-sub">布局參考：&lt; {per_threshold:g} 倍</div>'
                   if per_threshold is not None else "")
        snap_per_for_chip = snap_per
        snap_margin_for_chip = snap_margin
        per_buy_for_chip = per_buy

        src_urls = fin.get("source_urls") or (annual.get("source_urls") if annual else []) or []
        disclosure_date = fin.get("disclosure_date") or "未標註"
        src_links = source_links(src_urls) or "（未標註來源）"
        manual_note = "人工登錄" if fin else "API 自動"
        date_note = f"　｜　公布 {disclosure_date}" if fin.get("disclosure_date") else ""

        fin_html = f"""
  <div class="sub-title">財務指標（{latest_quarter_label}）</div>
  <div class="fin-grid">
    <div class="{'fin-box alert-buy' if per_buy else 'fin-box'}"><div class="fin-label">本益比 PER (倍){per_badge}</div><div class="fin-value">{per_disp}</div>{per_sub}</div>
    <div class="fin-box"><div class="fin-label">每股盈餘 EPS (日圓)</div><div class="fin-value">{eps_disp}</div></div>
    <div class="fin-box">
      <div class="fin-label-row"><span class="fin-label">股價淨值比 PBR (倍)</span><button class="fin-info-btn" onclick="toggleInfo('{key}PbrInfo')" title="股價淨值比說明">💡</button></div>
      <div class="fin-value">{pbr_disp}</div>
    </div>
    <div class="fin-box"><div class="fin-label">營業利益率 (%)</div><div class="fin-value">{margin_disp}</div></div>
  </div>
  <div id="{key}PbrInfo" class="info-popup">{PBR_EXPLAIN_TEXT}</div>
  <div class="chart-source-box" title="資料來源與更新時間" style="margin-bottom:12px;">
    📌 {src_links}　｜　{manual_note}{date_note}
  </div>
"""

    buy_sub = f'<div class="stat-sub">布局參考：&lt; {buy_threshold:,} 円</div>' if buy_threshold is not None else ""

    quarterly_html, quarterly_script = "", ""

    annual_html, annual_script = "", ""
    if annual:
        fy_labels_json = json.dumps(annual["fiscal_years"], ensure_ascii=False)
        margin_json = json.dumps(annual["operating_margin_pct"])
        margin_colors_json = json.dumps([
            "rgba(239,68,68,0.75)" if (m is not None and m < 0) else "rgba(16,185,129,0.55)"
            for m in annual["operating_margin_pct"]
        ])
        per_json = json.dumps(per_series)
        eps_json = json.dumps(annual.get("eps_jpy", []))
        pbr_json = json.dumps(pbr_series)

        a_links = source_links(annual.get("source_urls")) or annual.get("source", "未標註來源")
        latest_q = annual["fiscal_years"][-1] if annual.get("fiscal_years") else ""
        vintage = f"截至 {latest_q}" if latest_q else ""
        if fin.get("disclosure_date"):
            vintage += f"（{fin['disclosure_date']}）"

        annual_html = f"""
  <div class="title-row">
    <div class="sub-title" style="margin-bottom:0;">{name} 財經指標</div>
    <button class="info-btn" onclick="toggleInfo('{key}AMethod')" title="資料怎麼來的" aria-label="說明：資料怎麼來的">💡</button>
  </div>
  <div id="{key}AMethod" class="info-popup">{annual.get('methodology', '')}</div>
  <div class="chart-container short"><canvas id="{key}AChart"></canvas></div>
  <div class="chart-source-box" title="資料來源與更新時間" style="margin-bottom:12px;">
    📌 {a_links}　｜　{vintage}
  </div>
"""
        annual_script = f"""
  new Chart(document.getElementById('{key}AChart'), {{
    data: {{
      labels: {fy_labels_json},
      datasets: [
        {{ type:'bar', label:'營益率 (%)', data: {margin_json}, backgroundColor: {margin_colors_json}, yAxisID:'yPct', order:4 }},
        {{ type:'line', label:'本益比 PER (倍)', data: {per_json}, borderColor:'#3b82f6', backgroundColor:'#3b82f6', borderWidth:2, pointRadius:4, tension:0, spanGaps:false, yAxisID:'yMulti', order:1 }},
        {{ type:'line', label:'每股盈餘 EPS (円)', data: {eps_json}, borderColor:'#f59e0b', backgroundColor:'#f59e0b', borderWidth:2, pointRadius:4, tension:0, spanGaps:false, yAxisID:'yEps', order:2 }},
        {{ type:'line', label:'股價淨值比 PBR (倍)', data: {pbr_json}, borderColor:'#ec4899', backgroundColor:'#ec4899', borderWidth:2, pointRadius:4, tension:0, spanGaps:false, yAxisID:'yMulti', order:3 }}
      ]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      interaction: {{ mode:'index', intersect:false }},
      plugins: {{
        legend: {{ display:true, position:'top', labels:{{ color:'#94a3b8', boxWidth:12, font:{{size:10}} }} }},
        tooltip: {{ backgroundColor:'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1', borderColor:'#334155', borderWidth:1 }}
      }},
      scales: {{
        x: {{ ticks:{{ color:'#94a3b8' }}, grid:{{ display:false }} }},
        yPct: {{ position:'left', title:{{display:true,text:'營益率(%)',font:{{size:9}}}}, ticks:{{ color:'#94a3b8' }}, grid:{{ color:'rgba(38,51,77,0.35)' }} }},
        yMulti: {{ position:'right', title:{{display:true,text:'PER/PBR(倍)',font:{{size:9}}}}, ticks:{{ color:'#94a3b8' }}, grid:{{ drawOnChartArea:false }} }},
        yEps: {{ display:false }}
      }}
    }}
  }});
"""

    summary_chips = [
        f'<span class="chip price {"up" if diff >= 0 else "down"}">'
        f'<span class="chip-v">{last_val:,.1f}</span>'
        f'<span class="chip-k">{diff_txt}</span></span>'
    ]
    if snap_per_for_chip is not None:
        summary_chips.append(chip("PER", f"{snap_per_for_chip:.1f}", "buy" if per_buy_for_chip else ""))
    if snap_margin_for_chip is not None:
        summary_chips.append(chip("營益率", f"{snap_margin_for_chip:.1f}%"))
    if buy:
        summary_chips.append('<span class="chip buy solid">可布局</span>')
    if per_buy_for_chip:
        summary_chips.append('<span class="chip buy solid">PER 可布局</span>')

    body_html = f"""
  <div class="{stat_box_cls(buy, 'buy')}" style="margin-bottom:14px;">
    <div class="stat-label">最新收盤 ({last_date_disp}){alert_badge(buy, '可以考慮布局', 'buy')}</div>
    <div>
      <span class="stat-value" style="color:{chg_color};">{last_val:,.1f}</span>
      <span class="stat-chg" style="color:{chg_color};">{diff_txt}</span>
    </div>
    {buy_sub}
  </div>
  {fin_html}
  <div class="tf-bar" id="tf-{key}">
    <span style="font-size:11px;color:#64748b;margin-right:2px;">週期切換:</span>
    <button class="tf-btn" onclick="simpleSetRange('{key}','5D',this)">5D</button>
    <button class="tf-btn" onclick="simpleSetRange('{key}','1M',this)">1M</button>
    <button class="tf-btn" onclick="simpleSetRange('{key}','3M',this)">3M</button>
    <button class="tf-btn" onclick="simpleSetRange('{key}','6M',this)">6M</button>
    <button class="tf-btn" onclick="simpleSetRange('{key}','YTD',this)">YTD</button>
    <button class="tf-btn" onclick="simpleSetRange('{key}','1Y',this)">1Y</button>
    <button class="tf-btn" onclick="simpleSetRange('{key}','3Y',this)">3Y</button>
    <button class="tf-btn active" onclick="simpleSetRange('{key}','5Y',this)">5Y</button>
  </div>
  <div class="custom-legend" id="{key}Legend"></div>
  <div class="chart-container"><canvas id="{key}Chart"></canvas></div>
  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="https://finance.yahoo.com/quote/{code}/" target="_blank">Yahoo Finance</a>　｜　{fetched_at}
  </div>
  {quarterly_html}
  {annual_html}
"""

    actions_html = (
        f'<button type="button" class="card-act" data-code="{key}"'
        f' data-name="{name}" data-ticker="{code}"'
        f' onclick="return mmCardAct(this,\'隱藏個股\')"'
        f' aria-label="隱藏 {name}"'
        f' title="隱藏 {name}——之後可以在下面那一列還原">{ICON_EYE_OFF}</button>'
        f'<button type="button" class="card-act danger" data-code="{key}"'
        f' data-name="{name}" data-ticker="{code}"'
        f' onclick="return mmCardAct(this,\'移除個股\')"'
        f' aria-label="從名單移除 {name}"'
        f' title="從名單移除 {name}">{ICON_TRASH}</button>'
    )
    section_html = collapsible(
        key, f"{name} ({code})", "".join(summary_chips), body_html,
        alert=bool(buy or per_buy_for_chip),
        actions_html=actions_html,
    )

    buy_dataset_js = ""
    if buy_threshold is not None:
        buy_dataset_js = f"""
        {{
          label: '{buy_threshold:,} 布局參考線', data: {key}Dates.map(() => {buy_threshold}),
          borderColor: '#22d3ee', borderDash: [6,4], borderWidth: 1.4, pointRadius: 0, fill:false, yAxisID:'y', order: 2
        }},"""

    volume_dataset_js = ""
    if has_volume:
        volume_dataset_js = f"""
        {{
          label: '成交量', data: {key}Volume, type: 'bar',
          backgroundColor: 'rgba(148,163,184,0.4)', borderRadius: 1,
          barPercentage: 0.85, categoryPercentage: 0.8, yAxisID: 'yVol', order: 3
        }},"""

    script = f"""
  const {key}Dates = {dates_json};
  const {key}Close = {close_json};
  const {key}Volume = {volume_json};
  const {key}Chart = new Chart(document.getElementById('{key}Chart'), {{
    type: 'line',
    data: {{
      labels: {key}Dates.map(fmtLabel),
      datasets: [
        {{
          label: '{name}', data: {key}Close, borderColor: 'rgb(236,72,153)',
          backgroundColor: (c) => gradientFill(c, '236,72,153'),
          fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4, borderWidth: 1.6, yAxisID:'y', order: 1
        }},{buy_dataset_js}{volume_dataset_js}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: 'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1',
          borderColor: '#334155', borderWidth: 1, padding: 10, boxPadding: 4,
          filter: (item) => !item.dataset.borderDash,
          callbacks: {{
            title: tooltipFullDateTitle('{key}'),
            label: (item) => item.dataset.label === '成交量'
              ? '成交量：' + item.formattedValue + ' 股' : '股價：' + item.formattedValue + ' 円'
          }}
        }}
      }},
      scales: {{
        x: {{ type: 'category', ticks: {{ maxTicksLimit: 8, maxRotation: 0, color: '#94a3b8' }}, grid: {{ color: 'rgba(38,51,77,0.35)' }} }},
        y: {{ position: 'left', title: {{ display:true, text:'股價 (円)', font:{{size:9.5}} }}, grid: {{ color:'rgba(38,51,77,0.35)' }} }},
        yVol: {{ position: 'right', title: {{ display:true, text:'成交量 (股)', font:{{size:9.5}} }}, grid: {{ drawOnChartArea:false }} }}
      }}
    }}
  }});
  buildLegend({key}Chart, '{key}Legend');
  chartRegistry['{key}'] = {{
    chart: {key}Chart, dates: {key}Dates, close: {key}Close, volume: {key}Volume, currentDates: {key}Dates.slice(),
    warnLevels: {'[' + str(buy_threshold) + ']' if buy_threshold is not None else 'null'},
    hasVolumeDataset: {str(has_volume).lower()}
  }};
{quarterly_script}
{annual_script}
"""
    return section_html, script


def tip_button(tip_id, key):
    entry = TIPS.get(key)
    if not entry:
        return "", ""
    label, body = entry
    btn = (f'<button class="info-btn" onclick="toggleInfo(\'{tip_id}\')" '
           f'title="{html_escape(label)}" aria-label="說明：{html_escape(label)}">💡</button>')
    popup = f'<div id="{tip_id}" class="info-popup">{html_escape(body)}</div>'
    return btn, popup


def html_escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def titled_row(title, tip_id=None, tip_key=None, level="section-title"):
    btn, popup = tip_button(tip_id, tip_key) if tip_id and tip_key else ("", "")
    return f"""
  <div class="title-row">
    <div class="{level}" style="margin-bottom:0;">{title}</div>
    {btn}
  </div>
  {popup}
"""


def vintage_note(iso_month, months_behind=None, freq="", normal_lag=None):
    if not iso_month:
        return ""
    disp = iso_month[:7].replace("-", "/")
    if months_behind is None:
        months_behind = _months_behind_iso(iso_month)
    suffix = f"｜{freq}頻" if freq else ""
    if months_behind is not None and months_behind >= 3:
        return (f'<span class="vintage stale">資料月份 {disp}'
                f'（落後 {months_behind} 個月）{suffix}</span>')
    if (normal_lag is not None and months_behind is not None
            and months_behind <= normal_lag):
        return (f'<span class="vintage">資料月份 {disp}{suffix}'
                f'｜來源每月更新，這是目前最新的一筆</span>')
    return f'<span class="vintage">資料月份 {disp}{suffix}</span>'


def _months_behind_iso(iso_date):
    try:
        y, m = int(iso_date[:4]), int(iso_date[5:7])
    except (ValueError, TypeError):
        return None
    today = date.today()
    return (today.year - y) * 12 + (today.month - m)


def fmt_period(iso_date, freq=""):
    if not iso_date:
        return "—"
    if freq == "季":
        try:
            y, m = int(iso_date[:4]), int(iso_date[5:7])
            return f"{y}Q{(m - 1) // 3 + 1}"
        except ValueError:
            return iso_date
    if freq == "週" or freq == "日":
        return iso_date.replace("-", "/")
    return iso_date[:7].replace("-", "/")


def fmt_indicator_value(value, unit=""):
    if value is None:
        return "—"
    if "%" in unit:
        return f"{value:,.1f}%"
    if abs(value) >= 10000:
        return f"{value:,.0f}"
    if abs(value) >= 100:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def render_tw_pmi_section(pmi):
    dates = pmi["dates"]
    pmi_vals, nmi_vals = pmi["pmi"], pmi["nmi"]
    last_pmi = next((v for v in reversed(pmi_vals) if v is not None), None)
    last_nmi = next((v for v in reversed(nmi_vals) if v is not None), None)
    prev_pmi = next((v for v in reversed(pmi_vals[:-1]) if v is not None), last_pmi)
    if last_pmi is None:
        return "", ""

    diff = round(last_pmi - prev_pmi, 1)
    pmi_pct = round(diff / prev_pmi * 100, 2) if prev_pmi else None
    diff_txt, chg_color = fmt_diff(diff, 1, pmi_pct)

    nmi_prev = None
    if last_nmi is not None:
        seen_last = False
        for v in reversed(nmi_vals):
            if v is None:
                continue
            if not seen_last:
                seen_last = True
                continue
            nmi_prev = v
            break
    if last_nmi is not None and nmi_prev:
        nmi_diff = round(last_nmi - nmi_prev, 1)
        nmi_diff_txt, nmi_chg_color = fmt_diff(
            nmi_diff, 1, round(nmi_diff / nmi_prev * 100, 2))
    else:
        nmi_diff_txt, nmi_chg_color = "", "#94a3b8"

    neutral = PMI_NEUTRAL
    expanding = last_pmi >= neutral
    zone_label = "擴張" if expanding else "收縮"
    zone_color = "#22d3ee" if expanding else "#ef4444"

    html = titled_row("臺灣製造業 PMI ／ 非製造業 NMI", "twPmiInfo", "tw_pmi", level="sub-title") + f"""
  <div class="stat-grid">
    <div class="stat-box">
      <div class="stat-label">製造業 PMI
        <span class="zone-badge" style="background:rgba(0,0,0,0.25);color:{zone_color};border:1px solid {zone_color};">{zone_label}</span>
      </div>
      <div>
        <span class="stat-value" style="color:{chg_color};">{last_pmi:,.1f}</span>
        <span class="stat-chg" style="color:{chg_color};">{diff_txt}</span>
      </div>
      <div class="stat-sub">{vintage_note(dates[-1], freq="月")}｜{neutral} 為榮枯線</div>
    </div>
    <div class="stat-box">
      <div class="stat-label">非製造業 NMI
        <span class="zone-badge" style="background:rgba(0,0,0,0.25);color:{'#22d3ee' if (last_nmi or 0) >= neutral else '#ef4444'};border:1px solid {'#22d3ee' if (last_nmi or 0) >= neutral else '#ef4444'};">{'擴張' if (last_nmi or 0) >= neutral else '收縮'}</span>
      </div>
      <div>
        <span class="stat-value" style="color:{nmi_chg_color};">{fmt_indicator_value(last_nmi)}</span>
        <span class="stat-chg" style="color:{nmi_chg_color};">{nmi_diff_txt}</span>
      </div>
      <div class="stat-sub">服務業與內需的對照組</div>
    </div>
  </div>

{fold_open("PMI／NMI 走勢圖")}
  <div class="tf-bar" id="tf-twpmi">
    <span style="font-size:11px;color:#64748b;margin-right:2px;">週期切換:</span>
    <button class="tf-btn" onclick="simpleSetRange('twpmi','1Y',this)">1Y</button>
    <button class="tf-btn" onclick="simpleSetRange('twpmi','3Y',this)">3Y</button>
    <button class="tf-btn active" onclick="simpleSetRange('twpmi','5Y',this)">5Y</button>
    <button class="tf-btn" onclick="simpleSetRange('twpmi','10Y',this)">10Y</button>
    <button class="tf-btn" onclick="simpleSetRange('twpmi','ALL',this)">全部</button>
  </div>
  <div class="custom-legend" id="twPmiLegend"></div>
  <div class="chart-container short"><canvas id="twPmiChart"></canvas></div>
{FOLD_CLOSE}
  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="https://data.gov.tw/dataset/6100" target="_blank">國發會／中華經濟研究院（政府資料開放平臺）</a>　｜　每月發布
  </div>
"""

    script = f"""
  const twPmiDates = {json.dumps(dates, ensure_ascii=False)};
  const twPmiVals = {json.dumps(pmi_vals, ensure_ascii=False)};
  const twNmiVals = {json.dumps(nmi_vals, ensure_ascii=False)};
  // 點半徑跟著目前顯示幾個點走。視窗放寬到 170 個月之後，固定 2px 在
  // 「全部」那一檔會把兩條線壓成兩條由圓點組成的帶子。
  const PMI_PT = (ctx) => (ctx.chart.data.labels.length > 90 ? 0
                           : (ctx.chart.data.labels.length > 36 ? 1.5 : 2));
  const twPmiChart = new Chart(document.getElementById('twPmiChart'), {{
    type: 'line',
    data: {{
      labels: twPmiDates.map(fmtLabel),
      datasets: [
        {{ label: '製造業 PMI', data: twPmiVals, borderColor: 'rgb(34,211,238)',
           backgroundColor: (c) => gradientFill(c, '34,211,238'),
           fill: true, tension: 0, pointRadius: PMI_PT, pointHoverRadius: 5, borderWidth: 2, order: 1, spanGaps: true }},
        {{ label: '非製造業 NMI', data: twNmiVals, borderColor: 'rgb(168,85,247)',
           fill: false, tension: 0, pointRadius: PMI_PT, pointHoverRadius: 5, borderWidth: 2, order: 2, spanGaps: true }},
        {{ label: '{PMI_NEUTRAL} 榮枯線', data: twPmiDates.map(() => {PMI_NEUTRAL}), borderColor: '#f59e0b',
           borderDash: [5,4], borderWidth: 1.2, pointRadius: 0, fill: false, order: 3 }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: 'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1',
          borderColor: '#334155', borderWidth: 1, padding: 10, boxPadding: 4,
          filter: (item) => !item.dataset.borderDash,
          callbacks: {{
            title: tooltipFullDateTitle('twpmi'),
            afterLabel: (item) => (item.parsed.y >= {PMI_NEUTRAL} ? '擴張（>{PMI_NEUTRAL}）' : '收縮（<{PMI_NEUTRAL}）')
          }}
        }}
      }},
      scales: {{
        x: {{ type: 'category', ticks: {{ maxTicksLimit: 8, maxRotation: 0, color: '#94a3b8' }}, grid: {{ color: 'rgba(38,51,77,0.35)' }} }},
        y: {{ suggestedMin: 30, suggestedMax: 70, grid: {{ color: 'rgba(38,51,77,0.35)' }} }}
      }}
    }}
  }});
  buildLegend(twPmiChart, 'twPmiLegend');
  chartRegistry['twpmi'] = {{ chart: twPmiChart, dates: twPmiDates, close: twPmiVals, currentDates: twPmiDates.slice(), warnLevels: [{PMI_NEUTRAL}] }};
"""
    return html, script


def render_tw_marketcap_m1b_section(ratio_data):
    dates = ratio_data["dates"]
    ratios = ratio_data["ratio"]
    if not dates:
        return "", ""

    last = ratios[-1]
    prev = ratios[-2] if len(ratios) > 1 else last
    diff = round(last - prev, 2)
    mc_pct = round(diff / prev * 100, 2) if prev else None
    diff_txt, chg_color = fmt_diff(diff, 2, mc_pct)
    behind = ratio_data.get("months_behind")

    percentile = None
    window = ratios[-TW_MC_M1B_PCT_WINDOW:]
    if len(window) >= 24:
        percentile = round(sum(1 for r in window if r < last) / len(window) * 100)
        tight = percentile >= TW_MC_M1B_PCT_HIGH
        loose = percentile <= TW_MC_M1B_PCT_LOW
    else:
        tight = last >= TW_MC_M1B_HIGH
        loose = last <= TW_MC_M1B_LOW
    if tight:
        zone_label, zone_color = "資金相對吃緊", "#ef4444"
    elif loose:
        zone_label, zone_color = "資金相對寬鬆", "#22d3ee"
    else:
        zone_label, zone_color = "區間中段", "#94a3b8"

    if percentile is not None:
        ordered = sorted(window)

        def at(p: int) -> float:
            i = (len(ordered) - 1) * p / 100
            lo, hi = int(i), min(int(i) + 1, len(ordered) - 1)
            return ordered[lo] + (ordered[hi] - ordered[lo]) * (i - lo)

        low = round(at(TW_MC_M1B_PCT_LOW), 2)
        high = round(at(TW_MC_M1B_PCT_HIGH), 2)
        zone_basis = (f"分區依近 {len(window)} 個月的百分位："
                      f"≤P{TW_MC_M1B_PCT_LOW}（約 {low:.2f}）寬鬆、"
                      f"≥P{TW_MC_M1B_PCT_HIGH}（約 {high:.2f}）吃緊")
    else:
        low, high = TW_MC_M1B_LOW, TW_MC_M1B_HIGH
        zone_basis = f"參考區間（歷史不足，暫用固定值）：&lt;{low} 寬鬆、&gt;{high} 吃緊"

    cap_t = ratio_data["market_cap"][-1] / 1e6
    m1b_t = ratio_data["m1b"][-1] / 1e6

    span_txt = ""
    if percentile is not None:
        years = len(ratios) / 12
        span_txt = (f"｜歷史位置：{years:.0f} 年區間 {min(ratios):.2f}～{max(ratios):.2f} 的"
                    f"<b style=\"color:{zone_color};\">第 {percentile} 百分位</b>")

    html = titled_row("市值貨幣比（上市櫃總市值 ÷ M1B）", "twMcM1bInfo", "tw_marketcap_m1b",
                      level="sub-title") + f"""
  <div class="stat-box" style="margin-bottom:14px;">
    <div class="stat-label">最新比值
      <span class="zone-badge" style="background:rgba(0,0,0,0.25);color:{zone_color};border:1px solid {zone_color};">{zone_label}</span>
    </div>
    <div>
      <span class="stat-value" style="color:{chg_color};">{last:,.2f}</span>
      <span class="stat-chg" style="color:{chg_color};">{diff_txt} 較上月</span>
    </div>
    <div class="stat-sub">
      {vintage_note(dates[-1], behind, freq="月", normal_lag=TW_MC_M1B_NORMAL_LAG)}
      ｜總市值 {cap_t:,.1f} 兆元 ÷ M1B {m1b_t:,.1f} 兆元
      ｜{zone_basis}
      {span_txt}
    </div>
  </div>

{fold_open("市值貨幣比走勢圖")}
  <div class="tf-bar" id="tf-twmcm1b">
    <span style="font-size:11px;color:#64748b;margin-right:2px;">週期切換:</span>
    <button class="tf-btn" onclick="simpleSetRange('twmcm1b','1Y',this)">1Y</button>
    <button class="tf-btn" onclick="simpleSetRange('twmcm1b','3Y',this)">3Y</button>
    <button class="tf-btn" onclick="simpleSetRange('twmcm1b','5Y',this)">5Y</button>
    <button class="tf-btn active" onclick="simpleSetRange('twmcm1b','ALL',this)">全部</button>
  </div>
  <div class="custom-legend" id="twMcM1bLegend"></div>
  <div class="chart-container short"><canvas id="twMcM1bChart"></canvas></div>
{FOLD_CLOSE}
  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="https://www.cbc.gov.tw/tw/lp-1114-1.html" target="_blank">中央銀行 上市股票統計</a>
    ｜<a href="https://www.tpex.org.tw/zh-tw/statistics" target="_blank">櫃買中心 歷年上櫃股票統計</a>
    ｜<a href="https://data.gov.tw/dataset/6024" target="_blank">中央銀行 貨幣總計數</a>
    ｜對帳：<a href="https://data.gov.tw/dataset/11138" target="_blank">金管會證期局 市場綜覽t49</a>
    ｜自行計算，非官方公布之比值
  </div>
"""

    script = f"""
  const mcDates = {json.dumps(dates, ensure_ascii=False)};
  const mcRatio = {json.dumps(ratios, ensure_ascii=False)};
  const mcCap = {json.dumps([round(v / 1e6, 2) for v in ratio_data["market_cap"]], ensure_ascii=False)};
  const mcM1b = {json.dumps([round(v / 1e6, 2) for v in ratio_data["m1b"]], ensure_ascii=False)};
  const twMcM1bChart = new Chart(document.getElementById('twMcM1bChart'), {{
    type: 'line',
    data: {{
      labels: mcDates.map(fmtLabel),
      datasets: [
        // 點的大小跟資料量走。原本固定 3px 是為了 5 個點的那張圖；接上長歷史
        // 之後有 126 個月，固定 3px 會把線壓成一條由圓點組成的粗帶子。
        {{ label: '市值貨幣比', data: mcRatio, borderColor: 'rgb(250,204,21)',
           backgroundColor: (c) => gradientFill(c, '250,204,21'),
           fill: true, tension: 0,
           // 跟著**目前畫出來的**點數走：切到 1Y 只剩 12 個點，要看得到點。
           pointRadius: (c) => {{ const n = c.chart.data.labels.length; return n > 90 ? 0 : (n > 36 ? 1.5 : 3); }},
           pointHoverRadius: 6, borderWidth: 2, order: 1 }},
        {{ label: '{high} 資金吃緊', data: mcDates.map(() => {high}), borderColor: '#ef4444',
           borderDash: [5,4], borderWidth: 1.1, pointRadius: 0, fill: false, order: 2 }},
        {{ label: '{low} 資金寬鬆', data: mcDates.map(() => {low}), borderColor: '#22d3ee',
           borderDash: [5,4], borderWidth: 1.1, pointRadius: 0, fill: false, order: 3 }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: 'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1',
          borderColor: '#334155', borderWidth: 1, padding: 10, boxPadding: 4,
          filter: (item) => !item.dataset.borderDash,
          callbacks: {{
            title: tooltipFullDateTitle('twmcm1b'),
            afterLabel: (item) => {{
              // 切了週期之後 dataIndex 是從區間起點數的，要加回位移才對得到原始陣列。
              const cur = chartRegistry['twmcm1b'] ? chartRegistry['twmcm1b'].currentDates : mcDates;
              const i = item.dataIndex + mcDates.length - cur.length;
              return ['總市值 ' + mcCap[i] + ' 兆元', 'M1B ' + mcM1b[i] + ' 兆元'];
            }}
          }}
        }}
      }},
      scales: {{
        x: {{ type: 'category', ticks: {{ maxTicksLimit: 8, maxRotation: 0, color: '#94a3b8' }}, grid: {{ color: 'rgba(38,51,77,0.35)' }} }},
        y: {{ grid: {{ color: 'rgba(38,51,77,0.35)' }} }}
      }}
    }}
  }});
  buildLegend(twMcM1bChart, 'twMcM1bLegend');
  chartRegistry['twmcm1b'] = {{ chart: twMcM1bChart, dates: mcDates, close: mcRatio, currentDates: mcDates.slice(), warnLevels: [{high},{low}] }};
"""
    return html, script


def render_us_indices_section(indices):
    usable = [(k, d) for k, d in indices if d and d.get("dates")]
    if not usable:
        return "", ""

    common = set(usable[0][1]["dates"])
    for _, d in usable[1:]:
        common &= set(d["dates"])
    common_dates = sorted(common)
    if len(common_dates) < 2:
        return "", ""

    colors = ["59,130,246", "34,197,94", "168,85,247"]
    series_js, legend_bits, chips = [], [], []
    for i, (key, d) in enumerate(usable):
        by_date = dict(zip(d["dates"], d["close"]))
        raw = [by_date[dt] for dt in common_dates]
        base = raw[0]
        rebased = [round(v / base * 100, 2) for v in raw] if base else raw
        color = colors[i % len(colors)]
        series_js.append(f"""
        {{ label: {json.dumps(d.get("name") or key, ensure_ascii=False)}, data: {json.dumps(rebased)},
           borderColor: 'rgb({color})', fill: false, tension: 0,
           pointRadius: 0, pointHoverRadius: 4, borderWidth: 2, order: {i + 1} }},""")
        legend_bits.append(f"rawSeries[{i}] = {json.dumps(raw)};")

        own = d["close"]
        last, prev = own[-1], (own[-2] if len(own) > 1 else own[-1])
        diff = round(last - prev, 2)
        pct = round(diff / prev * 100, 2) if prev else 0.0
        diff_txt, _ = fmt_diff(diff, 2, pct)
        tone = "up" if diff > 0 else ("down" if diff < 0 else "")
        chips.append(
            f'<span class="{("chip price idx " + tone).strip()}">'
            f'<span class="chip-n">{d.get("name") or key}</span>'
            f'<span class="chip-v">{last:,.0f}</span><span class="chip-k">{diff_txt}</span></span>')

    period_txt = f"{common_dates[0].replace('-', '/')} 起"
    html = f"""
  <div class="stat-box" style="margin-bottom:12px;">
    <div class="stat-label">相對走勢（<span id="usIdxBase">{period_txt}</span> = 100）</div>
    <div class="stat-sub">三個指數的點數量級差很多，直接疊圖看不出相對強弱，
      所以統一重訂基期。滑過圖表可同時看到重訂基期後的值與真實收盤點數。</div>
  </div>
{fold_open("三大指數相對走勢圖")}
  <div class="tf-bar" id="tf-usidx">
    <span style="font-size:11px;color:#64748b;margin-right:2px;">週期切換:</span>
    <button class="tf-btn" onclick="usIdxSetRange('5D',this)">5D</button>
    <button class="tf-btn" onclick="usIdxSetRange('1M',this)">1M</button>
    <button class="tf-btn" onclick="usIdxSetRange('3M',this)">3M</button>
    <button class="tf-btn" onclick="usIdxSetRange('6M',this)">6M</button>
    <button class="tf-btn" onclick="usIdxSetRange('YTD',this)">YTD</button>
    <button class="tf-btn" onclick="usIdxSetRange('1Y',this)">1Y</button>
    <button class="tf-btn" onclick="usIdxSetRange('3Y',this)">3Y</button>
    <button class="tf-btn active" onclick="usIdxSetRange('ALL',this)">全部</button>
  </div>
  <div class="custom-legend" id="usIdxLegend"></div>
  <div class="chart-container"><canvas id="usIdxChart"></canvas></div>
{FOLD_CLOSE}
  <div class="chart-source-box" title="資料來源與更新時間">
    📌 Yahoo Finance Chart API　｜　^DJI、^GSPC、^IXIC　｜　每日收盤
  </div>
"""

    script = f"""
  const usIdxDates = {json.dumps(common_dates, ensure_ascii=False)};
  const rawSeries = [];
  {' '.join(legend_bits)}
  let usIdxOff = 0;          // 目前畫的是從第幾天開始（tooltip 要拿它對回真實點數）
  const usIdxChart = new Chart(document.getElementById('usIdxChart'), {{
    type: 'line',
    data: {{ labels: usIdxDates.map(fmtLabel), datasets: [{''.join(series_js)}] }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: 'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1',
          borderColor: '#334155', borderWidth: 1, padding: 10, boxPadding: 4,
          callbacks: {{
            title: tooltipFullDateTitle('usidx'),
            label: (item) => {{
              const raw = rawSeries[item.datasetIndex];
              const actual = raw ? raw[item.dataIndex + usIdxOff] : null;
              const base = item.dataset.label + ': ' + item.parsed.y.toFixed(2);
              return actual === null ? base
                : base + '（實際 ' + actual.toLocaleString(undefined, {{maximumFractionDigits: 2}}) + '）';
            }}
          }}
        }}
      }},
      scales: {{
        x: {{ type: 'category', ticks: {{ maxTicksLimit: 8, maxRotation: 0, color: '#94a3b8' }}, grid: {{ color: 'rgba(38,51,77,0.35)' }} }},
        y: {{ grid: {{ color: 'rgba(38,51,77,0.35)' }}, title: {{ display: true, text: '重訂基期（起點=100）', color: '#64748b' }} }}
      }}
    }}
  }});
  buildLegend(usIdxChart, 'usIdxLegend');
  chartRegistry['usidx'] = {{ chart: usIdxChart, dates: usIdxDates, close: [], currentDates: usIdxDates.slice(), warnLevels: [] }};
  /* 週期切換：重訂基期跟著區間走——切到 1M 就是「一個月前＝100」，比的是這一段的
     相對強弱。只裁切不重訂的話，起點不在 100，三條線的高低就看不出誰漲得多。 */
  function usIdxSetRange(tf, btn) {{
    document.querySelectorAll('#tf-usidx .tf-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const idx = tf === '5D' ? Math.max(0, usIdxDates.length - 5) : filterByRange(usIdxDates, tf);
    const dates = usIdxDates.slice(idx);
    usIdxOff = idx;
    const short = (tf === '5D' || tf === '1M' || tf === '3M');
    usIdxChart.data.labels = dates.map(short ? fmtLabelShort : fmtLabel);
    rawSeries.forEach((raw, i) => {{
      const seg = raw.slice(idx), base = seg[0];
      usIdxChart.data.datasets[i].data = seg.map(v => base ? Math.round(v / base * 10000) / 100 : v);
    }});
    chartRegistry['usidx'].currentDates = dates;
    const lab = document.getElementById('usIdxBase');
    if (lab) lab.textContent = dates[0].replace(/-/g, '/') + ' 起';
    usIdxChart.update();
  }}
"""
    return html, script, chips


US_GROUP_COLOURS = {
    "growth": ("34,211,238", "#22d3ee"),
    "labor": ("59,130,246", "#3b82f6"),
    "inflation": ("244,63,94", "#f43f5e"),
    "housing_sentiment": ("168,85,247", "#a855f7"),
}


def render_us_indicator_group(group, series_with_data):
    if not series_with_data:
        return "", ""

    charts_by_id, charts_js = _us_indicator_charts(group, series_with_data)
    rgb, hex_colour = US_GROUP_COLOURS.get(group["key"], ("148,163,184", "#94a3b8"))
    boxes = []
    for meta, data in series_with_data:
        values, dates = data["close"], data["dates"]
        last = values[-1]
        prev = values[-2] if len(values) > 1 else last
        diff = last - prev
        pct = (diff / prev * 100) if prev else None
        if abs(last) >= 10000:
            decimals = 0
        elif abs(last) >= 100:
            decimals = 1
        else:
            decimals = 2
        diff_txt, chg_color = fmt_diff(diff, decimals, pct)
        unit = meta.get("unit", "")
        boxes.append(f"""
    <div class="fin-box">
      <div class="fin-label">{meta['name']}</div>
      <div class="fin-value" style="color:{chg_color};">{fmt_indicator_value(last, unit)}</div>
      <div class="fin-sub" style="color:{chg_color};">{diff_txt}</div>
      <div class="fin-sub" style="font-size:10px;opacity:.75;">{fmt_period(dates[-1], meta.get('freq', ''))}{' 初值' if michigan_is_prelim(data) else ''}
        {('｜' + unit) if unit else ''}</div>
    </div>
    {charts_by_id.get((meta.get("id") or "").strip(), "")}""")

    tip_id = f"us{group['key'].title().replace('_', '')}Info"
    btn, popup = tip_button(tip_id, f"us_{group['key']}")
    html = f"""
  <div class="us-group">
  <div class="title-row">
    <div class="sub-title" style="margin:0;font-size:15px;color:{hex_colour};">{group['label']}</div>
    {btn}
  </div>
  {popup}
  <div class="ind-grid">{''.join(ind_block(b, hex_colour) for b in boxes)}</div>
  </div>
"""
    return html, charts_js


def _us_indicator_charts(group, series_with_data):
    rgb, hex_colour = US_GROUP_COLOURS.get(group["key"], ("148,163,184", "#94a3b8"))
    blocks, scripts = {}, []
    for meta, data in series_with_data:
        series_id = (meta.get("id") or "").strip()
        if not series_id or not data.get("dates"):
            continue
        if not meta.get("in_group", True):
            continue
        key = f"usfr{series_id}"
        blocks[series_id] = (f"""
      <div class="ind-chart">
        <div class="tf-bar" id="tf-{key}">
          <span style="font-size:11px;color:#64748b;margin-right:2px;">週期切換:</span>
          <button class="tf-btn" onclick="simpleSetRange('{key}','1Y',this)">1Y</button>
          <button class="tf-btn" onclick="simpleSetRange('{key}','3Y',this)">3Y</button>
          <button class="tf-btn active" onclick="simpleSetRange('{key}','5Y',this)">5Y</button>
          <button class="tf-btn" onclick="simpleSetRange('{key}','10Y',this)">10Y</button>
          <button class="tf-btn" onclick="simpleSetRange('{key}','ALL',this)">全部</button>
        </div>
        <div class="chart-container short"><canvas id="{key}Chart"></canvas></div>
        <div class="chart-source-box" title="資料來源與更新時間">
          📌 <a href="https://fred.stlouisfed.org/series/{series_id}" target="_blank">FRED {series_id}</a>
          　｜　資料截至 {fmt_period(data['dates'][-1], meta.get('freq', ''))}
        </div>
      </div>""")
        scripts.append(f"""
  {{
    const d = {json.dumps(data['dates'], ensure_ascii=False)};
    const c = {json.dumps(data['close'], ensure_ascii=False)};
    const ch = new Chart(document.getElementById('{key}Chart'), {{
      type: 'line',
      data: {{ labels: d.map(fmtLabel), datasets: [{{
        label: {json.dumps(meta['name'], ensure_ascii=False)}, data: c,
        borderColor: '{hex_colour}',
        backgroundColor: (x) => gradientFill(x, '{rgb}'),
        fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4, borderWidth: 1.6
      }}] }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{
            backgroundColor: 'rgba(15,23,42,0.95)', titleColor:'#f8fafc', bodyColor:'#cbd5e1',
            borderColor: '#334155', borderWidth: 1, padding: 10, boxPadding: 4,
            callbacks: {{ title: tooltipFullDateTitle('{key}') }}
          }}
        }},
        scales: {{
          x: {{ type: 'category', ticks: {{ maxTicksLimit: 8, maxRotation: 0, color: '#94a3b8' }},
               grid: {{ color: 'rgba(38,51,77,0.35)' }} }},
          y: {{ position: 'left', grid: {{ color: 'rgba(38,51,77,0.35)' }} }}
        }}
      }}
    }});
    chartRegistry['{key}'] = {{ chart: ch, dates: d, close: c, currentDates: d.slice(), warnLevels: [] }};
    simpleSetRange('{key}', '5Y', document.querySelector('#tf-{key} .tf-btn.active'));
  }}""")
    return blocks, "".join(scripts)


def render_us_overview_table():
    btn, popup = tip_button("usOverviewInfo", "us_overview")
    rows = []
    tone = {"領先": "#22d3ee", "同步": "#94a3b8", "落後": "#f59e0b"}
    for name, freq, what, lead in OVERVIEW_TABLE:
        rows.append(f"""
      <tr>
        <td class="ov-name">{name}</td>
        <td class="ov-freq">{freq}</td>
        <td>{what}</td>
        <td><span class="ov-lead" style="color:{tone.get(lead, '#94a3b8')};border-color:{tone.get(lead, '#94a3b8')};">{lead}</span></td>
      </tr>""")
    return f"""
  <details class="fold">
    <summary>核心指標速覽表（{len(OVERVIEW_TABLE)} 項）</summary>
    <div class="fold-body">
      <div class="title-row" style="margin:0 0 10px 0;">{btn}</div>
      {popup}
      <div class="ov-wrap">
        <table class="ov-table">
          <thead><tr><th>指標</th><th>頻率</th><th>這格在看什麼</th><th>時序</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </div>
  </details>
"""


def collect_alerts(taiex, vix, nikkei, michigan, murata, jp_stocks,
                   tw_pmi=None, tw_mc_m1b=None):
    alerts = []
    if taiex:
        last_close = taiex["close"][-1]
        value_bil = [round(v / 1e8, 2) for v in taiex["value_twd"]]
        avg10 = sum(value_bil[-10:]) / len(value_bil[-10:]) if value_bil else 0
        if last_close < TAIEX_BUY_THRESHOLD:
            alerts.append(("buy", f"台股加權指數 {last_close:,.0f} 點，低於 {TAIEX_BUY_THRESHOLD:,} 布局參考線"))
        if avg10 < VOLUME_BUY_THRESHOLD_BIL:
            alerts.append(("buy", f"台股10日均量 {avg10:,.0f} 億，低於 {VOLUME_BUY_THRESHOLD_BIL:,} 億布局參考"))
    if tw_pmi and tw_pmi.get("pmi"):
        last_pmi = next((v for v in reversed(tw_pmi["pmi"]) if v is not None), None)
        last_month = tw_pmi["dates"][-1][:7].replace("-", "/") if tw_pmi.get("dates") else ""
        if last_pmi is not None and last_pmi < PMI_NEUTRAL:
            alerts.append(("warn", f"臺灣製造業 PMI {last_pmi:.1f}（{last_month}），"
                                   f"低於 {PMI_NEUTRAL} 榮枯線，製造業處於收縮"))
    if tw_mc_m1b and tw_mc_m1b.get("ratio"):
        last_ratio = tw_mc_m1b["ratio"][-1]
        month = tw_mc_m1b["dates"][-1][:7].replace("-", "/")
        behind = tw_mc_m1b.get("months_behind")
        stale_note = f"，資料月份 {month}"
        if behind and behind > TW_MC_M1B_NORMAL_LAG:
            stale_note += f"、落後 {behind} 個月"
        if last_ratio >= TW_MC_M1B_HIGH:
            alerts.append(("warn", f"市值貨幣比 {last_ratio:.2f}，"
                                   f"高於 {TW_MC_M1B_HIGH} 參考線，資金相對吃緊{stale_note}"))
        elif last_ratio <= TW_MC_M1B_LOW:
            alerts.append(("buy", f"市值貨幣比 {last_ratio:.2f}，"
                                  f"低於 {TW_MC_M1B_LOW} 參考線，資金相對寬鬆{stale_note}"))
    if vix:
        last_vix = vix["close"][-1]
        if last_vix > VIX_PANIC_THRESHOLD:
            alerts.append(("warn", f"VIX 恐慌指數 {last_vix:.2f}，超過 {VIX_PANIC_THRESHOLD} 高度恐慌門檻"))
        elif last_vix > VIX_WARN_THRESHOLD:
            alerts.append(("warn", f"VIX 恐慌指數 {last_vix:.2f}，超過 {VIX_WARN_THRESHOLD} 波動升溫門檻"))
    if nikkei:
        last_nikkei = nikkei["close"][-1]
        if last_nikkei < NIKKEI_BUY_THRESHOLD:
            alerts.append(("buy", f"日經225 {last_nikkei:,.0f} 點，低於 {NIKKEI_BUY_THRESHOLD:,} 布局參考線"))
    if michigan:
        last_mi = michigan["close"][-1]
        if last_mi < MICHIGAN_WARN_THRESHOLD:
            zone_label, _ = michigan_zone(last_mi)
            tag = f"（{michigan['dates'][-1][:7].replace('-', '/')} 初值）" if michigan_is_prelim(michigan) else ""
            alerts.append(("warn", f"密大消費者信心指數 {last_mi:.1f}{tag}，落在「{zone_label}」區間（&lt;{MICHIGAN_WARN_THRESHOLD}）"))
    if murata:
        last_bb = murata["bb_ratio"][-1]
        if last_bb > MURATA_BB_WARN_THRESHOLD:
            alerts.append(("warn", f"村田製作所 B/B Ratio {last_bb:.2f}，突破 {MURATA_BB_WARN_THRESHOLD} 反指標聖杯警示線"))
        mlcc_series = murata.get("bb_ratio_mlcc", [])
        last_mlcc = next((v for v in reversed(mlcc_series) if v is not None), None)
        if last_mlcc is not None and last_mlcc > MURATA_BB_WARN_THRESHOLD:
            alerts.append(("warn", f"村田 MLCC 部門 B/B Ratio {last_mlcc:.2f}，突破 {MURATA_BB_WARN_THRESHOLD} 反指標聖杯警示線"))
    for key, stock, fin, quarterly, annual in jp_stocks:
        if not stock:
            continue
        name = stock.get("name", key)
        threshold = JP_STOCK_BUY_THRESHOLD.get(key)
        last_val = stock["close"][-1]
        if threshold is not None and last_val < threshold:
            alerts.append(("buy", f"{name} 收盤 {last_val:,.0f} 円，低於 {threshold:,} 布局參考線"))

        per_threshold = JP_STOCK_PER_THRESHOLD.get(key)
        if per_threshold is not None and annual:
            latest_per = _latest_ttm_per(stock, annual)
            if latest_per is not None and latest_per < per_threshold:
                alerts.append(("buy", f"{name} 本益比 {latest_per:.1f} 倍，低於 {per_threshold:g} 倍布局參考"))
    return alerts


def render_page_header(alerts, taiex, missing=None):
    now_disp = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")
    baseline_disp = taiex["dates"][-1].replace("-", "/") if taiex else "N/A"

    if alerts:
        items = "".join(
            f'<div class="al al-{"buy" if kind == "buy" else "warn"}">'
            f'<span class="al-tag">{"布局機會" if kind == "buy" else "風險預警"}</span>'
            f'<span class="al-txt">{text}</span></div>'
            for kind, text in alerts
        )
        summary_html = f"""
  <div class="summary-box has-alerts alert-list">
    <div class="summary-title alert">🚨 本次報告有 {len(alerts)} 項指標觸發預警／布局參考</div>
    <div class="summary-list">{items}</div>
  </div>"""
    else:
        summary_html = """
  <div class="summary-box">
    <div class="summary-title ok">✅ 目前所有指標皆在正常區間，未觸發任何預警或布局參考線</div>
  </div>"""

    if missing:
        names = "、".join(missing)
        summary_html += f'''
  <div class="summary-box has-alerts">
    <div class="summary-title alert">⚠️ 本次報告缺少 {len(missing)} 個資料來源，對應的區塊沒有畫出來</div>
    <div class="summary-list"><div>{names}</div></div>
  </div>'''

    header = f"""
<div class="page-header">
  <div class="page-header-top">
    <div>
      <!-- 標題那一行拿掉了。
         這份報告平常是嵌在 tw-six-metrics 的〔全球市場監控＋日股觀察〕分頁裡，
         而那一頁自己就有一個同義的標題——兩個標題疊在一起，上面那個講一次、
         下面那個再講一次，中間隔著一條 iframe 的邊界。

         時間戳留著，而且現在是報告的第一行：嵌起來的時候它剛好接在那個分頁的
         標題底下，這正是它該在的位置——「你正在看的這一份是什麼時候的」。 -->
      <div class="page-subtitle stamp-lead">報告生成時間：{now_disp}　｜　報告資料基準：{baseline_disp}</div>
    </div>
  </div>
</div>
"""
    return header, summary_html


def build_html(taiex, vix, nikkei, michigan, murata, jp_stocks,
               tw_pmi=None, tw_mc_m1b=None, us_indices=None, us_fred=None,
               missing=None):
    scripts = []
    us_indices = us_indices or []
    us_fred = us_fred or {}

    alerts = collect_alerts(taiex, vix, nikkei, michigan, murata, jp_stocks,
                            tw_pmi=tw_pmi, tw_mc_m1b=tw_mc_m1b)
    header_html, summary_html = render_page_header(alerts, taiex, missing)

    n_warn = sum(1 for kind, _ in alerts if kind == "warn")
    n_buy = len(alerts) - n_warn
    panes = []

    tw_subs = []
    if taiex:
        t_html, t_script = render_taiex_section(taiex)
        tw_subs.append(("taiex", "台股加權指數", t_html))
        scripts.append(t_script)

    macro_tw_html, macro_tw_scripts = [], []
    if tw_pmi and tw_pmi.get("dates"):
        h, s = render_tw_pmi_section(tw_pmi)
        if h:
            macro_tw_html.append(ind_block(h, IND_TONES[0]))
            macro_tw_scripts.append(s)
    if tw_mc_m1b and tw_mc_m1b.get("dates"):
        h, s = render_tw_marketcap_m1b_section(tw_mc_m1b)
        if h:
            macro_tw_html.append(ind_block(h, IND_TONES[1]))
            macro_tw_scripts.append(s)
    if macro_tw_html:
        tw_subs.append(("twmacro", "台股資金面與景氣領先指標", "".join(macro_tw_html)))
        scripts.append("".join(macro_tw_scripts))

    if tw_subs:
        panes.append(("tw", "台股重要經濟指標", "", sub_tabs("tw", tw_subs)))

    us_subs = []
    idx_result = render_us_indices_section(us_indices) if us_indices else None
    if idx_result:
        i_html, i_script, i_chips = idx_result
        if i_html:
            us_subs.append(("usidx", "美股三大指數", pane_chips(i_chips) + i_html))
            scripts.append(i_script)

    group_html = []
    for group in US_GROUP_CONFIG:
        members = []
        for meta in US_FRED_CONFIG:
            if meta.get("group") != group["key"]:
                continue
            data = us_fred.get(meta["id"])
            if data and data.get("dates"):
                members.append((meta, data))
        if group["key"] == "housing_sentiment" and vix and vix.get("dates"):
            members.append(({"name": "VIX", "unit": "", "freq": "日"}, vix))
        if members:
            g_html, g_script = render_us_indicator_group(group, members)
            if g_html:
                group_html.append(g_html)
            if g_script:
                scripts.append(g_script)

    if group_html:
        group_html.append(render_us_overview_table())
        us_subs.append(("usmacro", "美股經濟指標", "".join(group_html)))

    if vix or michigan:
        inner_html, inner_scripts = [], []
        if vix:
            h, s = render_vix_section(vix)
            inner_html.append(ind_block(h, IND_TONES[2])); inner_scripts.append(s)
        if michigan:
            h, s = render_michigan_section(michigan)
            inner_html.append(ind_block(h, IND_TONES[3])); inner_scripts.append(s)
        us_subs.append(("macro", "VIX ＆ 密大消費者信心", "".join(inner_html)))
        scripts.append("".join(inner_scripts))

    if us_subs:
        panes.append(("us", "美股重要經濟指標", "", sub_tabs("us", us_subs)))

    jp_subs = []
    if nikkei:
        n_html, n_script = render_nikkei_section(nikkei)
        jp_subs.append(("nikkei", "日經225指數", n_html))
        scripts.append(n_script)
    if murata:
        mu_html, mu_script = render_murata_bb_section(murata)
        jp_subs.append(("murata", "村田 B/B Ratio", mu_html))
        scripts.append(mu_script)
    if jp_subs:
        panes.append(("jp", "日股重要經濟指標", "", sub_tabs("jp", jp_subs)))

    jp_html_list = []
    for key, stock, fin, quarterly, annual in jp_stocks:
        if not stock:
            continue
        a_html, a_script = render_jp_stock_section(stock, fin, key, quarterly, annual)
        jp_html_list.append((1 if 'class="chip buy solid"' in a_html.split('class="card-body"', 1)[0] else 0,
                             a_html))
        scripts.append(a_script)
    stock_chips = []
    if jp_html_list:
        jp_html_list = [h for _, h in sorted(jp_html_list, key=lambda t: -t[0])]
        buy_hits = sum(1 for kind, text in alerts
                       if kind == "buy" and "布局參考線" in text)
        stock_chips = [chip("追蹤中", f"{len(jp_html_list)} 檔", vid="mm-watch-count")]
        if buy_hits:
            stock_chips.append(chip("觸發布局", f"{buy_hits} 檔", "buy"))
        shown_keys = {s["key"] for s in JP_STOCK_CONFIG}
        hidden = [s for s in load_jp_stocks(include_disabled=True)
                  if s["key"] not in shown_keys]
        manage = render_manage_bar(with_status=False)
        manage_html = (
            '<details class="fold manage-fold"><summary>⚙️ 管理追蹤名單'
            '<span class="fold-hint">新增個股、重建季報、輸入權杖</span></summary>'
            f'<div class="fold-body">{manage}</div></details>' if manage else "")
        acts = ('<span class="pane-acts">'
                '<button type="button" class="expand-btn" onclick="mmStockCards(false)">全部展開</button>'
                '<button type="button" class="expand-btn" onclick="mmStockCards(true)">全部收合</button>'
                '</span>')
        panes.append(("jpstock", "日股觀察", "",
                      pane_chips(stock_chips + [acts])
                      + manage_html
                      + (render_manage_status() if manage else "")
                      + f'<div class="jp-stock-grid">{"".join(jp_html_list)}</div>'
                      + render_hidden_row(hidden)))

    summary_body = summary_html
    badge = ""
    if n_warn:
        badge += f'<span class="tab-badge warn" title="風險預警 {n_warn} 項">{n_warn}</span>'
    if n_buy:
        badge += f'<span class="tab-badge buy" title="布局參考 {n_buy} 項">{n_buy}</span>'
    panes.insert(0, ("summary", "重點摘要", badge, summary_body))
    tabs_html = render_tabs(panes)

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日全球市場與總經個股監控報告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>{CSS}</style>
</head>
<body>
{header_html}
<div class="wrap">
{tabs_html}
</div>

<script>
{SHARED_JS}
{''.join(scripts)}
</script>
<script>
{TABS_JS}
  // 刻意放在獨立的 script 區塊：上面任何一張圖表若出錯（例如 CDN 沒載入），
  // 也不會連帶讓折疊、縮字、分頁這些基本功能失效。
  clearSavedCardStates();
  setInitialCardStates();  // 卡片與趨勢圖全部收合
  mmRestoreTab();          // 網址帶著 #tw/twmacro 的話回到那一頁
  requestAnimationFrame(function () {{ requestAnimationFrame(fitAllCardHeads); }});
  watchCardHeads();
  if (document.fonts && document.fonts.ready) {{
    document.fonts.ready.then(fitAllCardHeads);   // 字型載入後寬度會變，再校一次
  }}
</script>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true",
                         help="本地測試模式：輸出到 local_test/index.html，強制不寄信")
    args = parser.parse_args()

    taiex = load_json("taiex.json")
    if taiex is None:
        raise FileNotFoundError("找不到 data/taiex.json。請先執行 `python fetch_market_data.py`。")
    vix = load_json("vix.json")
    nikkei = load_json("nikkei.json")
    michigan = load_json("michigan.json")
    murata = load_json("murata_bb.json")

    tw_pmi = load_json("tw_pmi.json")
    tw_mc_m1b = load_json("tw_marketcap_m1b.json")

    us_indices = [(idx["key"], load_json(f"index_{idx['key']}.json")) for idx in US_INDEX_CONFIG]
    us_fred = {}
    for meta in US_FRED_CONFIG:
        cache = meta.get("cache") or f"fred_{meta['id'].lower()}.json"
        data = load_json(cache)
        if data:
            us_fred[meta["id"]] = data

    JP_STOCK_KEYS = [s["key"] for s in JP_STOCK_CONFIG]
    if not JP_STOCK_KEYS:
        print("⚠️ config.json 裡沒有任何啟用中的個股，本次報告不含個股區塊。")
    jp_stocks = []
    missing = []
    for key in JP_STOCK_KEYS:
        stock = load_json(f"stock_{key}.json")
        fin = load_json(f"stock_{key}_financials.json")
        quarterly = load_json(f"stock_{key}_quarterly_financials.json")
        annual = load_json(f"stock_{key}_quarterly_financials.json") or load_json(f"stock_{key}_annual_financials.json")
        if stock is None:
            print(f"⚠️ 找不到 data/stock_{key}.json，本次輸出會跳過這檔個股。")
            missing.append(f"個股 {key}")
        jp_stocks.append((key, stock, fin, quarterly, annual))

    for name, val in [("vix.json", vix), ("nikkei.json", nikkei), ("michigan.json", michigan),
                       ("murata_bb.json", murata), ("tw_pmi.json", tw_pmi),
                       ("tw_marketcap_m1b.json", tw_mc_m1b)]:
        if val is None:
            print(f"⚠️ 找不到 data/{name}，本次輸出會跳過對應區塊。")
            missing.append(name)

    missing_idx = [k for k, v in us_indices if v is None]
    if missing_idx:
        print(f"⚠️ 找不到美股指數快取：{', '.join(missing_idx)}，本次報告會跳過這幾條線。")
        missing.extend(f"美股指數 {k}" for k in missing_idx)
    missing_fred = [m["id"] for m in US_FRED_CONFIG if m["id"] not in us_fred]
    if missing_fred:
        print(f"⚠️ 找不到 FRED 指標快取：{', '.join(missing_fred)}，本次報告不顯示這幾格。")
        missing.extend(f"FRED {m}" for m in missing_fred)

    if missing and os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning title=報告缺少資料來源::{'、'.join(missing)}")

    html = build_html(taiex, vix, nikkei, michigan, murata, jp_stocks,
                      missing=missing,
                      tw_pmi=tw_pmi, tw_mc_m1b=tw_mc_m1b,
                      us_indices=us_indices, us_fred=us_fred)

    if args.local:
        out_dir = os.path.join(BASE_DIR, "local_test")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "index.html")
    else:
        out_path = os.path.join(BASE_DIR, "index.html")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ 已產生：{out_path}")
    if args.local:
        print("🧪 本地測試模式：未寄信、未動到正式 index.html。用瀏覽器打開上面路徑檢查即可。")


if __name__ == "__main__":
    main()
