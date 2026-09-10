# -*- coding: utf-8 -*-
"""
generate_report_local.py
修正版報告產生器 v5

這一版的改動：
1. VIX 與密大信心指數改回「各自獨立的圖」，但放在同一個大卡片裡上下
   排列（不共用時間軸，不會再有排版擁擠的問題），密大信心指數的
   tooltip 跟統計卡片會顯示目前落在哪個警戒區間。
2. VIX 圖補上 20 (波動升溫) / 30 (高度恐慌) 兩條門檻線，配色跟平常
   紅色警示線做出层次區分。
3. 所有統計卡片，只要數值觸發預警，卡片本身會變色：
   - 「可以布局」類型（TAIEX < 38,000、10日均量 < 8,000億、日經 < 56,000）
     用藍/青色，代表機會而不是危險。
   - 「風險警戒」類型（VIX > 20、密大 < 60、村田 B/B > 1.2）用紅色。
4. 村田 B/B Ratio 警示門檻改成 1.2（原本是拿 1.0 均衡線做警示，現在
   拆開：1.0 只是均衡參考線，1.2 才是真正的警示線），並附上「反指標
   聖杯」的說明文字。
5. 新增日本個股區塊，目前先做味之素 (2802.T)：股價用 Yahoo Finance
   Chart API 自動抓（跟日經225同邏輯），財務指標 (PER/EPS/PBR/營益率)
   比照村田 B/B Ratio 的做法，人工從財報網站讀取存進
   data/stock_ajinomoto_financials.json。

用法：
    python fetch_market_data.py          # 抓 taiex/vix/nikkei/michigan/個股 價格
    python generate_report_local.py --local   # 本地測試，看 local_test/index.html
    python generate_report_local.py            # 正式模式，輸出 index.html（部署用）
"""

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone

# Windows 沒有內建 IANA 時區資料庫，zoneinfo 需要另外裝 tzdata 套件
# （pip install tzdata）才能找到 "Asia/Taipei"。這裡做防護：找不到就退回
# 固定 UTC+8（台灣沒有日光節約時間，固定 8 小時永遠準確），不會讓報告產不出來。
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

# ---------------------------------------------------------------------------
# 警示門檻設定 — 全部讀自 config.json，要調整請改那個檔案，不用動這裡
# ---------------------------------------------------------------------------
_TH = load_thresholds()
TAIEX_BUY_THRESHOLD = _TH["taiex_buy"]              # < 此值 => 可以考慮布局
VOLUME_BUY_THRESHOLD_BIL = _TH["taiex_volume_buy_bil"]  # 10日均量 < 此值 => 可以考慮布局
NIKKEI_BUY_THRESHOLD = _TH["nikkei_buy"]            # < 此值 => 可以考慮布局
VIX_WARN_THRESHOLD = _TH["vix_warn"]                # > 此值 => 波動升溫警戒
VIX_PANIC_THRESHOLD = _TH["vix_panic"]              # > 此值 => 高度恐慌
MICHIGAN_WARN_THRESHOLD = _TH["michigan_warn"]      # < 此值 => 衰退警戒
MURATA_BB_WARN_THRESHOLD = _TH["murata_bb_warn"]    # > 此值 => 反指標聖杯警示
PER_BUY_DEFAULT = _TH["per_buy_default"]            # 本益比 < 此值 => 可以考慮布局（個股可各自覆寫）
PMI_NEUTRAL = _TH["pmi_neutral"]                    # PMI/NMI 榮枯線（50）
TW_MC_M1B_HIGH = _TH["tw_marketcap_m1b_high"]       # 備援：歷史不足時，> 此值 => 吃緊
TW_MC_M1B_LOW = _TH["tw_marketcap_m1b_low"]         # 備援：歷史不足時，< 此值 => 寬鬆
TW_MC_M1B_PCT_HIGH = _TH["tw_marketcap_m1b_pct_high"]  # 主要判準：≥ 第 N 百分位 => 吃緊
TW_MC_M1B_PCT_LOW = _TH["tw_marketcap_m1b_pct_low"]    # 主要判準：≤ 第 N 百分位 => 寬鬆

US_INDEX_CONFIG = load_us_indices()
US_FRED_CONFIG = load_fred_series()
US_GROUP_CONFIG = load_us_indicator_groups()

# 個股清單（順序＝顯示順序，已濾掉 enabled=false 的隱藏個股）
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
    """台股慣例：漲=紅色配上升三角形，跌=綠色配下降三角形，平盤=灰色。
    回傳 (color, arrow) 供組字串用。"""
    if diff > 0:
        return "#ef4444", "▲"
    if diff < 0:
        return "#10b981", "▼"
    return "#94a3b8", ""


def fmt_diff(diff, decimals=2, pct=None):
    """組出『▲ 7.00 (2.72%)』這種帶三角形的漲跌字串，顏色由呼叫端另外套用。

    數字不帶正負號——方向由三角形表示，再加一個 `+`／`-` 等於同一件事講兩次，
    而且 `▼-30.0` 讀起來像雙重否定。漲跌幅收進括號，跟漲跌點數分開，
    掃過去的時候不會把兩個數字讀成一個。
    """
    color, arrow = updown(diff)
    if not arrow:
        # 平盤印「0.00 (0.00%)」只是把兩個零講兩次，不如直接說持平。
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
  .chip.price.down .chip-v, .chip.price.down .chip-k { color:#10b981; }
  .chip.buy { border-color:rgba(34,211,238,0.45); background:rgba(34,211,238,0.10); }
  .chip.buy .chip-v { color:#22d3ee; }
  .chip.warn { border-color:rgba(239,68,68,0.45); background:rgba(239,68,68,0.10); }
  .chip.warn .chip-v { color:#ef4444; }
  .chip.solid { font-weight:700; font-size:0.92em; padding:0.25em 0.75em; }
  .chip.buy.solid { color:#22d3ee; }
  .chip.warn.solid { color:#ef4444; }

  /* ---- 全部展開／收合 ---- */
  .expand-all-bar { display:flex; justify-content:flex-end; gap:8px; margin-bottom:12px; }
  .expand-btn { font-size:11.5px; font-weight:600; color:var(--text-muted); background:rgba(148,163,184,0.08);
                border:1px solid var(--border-color); border-radius:7px; padding:5px 12px; cursor:pointer; }
  .expand-btn:hover { color:var(--text-main); border-color:#22d3ee; }

  /* 五大區塊。每一塊一個色系 —— 一打開報告看到的是五條收合的橫幅，
     顏色是用來「認位置」的：捲到一半也知道自己在哪一塊。
     色相由 --blk 帶進來，其餘規則共用，不要為每一塊各寫一份。 */
  .block-card { border-left:4px solid var(--blk); background:
                linear-gradient(90deg, color-mix(in srgb, var(--blk) 10%, transparent) 0%,
                                       var(--bg-card) 42%); }
  .block-card > .card-head .card-title { font-size:1.06em; color:#f8fafc; letter-spacing:0.4px; }
  .block-card > .card-head .card-title::before { content:''; display:inline-block; width:8px; height:8px;
                border-radius:50%; background:var(--blk); margin-right:9px; vertical-align:middle; }
  .block-card > .card-head:hover .card-chev { color:var(--blk); }
  .block-card:not(.collapsed) { box-shadow:0 0 0 1px color-mix(in srgb, var(--blk) 28%, transparent) inset; }
  /* 內層卡片跟外層拉開層次，否則兩層邊框疊在一起會很吵。 */
  .block-card > .card-body > .section-card { background:rgba(11,15,25,0.45); margin-bottom:14px; }
  .block-card > .card-body > .section-card:last-child { margin-bottom:0; }
  .block-card > .card-body > .jp-stock-grid { margin-top:2px; }
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
  .fin-info-btn { background:none; border:none; color:#facc15; font-size:12px; cursor:pointer; padding:0; line-height:1; }
  .page-header { max-width:1280px; margin:0 auto 20px auto; }
  .page-header-top { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; flex-wrap:wrap; }
  .page-title { font-size:30px; font-weight:800; color:#f8fafc; letter-spacing:0.3px; }
  .page-subtitle { font-size:13px; color:var(--text-muted); margin-top:6px; }
  /* 標題拿掉之後它變成第一行，上面不再需要留白。 */
  .page-subtitle.stamp-lead { margin-top:0; }
  .mode-toggle-btn { flex-shrink:0; display:inline-flex; align-items:center; gap:6px; background:rgba(59,130,246,0.14);
                      border:1px solid rgba(59,130,246,0.5); color:#93c5fd; font-size:12.5px; font-weight:700;
                      padding:8px 16px; border-radius:22px; cursor:pointer; white-space:nowrap; transition:background .2s,transform .15s; }
  .mode-toggle-btn:hover { background:rgba(59,130,246,0.28); transform:translateY(-1px); }
  .mode-toggle-btn:active { transform:translateY(0); }
  .summary-box { margin-top:16px; padding:16px 18px; border-radius:12px; border:1px solid var(--border-color); background:var(--bg-card); }
  .summary-box.has-alerts { border-color:#ef4444; background:rgba(239,68,68,0.08); }
  .summary-title { font-size:14px; font-weight:700; margin-bottom:10px; }
  .summary-title.alert { color:#f87171; }
  .summary-title.ok { color:#10b981; }
  .summary-list { font-size:12.5px; line-height:2; color:#e2e8f0; }
  .summary-list b { color:#facc15; }
  .jp-stock-grid { display:grid; grid-template-columns:1fr; gap:20px; align-items:start; width:100%; box-sizing:border-box; }
  .jp-stock-grid .section-card { margin-bottom:0; display:flex; flex-direction:column; min-width:0; }
  .jp-stock-grid .section-card:hover { box-shadow:0 8px 26px rgba(0,0,0,0.32); transform:translateY(-2px); }
  @media (min-width:1180px) {
    .jp-stock-grid { grid-template-columns:1fr 1fr; }
  }
  .info-btn { display:inline-flex; align-items:center; gap:4px; background:rgba(250,204,21,0.12); border:1px solid rgba(250,204,21,0.4);
              color:#facc15; font-size:11px; font-weight:600; padding:3px 10px; border-radius:14px; cursor:pointer; margin-left:10px; vertical-align:middle; }
  .info-btn:hover { background:rgba(250,204,21,0.22); }
  .info-popup { display:none; margin:10px 0; padding:14px 16px; background:rgba(250,204,21,0.06); border:1px solid rgba(250,204,21,0.35);
                border-radius:8px; font-size:12px; line-height:1.8; color:#e2e8f0; white-space:pre-line; }
  .info-popup.open { display:block; }
  .title-row { display:flex; align-items:center; flex-wrap:wrap; margin-bottom:14px; }
  /* 由 JS 依卡片實際寬度加上，收起次要資訊只留股價與警示標籤 */
  .card-summary.compact .chip:not(.price):not(.solid) { display:none; }

  @media (max-width:768px) {
    .stat-grid { grid-template-columns:1fr; }
    .fin-grid { grid-template-columns:1fr 1fr; }
    .stat-value { font-size:21px; }
    .chart-container { height:280px; }
    .card-head-main { font-size:14.5px; }
    .section-card { padding:14px 14px; }
    .section-card.collapsed { padding:12px 14px; }
  }

  /* 版型切換只調基準字級，實際是否縮放、是否收起標籤交給 JS 依卡片寬度決定，
     這裡不用 !important，否則會蓋掉那些調整。 */
  html.force-mobile .card-head-main { font-size:14.5px; }
  html.force-desktop .card-head-main { font-size:16px; }

  /* ---- 手動切換「電腦版／手機版」：不論實際螢幕寬度，強制套用指定版型 ---- */
  html.force-mobile body { padding:12px; }
  html.force-mobile .wrap { max-width:480px; gap:14px; }
  html.force-mobile .section-card { padding:14px 14px; border-radius:12px; }
  html.force-mobile .page-header-top { flex-direction:column; align-items:stretch; }
  html.force-mobile .mode-toggle-btn { align-self:flex-end; }
  html.force-mobile .page-title { font-size:22px; }
  html.force-mobile .stat-grid { grid-template-columns:1fr !important; }
  html.force-mobile .fin-grid { grid-template-columns:1fr 1fr !important; }
  html.force-mobile .jp-stock-grid { grid-template-columns:1fr !important; }
  html.force-mobile .stat-value { font-size:21px !important; }
  html.force-mobile .chart-container { height:260px !important; }
  html.force-mobile .chart-container.short { height:220px !important; }
  html.force-mobile .tf-btn { padding:4px 10px; font-size:11px; }

  html.force-desktop .wrap { max-width:1280px; }
  html.force-desktop .jp-stock-grid { grid-template-columns:1fr 1fr !important; }
  html.force-desktop .stat-grid { grid-template-columns:1fr 1fr !important; }
  html.force-desktop .fin-grid { grid-template-columns:repeat(4,1fr) !important; }
  html.force-desktop .stat-value { font-size:26px !important; }
  html.force-desktop .chart-container { height:380px !important; }
  html.force-desktop .chart-container.short { height:260px !important; }
  html.force-desktop body { overflow-x:auto; }
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
  function toggleInfo(id) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('open');
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
      // 用 important 寫入，否則會被版型切換那組 !important 規則蓋掉
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
  function applyViewMode(mode) {
    const html = document.documentElement;
    html.classList.remove('force-desktop', 'force-mobile');
    // 'auto' 表示不強制，交給 CSS 的響應式規則依實際寬度決定，
    // 這樣視窗多寬就用多寬的版型，不會在 768px 這種尷尬寬度被硬塞成兩欄。
    if (mode === 'mobile' || mode === 'desktop') {
      html.classList.add(mode === 'mobile' ? 'force-mobile' : 'force-desktop');
    }
    const btn = document.getElementById('modeToggleBtn');
    if (btn) {
      btn.dataset.mode = mode;
      const wide = window.innerWidth >= 768;
      btn.innerHTML = (mode === 'mobile' || (mode === 'auto' && !wide))
        ? '🖥️ 切換為電腦版' : '📱 切換為手機版';
    }
    setTimeout(() => {
      Object.values(chartRegistry).forEach((entry) => {
        if (entry && entry.chart) entry.chart.resize();
      });
      fitAllCardHeads();
    }, 60);
  }
  function toggleViewMode() {
    const btn = document.getElementById('modeToggleBtn');
    const cur = btn ? btn.dataset.mode : 'auto';
    if (cur === 'mobile') applyViewMode('desktop');
    else if (cur === 'desktop') applyViewMode('mobile');
    else applyViewMode(window.innerWidth >= 768 ? 'mobile' : 'desktop');
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


# ---------------------------------------------------------------------------
# TAIEX
# ---------------------------------------------------------------------------
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

    # TWSE 的官方統計報表是「盤後彙整」，不是收盤瞬間就有——實務上要到傍晚後
    # 才會放上當天資料。所以「還沒抓到今天」很常是資料源當下沒有，不是程式壞掉。
    # 這裡明確算給人看，而不是讓人自己猜為什麼還停在前一天。
    last_data_date = datetime.strptime(dates[-1], "%Y-%m-%d").date()
    today_taipei = datetime.now(TAIPEI_TZ).date()
    gap_days = (today_taipei - last_data_date).days
    # 用「最近一個已過去的平日」當作應該要有資料的基準，跳過還沒收盤的當天與週末
    expected = today_taipei
    while expected.weekday() >= 5:          # 5=六 6=日，退到最近的平日
        expected -= timedelta(days=1)
    if expected == today_taipei and datetime.now(TAIPEI_TZ).hour < 17:
        expected -= timedelta(days=1)       # 今天還沒到傍晚，官方報表通常還沒出
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

  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="https://www.google.com/finance/beta/quote/IX0001:TPE?type=area" target="_blank">Google</a>　｜　<a href="https://www.twse.com.tw/zh/trading/historical/fmtqik.html" target="_blank">TWSE</a>　｜　{vintage_note}
  </div>
"""
    if stale:
        taiex_summary += '<span class="chip warn">資料尚未更新到今天</span>'
    section_html = collapsible("taiex", "台股加權指數", taiex_summary, taiex_body,
                               alert=bool(idx_buy or vol_buy))

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


# ---------------------------------------------------------------------------
# VIX + 密大信心指數（同卡片、各自獨立子圖）
# ---------------------------------------------------------------------------
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
    """回傳該月最後一個週五的日期。"""
    # 先取該月最後一天：跳到下個月一號再退一天
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = nxt - timedelta(days=1)
    # weekday(): 週一=0 … 週五=4
    return last_day - timedelta(days=(last_day.weekday() - 4) % 7)


def michigan_next_release(last_date_str):
    """推算 FRED 下一次補上新數據的日期。

    密大授權 FRED 的條件是「延遲一個月」，實務上 FRED 固定在每個月的
    最後一個週五更新，補進「前一個月」的數值。例如資料最新到 6 月時，
    7 月的數值會在 8 月的最後一個週五出現。

    回傳 ((下一筆數據的年, 月), 公布日期)。若推算出的日期已經過去
    （資料源臨時延後），會自動往後推到下一個月，不會顯示過期資訊。
    """
    try:
        y, m = int(last_date_str[:4]), int(last_date_str[5:7])
    except (ValueError, IndexError):
        return None, None

    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)          # 下一筆數據的月份
    ry, rm = (ny + 1, 1) if nm == 12 else (ny, nm + 1)      # 該筆數據的公布月份

    today = date.today()
    for _ in range(24):
        rel = _last_friday(ry, rm)
        if rel >= today:
            return (ny, nm), rel
        ry, rm = (ry + 1, 1) if rm == 12 else (ry, rm + 1)
    return (ny, nm), _last_friday(ry, rm)


def render_michigan_section(michigan):
    dates_json = json.dumps(michigan["dates"], ensure_ascii=False)
    close_json = json.dumps(michigan["close"], ensure_ascii=False)
    fetched_at = michigan.get("fetched_at", "")
    dates, close = michigan["dates"], michigan["close"]

    last_val = close[-1]
    prev_val = close[-2] if len(close) > 1 else last_val
    diff = round(last_val - prev_val, 2)
    last_date_disp = dates[-1].replace("-", "/")
    pct = round(diff / prev_val * 100, 2) if prev_val else None
    diff_txt, chg_color = fmt_diff(diff, 1, pct)
    warn = last_val < MICHIGAN_WARN_THRESHOLD
    zone_label, zone_color = michigan_zone(last_val)

    # 這個指標的「新舊」不能看抓取日期：密大授權 FRED 延遲一個月，
    # 就算今天剛抓過，最新值仍會落後一到兩個月。所以標出資料本身涵蓋到哪個月，
    # 以及下一筆何時才會出現，才不會讓人誤以為資料沒更新或程式壞掉。
    next_month, release_date = michigan_next_release(dates[-1])
    vintage_txt = f"資料截至 {dates[-1][:7]}"
    if next_month and release_date:
        vintage_txt += (f"（官方延遲一個月，{next_month[1]}月數據將於 "
                        f"{release_date.strftime('%m/%d')} 發布）")
    else:
        vintage_txt += "（官方延遲一個月）"

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
  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="https://fred.stlouisfed.org/series/UMCSENT" target="_blank">FRED</a>　｜　{vintage_txt}
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


# ---------------------------------------------------------------------------
# 日經225
# ---------------------------------------------------------------------------
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
  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="https://finance.yahoo.com/quote/%5EN225/" target="_blank">Yahoo Finance</a>　｜　{fetched_at}
  </div>
"""
    section_html = collapsible("nikkei", "日經225指數", nikkei_summary, nikkei_body, alert=bool(buy))

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


# ---------------------------------------------------------------------------
# 村田製作所 B/B Ratio
# ---------------------------------------------------------------------------
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
    <button class="info-btn" onclick="toggleInfo('murataInfo')">💡 反指標聖杯</button>
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

  <div class="custom-legend" id="murataLegend" style="margin-top:14px;"></div>
  <div class="chart-container" style="height:320px;"><canvas id="murataChart"></canvas></div>

  <div class="chart-source-box" title="資料來源與更新時間">
    📌 <a href="{source_url}" target="_blank">村田法說會</a>　｜　人工登錄　｜　資料截至 {last_q}　｜　每季法說會後更新（約 4月底・7月底・10月底・2月初）
  </div>
"""
    murata_summary = (chip("B/B", f"{last_bb:.2f}")
                      + (chip("MLCC", f"{last_mlcc:.2f}") if last_mlcc is not None else "")
                      + ('<span class="chip warn solid">反指標警示</span>' if (warn or mlcc_warn) else ""))
    section_html = collapsible("murata", "村田製作所 (6981.T) B/B Ratio",
                               murata_summary, murata_body, alert=bool(warn or mlcc_warn))

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


# ---------------------------------------------------------------------------
def short_host(url):
    """把網址縮成好認的網域名。www. 這種前綴佔空間又沒有辨識度，去掉。"""
    host = url.split("//")[-1].split("/")[0]
    return host[4:] if host.startswith("www.") else host


def source_links(urls, limit=2):
    """來源連結列。來源多的時候只列前幾個，避免那一列被撐爆。"""
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


def collapsible(card_id, title, summary_html, body_html, open_by_default=False, alert=False):
    """把一個區塊包成可折疊的卡片。

    一律預設收合，讓整份報告一眼掃完；需要細看時點一下展開。
    收合狀態會記在瀏覽器裡，下次打開會維持上次的選擇。
    alert 參數保留給摘要列上色使用，不再影響預設展開與否。
    """
    collapsed_cls = "" if open_by_default else " collapsed"
    return f"""
<div class="section-card{collapsed_cls}" id="card-{card_id}" data-card="{card_id}">
  <button class="card-head" type="button" onclick="toggleCard('{card_id}')" aria-expanded="{str(open_by_default).lower()}">
    <span class="card-head-main">
      <span class="card-title">{title}</span>
      <span class="card-summary">{summary_html}</span>
    </span>
    <span class="card-chev" aria-hidden="true">⌄</span>
  </button>
  <div class="card-body">
{body_html}
  </div>
</div>
"""


#: 五大區塊各自的色系。順序＝顯示順序。
BLOCK_TONES = {
    "summary": "#f59e0b",   # 重點摘要　琥珀
    "tw":      "#22d3ee",   # 台股　　　青
    "us":      "#3b82f6",   # 美股　　　藍
    "jp":      "#a855f7",   # 日股總經　紫
    "jpstock": "#10b981",   # 日股觀察　綠
}


def block_card(card_id, title, summary_html, body_html):
    """一個大區塊。兩層都預設收合。

    打開報告看到的是五條橫幅，顏色是用來認位置的——捲到一半也知道自己在哪一塊。
    展開哪一塊、那一塊裡面再看哪一張，都由讀者自己決定；一次只攤開真正要看的東西。
    """
    tone = BLOCK_TONES.get(card_id, "#64748b")
    return f"""
<div class="section-card block-card collapsed" id="card-{card_id}" data-card="{card_id}" style="--blk:{tone};">
  <button class="card-head" type="button" onclick="toggleCard('{card_id}')" aria-expanded="false">
    <span class="card-head-main">
      <span class="card-title">{title}</span>
      <span class="card-summary">{summary_html}</span>
    </span>
    <span class="card-chev" aria-hidden="true">⌄</span>
  </button>
  <div class="card-body">
{body_html}
  </div>
</div>
"""


def chip(label, value, tone=""):
    """摘要列上的一格小資訊。tone 可用 up / down / buy / warn 上色。"""
    cls = f"chip {tone}".strip()
    return f'<span class="{cls}"><span class="chip-k">{label}</span><span class="chip-v">{value}</span></span>'


# 日本焦點個股（可重複套用於多檔股票）
# ---------------------------------------------------------------------------
def _price_on_or_before(dates, closes, target_date):
    """在真實逐日股價序列裡，找『目標日期當天或最近一個交易日之前』的真實收盤價。
    用來把財年結束日（例如 3/31，可能剛好是假日）對應到當時真實成交的股價，
    不是憑空捏造某一天的股價。找不到就回傳 None。"""
    result = None
    for d, c in zip(dates, closes):
        if d <= target_date:
            result = c
        else:
            break
    return result


def _latest_ttm_per(stock, annual):
    """算出最新一期的本益比（季度資料用近四季 EPS 加總的 TTM 口徑）。

    刻意與個股卡片內的 PER 算法完全一致：同樣用財報期末當日（或之前最近交易日）
    的真實收盤價，季度資料同樣要求近四季 EPS 齊全才計算，不滿四季寧可回傳 None，
    避免摘要與卡片顯示不同的數字。
    """
    if not annual or not annual.get("fiscal_year_end_dates"):
        return None
    eps_list = annual.get("eps_jpy") or []
    labels = annual.get("fiscal_years") or []
    if not eps_list or not labels:
        return None

    i = len(eps_list) - 1
    price = _price_on_or_before(stock["dates"], stock["close"], annual["fiscal_year_end_dates"][i])
    if price is None:
        return None

    if "Q" in labels[i]:
        if i >= 3 and all(e is not None for e in eps_list[i - 3:i + 1]):
            ttm_eps = sum(eps_list[i - 3:i + 1])
            return round(price / ttm_eps, 2) if ttm_eps else None
        return None
    eps = eps_list[i]
    return round(price / eps, 2) if eps else None


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

    # 先驗證 annual/quarterly 趨勢資料格式
    if annual and not ("fiscal_years" in annual and "fiscal_year_end_dates" in annual):
        print(f"⚠️ {key} 的財經指標趨勢資料格式不正確（缺少 fiscal_years/fiscal_year_end_dates 欄位），本次跳過這張圖，不會讓整份報告失敗。")
        annual = None

    # 先把趨勢圖的 PER/PBR 算出來，財務指標快照才能直接引用同一份數字（不是另外重算一次），
    # 這樣快照跟趨勢圖最後一筆保證永遠一致，不會再有兩邊對不上的狀況。
    per_series, pbr_series = [], []
    if annual:
        # PER 若是季度資料，要用「近四季 EPS 加總」(TTM，trailing-twelve-months) 而不是單季 EPS，
        # 否則單季獲利淡旺季波動會讓 PER 失真（例如某季因一次性費用獲利驟減，單季本益比會暴衝到不合理的數字）。
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
                    per_series.append(None)  # 不滿四季歷史，年化會失真，寧可留空不亂算
            else:
                per_series.append(round(price / eps, 2) if eps else None)
        for price, bvps in zip(fy_prices, annual.get("bvps_jpy", [])):
            pbr_series.append(round(price / bvps, 2) if (price is not None and bvps) else None)

    fin_html = ""
    snap_per_for_chip = None
    snap_margin_for_chip = None
    per_buy_for_chip = False
    if not fin and not annual:
        # 新加入的個股還沒有季報資料。這裡照樣把四個欄位畫出來、值留「—」，
        # 版面才會跟其他個股一致，也一眼看得出是「還沒建立」而不是程式壞掉。
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
        # 這四個數字其實都來自趨勢圖資料，快照檔只負責提供來源連結與公布日。
        # 所以只要有趨勢資料就要顯示，不能因為缺快照檔就整塊不畫。
        fin = fin or {}
        if annual:
            latest_quarter_label = annual["fiscal_years"][-1]
            snap_eps = annual.get("eps_jpy", [None])[-1]
            snap_margin = annual.get("operating_margin_pct", [None])[-1]
            snap_per = per_series[-1] if per_series else None
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

        # 本益比布局判斷：PER 低於門檻 => 標示可考慮布局（門檻可在 config.json 逐檔設定）
        per_threshold = JP_STOCK_PER_THRESHOLD.get(key)
        per_buy = (snap_per is not None) and (per_threshold is not None) and (snap_per < per_threshold)
        per_badge = alert_badge(per_buy, 'PER 可布局', 'buy')
        per_sub = (f'<div class="fin-sub">布局參考：&lt; {per_threshold:g} 倍</div>'
                   if per_threshold is not None else "")
        snap_per_for_chip = snap_per
        snap_margin_for_chip = snap_margin
        per_buy_for_chip = per_buy

        # 來源與公布日優先取自快照檔；自動建立的個股沒有快照檔，就退回趨勢檔本身記載的來源
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
        # 虧損季度(營益率<0)的長條改成警示紅色，正常獲利維持原本綠色，一眼就能看出虧損那一季
        margin_colors_json = json.dumps([
            "rgba(239,68,68,0.75)" if (m is not None and m < 0) else "rgba(16,185,129,0.55)"
            for m in annual["operating_margin_pct"]
        ])
        per_json = json.dumps(per_series)
        eps_json = json.dumps(annual.get("eps_jpy", []))
        pbr_json = json.dumps(pbr_series)

        # 附註只留來源與資料本身的新舊程度。日期採用「資料截至哪一季＋官方公布日」，
        # 而不是我們自己跑程式的日期——後者只說明何時抓取，看不出數據是否過時。
        a_links = source_links(annual.get("source_urls")) or annual.get("source", "未標註來源")
        latest_q = annual["fiscal_years"][-1] if annual.get("fiscal_years") else ""
        vintage = f"截至 {latest_q}" if latest_q else ""
        if fin.get("disclosure_date"):
            vintage += f"（{fin['disclosure_date']}）"

        annual_html = f"""
  <div class="title-row">
    <div class="sub-title" style="margin-bottom:0;">{name} 財經指標</div>
    <button class="info-btn" onclick="toggleInfo('{key}AMethod')">💡 資料怎麼來的</button>
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

    # 摘要列：收合時就靠這一行做判斷，所以要放最關鍵的數字與訊號
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

    section_html = collapsible(
        key, f"{name} ({code})", "".join(summary_chips), body_html,
        alert=bool(buy or per_buy_for_chip),
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


# ---------------------------------------------------------------------------
# 燈泡說明（💡）
# ---------------------------------------------------------------------------
def tip_button(tip_id, key):
    """
    產生「💡 短標題」按鈕 ＋ 收合的說明區塊。

    文字全部放在 explanations.py 的 TIPS 裡 —— 想改內容只要動那個檔，
    不用碰這裡的排版邏輯。找不到 key 就回傳空字串，不會讓報告產不出來。
    """
    entry = TIPS.get(key)
    if not entry:
        return "", ""
    label, body = entry
    btn = f'<button class="info-btn" onclick="toggleInfo(\'{tip_id}\')">💡 {label}</button>'
    popup = f'<div id="{tip_id}" class="info-popup">{html_escape(body)}</div>'
    return btn, popup


def html_escape(text):
    """說明文字是純文字，出現 < > & 時要跳脫，不然會被當標籤吃掉。"""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def titled_row(title, tip_id=None, tip_key=None, level="section-title"):
    """標題列＋（可選）燈泡。回傳整段 HTML。"""
    btn, popup = tip_button(tip_id, tip_key) if tip_id and tip_key else ("", "")
    return f"""
  <div class="title-row">
    <div class="{level}" style="margin-bottom:0;">{title}</div>
    {btn}
  </div>
  {popup}
"""


def vintage_note(iso_month, months_behind=None, freq=""):
    """
    誠實標示這格數字代表的是哪個月，而不是讓人以為是「今天」。

    落後三個月以上會加上警示色 —— 不是資料錯了，是來源本來就慢，
    但看報告的人有權利一眼知道。
    """
    if not iso_month:
        return ""
    disp = iso_month[:7].replace("-", "/")
    if months_behind is None:
        months_behind = _months_behind_iso(iso_month)
    suffix = f"｜{freq}頻" if freq else ""
    if months_behind is not None and months_behind >= 3:
        return (f'<span class="vintage stale">資料月份 {disp}'
                f'（落後 {months_behind} 個月）{suffix}</span>')
    return f'<span class="vintage">資料月份 {disp}{suffix}</span>'


def _months_behind_iso(iso_date):
    try:
        y, m = int(iso_date[:4]), int(iso_date[5:7])
    except (ValueError, TypeError):
        return None
    today = date.today()
    return (today.year - y) * 12 + (today.month - m)


def fmt_period(iso_date, freq=""):
    """
    把資料日期顯示成跟該指標頻率相符的樣子。

    季頻序列在 FRED 裡是用「該季第一個月的 1 號」表示的，直接印 2026/04
    會讓人以為是四月的數字 —— 實際上那是第二季。週頻則要看到日，
    因為初請失業金一週就換一筆。
    """
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
    """依單位挑一個看得懂的格式。經濟指標的量級差很大，硬用同一種會很難讀。"""
    if value is None:
        return "—"
    if "%" in unit:
        return f"{value:,.1f}%"
    if abs(value) >= 10000:
        return f"{value:,.0f}"
    if abs(value) >= 100:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


# ---------------------------------------------------------------------------
# 台股：製造業 PMI ／ 非製造業 NMI
# ---------------------------------------------------------------------------
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

    # NMI 原本只有一個數字，沒有月變化。往回找上一個非 None 的值把它補上。
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
    # 擴張/收縮不是「警示」，是狀態，所以用 buy/warn 兩種既有色系表達方向
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


# ---------------------------------------------------------------------------
# 台股：市值貨幣比
# ---------------------------------------------------------------------------
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

    # 分區用**百分位**，不用固定的絕對值。
    #
    # 這個數列有結構性的上升趨勢：2016 年中位 1.86、2021 年 2.43、2024 年 2.81、
    # 2026 年 4.56。原本那組固定門檻（>4.5 吃緊、<2.5 寬鬆）是只有 5 個月歷史時
    # 訂的，補完 126 個月之後回頭看，2.5 以下涵蓋 77% 的歷史——等於過去四分之三
    # 的月份都掛「資金相對寬鬆」，而那個標籤也就不再說明任何事。
    #
    # 「看現在落在自己歷史區間的哪裡」本來就是這個指標說明文字寫的用法，只是
    # 以前沒有歷史可以兌現。現在有了，就讓它真的照那句話判斷。
    #
    # 絕對值留著當備援：歷史不足 24 個月（例如從零重建資料）時百分位沒有意義。
    percentile = None
    if len(ratios) >= 24:
        percentile = round(sum(1 for r in ratios if r < last) / len(ratios) * 100)
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

    # 把「這個標籤是怎麼判的」寫在旁邊。門檻換算成當下的絕對值一起印出來，
    # 是因為「第 80 百分位」對讀的人來說不是一個可以拿去比對的數字。
    if percentile is not None:
        ordered = sorted(ratios)

        def at(p: int) -> float:
            i = (len(ordered) - 1) * p / 100
            lo, hi = int(i), min(int(i) + 1, len(ordered) - 1)
            return ordered[lo] + (ordered[hi] - ordered[lo]) * (i - lo)

        low = round(at(TW_MC_M1B_PCT_LOW), 2)
        high = round(at(TW_MC_M1B_PCT_HIGH), 2)
        zone_basis = (f"分區依歷史百分位："
                      f"≤P{TW_MC_M1B_PCT_LOW}（約 {low:.2f}）寬鬆、"
                      f"≥P{TW_MC_M1B_PCT_HIGH}（約 {high:.2f}）吃緊")
    else:
        low, high = TW_MC_M1B_LOW, TW_MC_M1B_HIGH
        zone_basis = f"參考區間（歷史不足，暫用固定值）：&lt;{low} 寬鬆、&gt;{high} 吃緊"

    cap_t = ratio_data["market_cap"][-1] / 1e6
    m1b_t = ratio_data["m1b"][-1] / 1e6

    # 這個指標的說明文字自己寫著：「用法是看現在落在自己歷史區間的哪裡，而不是
    # 看今天比昨天高還是低」。在只有 5 個月歷史的時候那句話沒辦法兌現；現在有
    # 十年了，就把它算出來放在旁邊——這是補歷史真正買到的東西。
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
      {vintage_note(dates[-1], behind, freq="月")}
      ｜總市值 {cap_t:,.1f} 兆元 ÷ M1B {m1b_t:,.1f} 兆元
      ｜{zone_basis}
      {span_txt}
    </div>
  </div>

  <div class="custom-legend" id="twMcM1bLegend"></div>
  <div class="chart-container short"><canvas id="twMcM1bChart"></canvas></div>
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
           pointRadius: mcDates.length > 90 ? 0 : (mcDates.length > 36 ? 1.5 : 3),
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
              const i = item.dataIndex;
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


# ---------------------------------------------------------------------------
# 美股：三大指數（重訂基期後放同一張圖比較）
# ---------------------------------------------------------------------------
def render_us_indices_section(indices):
    """
    三個指數放同一張圖。因為道瓊四萬多、S&P 六千多、NASDAQ 兩萬多，
    直接畫在同一個 y 軸上只會看到三條互不相干的線 —— 所以全部重訂基期成
    「區間起點 = 100」，比較的是相對漲跌幅。圖上會標明這件事，
    tooltip 裡同時顯示重訂基期後的值與真實收盤點數，不會讓人誤讀。
    """
    usable = [(k, d) for k, d in indices if d and d.get("dates")]
    if not usable:
        return "", ""

    # 對齊到共同交易日，否則三條線的 x 軸對不起來
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

        last, prev = raw[-1], raw[-2]
        pct = round((last - prev) / prev * 100, 2) if prev else 0
        _, tone_color = updown(last - prev)
        tone = "up" if last > prev else ("down" if last < prev else "")
        chips.append(chip(d.get("name") or key, f"{last:,.0f} ({pct:+.2f}%)", f"price {tone}".strip()))

    period_txt = f"{common_dates[0].replace('-', '/')} 起"
    html = f"""
  <div class="stat-box" style="margin-bottom:12px;">
    <div class="stat-label">相對走勢（{period_txt} = 100）</div>
    <div class="stat-sub">三個指數的點數量級差很多，直接疊圖看不出相對強弱，
      所以統一重訂基期。滑過圖表可同時看到重訂基期後的值與真實收盤點數。</div>
  </div>
  <div class="custom-legend" id="usIdxLegend"></div>
  <div class="chart-container"><canvas id="usIdxChart"></canvas></div>
  <div class="chart-source-box" title="資料來源與更新時間">
    📌 Yahoo Finance Chart API　｜　^DJI、^GSPC、^IXIC　｜　每日收盤
  </div>
"""

    script = f"""
  const usIdxDates = {json.dumps(common_dates, ensure_ascii=False)};
  const rawSeries = [];
  {' '.join(legend_bits)}
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
              const actual = raw ? raw[item.dataIndex] : null;
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
"""
    return html, script, chips


# ---------------------------------------------------------------------------
# 美股：四組經濟指標
# ---------------------------------------------------------------------------
def render_us_indicator_group(group, series_with_data):
    """
    一組指標一個 fin-grid。這裡刻意不畫圖：這一組裡的單位有 %、有千人、
    有指數，畫在同一張圖上沒有意義；分開畫十二張圖又會讓整份報告失焦。
    數值、變化、以及「這個數字是哪個月的」才是這一格真正要回答的事。
    """
    if not series_with_data:
        return ""

    boxes = []
    for meta, data in series_with_data:
        values, dates = data["close"], data["dates"]
        last = values[-1]
        prev = values[-2] if len(values) > 1 else last
        diff = last - prev
        pct = (diff / prev * 100) if prev else None
        # 小數位數跟著數值本身的量級走（與 fmt_indicator_value 同一套規則），
        # 免得出現「1,239.0 ▼ 176.00」這種一個一位、一個兩位的怪組合。
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
      <div class="fin-sub" style="font-size:10px;opacity:.75;">{fmt_period(dates[-1], meta.get('freq', ''))}
        {('｜' + unit) if unit else ''}</div>
    </div>""")

    tip_id = f"us{group['key'].title().replace('_', '')}Info"
    btn, popup = tip_button(tip_id, f"us_{group['key']}")
    return f"""
  <div class="title-row" style="margin-top:18px;">
    <div class="sub-title" style="margin:0;">{group['label']}</div>
    {btn}
  </div>
  {popup}
  <div class="fin-grid">{''.join(boxes)}</div>
"""


def render_us_overview_table():
    """核心指標速覽表：把上面四組壓成一頁，用來確認總體位置。"""
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
    """彙整所有區塊目前觸發的預警/布局機會，給頁首摘要欄用。"""
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
        # 這個指標本來就落後好幾個月，摘要列一定要把資料月份講出來，
        # 不然會被誤讀成「現在」的狀態
        stale_note = f"，資料月份 {month}" + (f"、落後 {behind} 個月" if behind else "")
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
            alerts.append(("warn", f"密大消費者信心指數 {last_mi:.1f}，落在「{zone_label}」區間（&lt;{MICHIGAN_WARN_THRESHOLD}）"))
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

        # 本益比布局判斷：用與個股卡片完全相同的 TTM PER 算法，確保兩邊數字一致
        per_threshold = JP_STOCK_PER_THRESHOLD.get(key)
        if per_threshold is not None and annual:
            latest_per = _latest_ttm_per(stock, annual)
            if latest_per is not None and latest_per < per_threshold:
                alerts.append(("buy", f"{name} 本益比 {latest_per:.1f} 倍，低於 {per_threshold:g} 倍布局參考"))
    return alerts


def render_page_header(alerts, taiex):
    now_disp = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")
    baseline_disp = taiex["dates"][-1].replace("-", "/") if taiex else "N/A"

    if alerts:
        items = "".join(
            f'<div>{"🔵" if kind == "buy" else "🔴"} <b>{"布局機會" if kind == "buy" else "風險預警"}：</b>{text}</div>'
            for kind, text in alerts
        )
        summary_html = f"""
  <div class="summary-box has-alerts">
    <div class="summary-title alert">🚨 本次報告有 {len(alerts)} 項指標觸發預警／布局參考</div>
    <div class="summary-list">{items}</div>
  </div>"""
    else:
        summary_html = """
  <div class="summary-box">
    <div class="summary-title ok">✅ 目前所有指標皆在正常區間，未觸發任何預警或布局參考線</div>
  </div>"""

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
    <button class="mode-toggle-btn" id="modeToggleBtn" onclick="toggleViewMode()">🖥️ 電腦版／📱 手機版</button>
  </div>
</div>
<div class="expand-all-bar">
  <button class="expand-btn" onclick="setAllCards(false)">全部展開</button>
  <button class="expand-btn" onclick="setInitialCardStates()">全部收合</button>
</div>
"""
    return header, summary_html


def build_html(taiex, vix, nikkei, michigan, murata, jp_stocks,
               tw_pmi=None, tw_mc_m1b=None, us_indices=None, us_fred=None):
    """五個大區塊，每一塊是一張可收合的卡片，各有自己的色系。

    兩層都預設收合：外層是五條橫幅，展開後裡面的卡片也還是收著的，
    要看哪一張再點哪一張。一次只攤開真正要看的東西。
    """
    scripts = []
    blocks = []
    us_indices = us_indices or []
    us_fred = us_fred or {}

    alerts = collect_alerts(taiex, vix, nikkei, michigan, murata, jp_stocks,
                            tw_pmi=tw_pmi, tw_mc_m1b=tw_mc_m1b)
    header_html, summary_html = render_page_header(alerts, taiex)

    # ── 一、重點摘要 ───────────────────────────────────────────────
    n_warn = sum(1 for kind, _ in alerts if kind == "warn")
    n_buy = len(alerts) - n_warn
    sum_chips = []
    if n_warn:
        sum_chips.append(chip("風險預警", f"{n_warn} 項", "warn"))
    if n_buy:
        sum_chips.append(chip("布局參考", f"{n_buy} 項", "buy"))
    if not alerts:
        sum_chips.append('<span class="chip">全部在正常區間</span>')
    blocks.append(block_card("summary", "重點摘要", "".join(sum_chips), summary_html))

    # ── 二、台股重要經濟指標 ──────────────────────────────────────
    tw_inner, tw_chips = [], []
    if taiex:
        t_html, t_script = render_taiex_section(taiex)
        tw_inner.append(t_html)
        scripts.append(t_script)
        tw_chips.append(chip("加權指數", f"{taiex['close'][-1]:,.0f}"))

    macro_tw_html, macro_tw_scripts = [], []
    if tw_pmi and tw_pmi.get("dates"):
        h, s = render_tw_pmi_section(tw_pmi)
        if h:
            macro_tw_html.append(h)
            macro_tw_scripts.append(s)
            last_pmi = next((v for v in reversed(tw_pmi["pmi"]) if v is not None), None)
            if last_pmi is not None:
                tw_chips.append(chip("製造業PMI", f"{last_pmi:.1f}",
                                     "buy" if last_pmi >= PMI_NEUTRAL else "warn"))
    if tw_mc_m1b and tw_mc_m1b.get("dates"):
        h, s = render_tw_marketcap_m1b_section(tw_mc_m1b)
        if h:
            macro_tw_html.append(h)
            macro_tw_scripts.append(s)
            r = tw_mc_m1b["ratio"][-1]
            tw_chips.append(chip("市值/M1B", f"{r:.2f}",
                                 "warn" if r >= TW_MC_M1B_HIGH else ""))
    if macro_tw_html:
        tw_inner.append(collapsible(
            "twmacro", "台股資金面與景氣領先指標", "", "".join(macro_tw_html)))
        scripts.append("".join(macro_tw_scripts))

    if tw_inner:
        blocks.append(block_card("tw", "台股重要經濟指標",
                                 "".join(tw_chips), "".join(tw_inner)))

    # ── 三、美股重要經濟指標 ──────────────────────────────────────
    us_inner, us_chips = [], []
    idx_result = render_us_indices_section(us_indices) if us_indices else None
    if idx_result:
        i_html, i_script, i_chips = idx_result
        if i_html:
            us_inner.append(collapsible("usidx", "美股三大指數", "".join(i_chips), i_html))
            scripts.append(i_script)

    # 四組指標。VIX 不走 FRED（用 CBOE 那份逐日的），所以在這裡手動併進
    # 「房地產與信心」那一組，讓它跟其他指標一起被一眼掃到。
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
            group_html.append(render_us_indicator_group(group, members))

    if group_html:
        group_html.append(render_us_overview_table())
        unrate = us_fred.get("UNRATE")
        cpi = us_fred.get("CPIAUCSL")
        if unrate and unrate.get("close"):
            us_chips.append(chip("失業率", f"{unrate['close'][-1]:.1f}%"))
        if cpi and len(cpi.get("close", [])) > 12:
            yoy = (cpi["close"][-1] / cpi["close"][-13] - 1) * 100
            us_chips.append(chip("CPI年增", f"{yoy:.1f}%"))
        us_inner.append(collapsible("usmacro", "美股經濟指標", "", "".join(group_html)))

    # VIX 與密大信心的細部圖表沿用既有區塊
    if vix or michigan:
        inner_html, inner_scripts, macro_chips = [], [], []
        if vix:
            h, s = render_vix_section(vix)
            inner_html.append(h); inner_scripts.append(s)
            v_last = vix["close"][-1]
            macro_chips.append(chip("VIX", f"{v_last:.1f}",
                                    "warn" if v_last > VIX_WARN_THRESHOLD else ""))
            us_chips.append(chip("VIX", f"{v_last:.1f}",
                                 "warn" if v_last > VIX_WARN_THRESHOLD else ""))
            if v_last > VIX_PANIC_THRESHOLD:
                macro_chips.append('<span class="chip warn solid">高度恐慌</span>')
            elif v_last > VIX_WARN_THRESHOLD:
                macro_chips.append('<span class="chip warn solid">波動升溫</span>')
        if michigan:
            h, s = render_michigan_section(michigan)
            inner_html.append(h); inner_scripts.append(s)
            m_last = michigan["close"][-1]
            m_warn = m_last < MICHIGAN_WARN_THRESHOLD
            macro_chips.append(chip("密大信心", f"{m_last:.1f}", "warn" if m_warn else ""))
            if m_warn:
                macro_chips.append('<span class="chip warn solid">衰退警戒</span>')

        us_inner.append(collapsible(
            "macro", "VIX 恐慌指數 ＆ 密大消費者信心",
            "".join(macro_chips), "".join(inner_html)))
        scripts.append("".join(inner_scripts))

    if us_inner:
        blocks.append(block_card("us", "美股重要經濟指標",
                                 "".join(us_chips), "".join(us_inner)))

    # ── 四、日股重要經濟指標 ──────────────────────────────────────
    jp_inner, jp_chips = [], []
    if nikkei:
        n_html, n_script = render_nikkei_section(nikkei)
        jp_inner.append(n_html)
        scripts.append(n_script)
        jp_chips.append(chip("日經225", f"{nikkei['close'][-1]:,.0f}"))
    if murata:
        mu_html, mu_script = render_murata_bb_section(murata)
        jp_inner.append(mu_html)
        scripts.append(mu_script)
        last_bb = murata["bb_ratio"][-1]
        jp_chips.append(chip("村田 B/B", f"{last_bb:.2f}",
                             "warn" if last_bb > MURATA_BB_WARN_THRESHOLD else ""))
    if jp_inner:
        blocks.append(block_card("jp", "日股重要經濟指標",
                                 "".join(jp_chips), "".join(jp_inner)))

    # ── 五、日股觀察（個股） ──────────────────────────────────────
    jp_html_list = []
    for key, stock, fin, quarterly, annual in jp_stocks:
        if not stock:
            continue
        a_html, a_script = render_jp_stock_section(stock, fin, key, quarterly, annual)
        jp_html_list.append(a_html)
        scripts.append(a_script)
    if jp_html_list:
        buy_hits = sum(1 for kind, text in alerts
                       if kind == "buy" and "布局參考線" in text)
        stock_chips = [chip("追蹤中", f"{len(jp_html_list)} 檔")]
        if buy_hits:
            stock_chips.append(chip("觸發布局", f"{buy_hits} 檔", "buy"))
        blocks.append(block_card(
            "jpstock", "日股觀察", "".join(stock_chips),
            f'<div class="jp-stock-grid">{"".join(jp_html_list)}</div>'))

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
{''.join(blocks)}
</div>

<script>
{SHARED_JS}
{''.join(scripts)}
</script>
<script>
  // 刻意放在獨立的 script 區塊：上面任何一張圖表若出錯（例如 CDN 沒載入），
  // 也不會連帶讓折疊、縮字、版型切換這些基本功能失效。
  applyViewMode('auto');   // 載入時不強制，交給響應式 CSS
  clearSavedCardStates();
  setInitialCardStates();  // 兩層全部收合
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

    # 台股新增的兩個總經指標
    tw_pmi = load_json("tw_pmi.json")
    tw_mc_m1b = load_json("tw_marketcap_m1b.json")

    # 美股三大指數與 FRED 指標，清單全部讀自 config.json
    us_indices = [(idx["key"], load_json(f"index_{idx['key']}.json")) for idx in US_INDEX_CONFIG]
    us_fred = {}
    for meta in US_FRED_CONFIG:
        cache = meta.get("cache") or f"fred_{meta['id'].lower()}.json"
        data = load_json(cache)
        if data:
            us_fred[meta["id"]] = data

    # 日本焦點個股清單：順序、啟用與否全部依 config.json 設定
    JP_STOCK_KEYS = [s["key"] for s in JP_STOCK_CONFIG]
    if not JP_STOCK_KEYS:
        print("⚠️ config.json 裡沒有任何啟用中的個股，本次報告不含個股區塊。")
    jp_stocks = []
    for key in JP_STOCK_KEYS:
        stock = load_json(f"stock_{key}.json")
        fin = load_json(f"stock_{key}_financials.json")
        quarterly = load_json(f"stock_{key}_quarterly_financials.json")
        annual = load_json(f"stock_{key}_quarterly_financials.json") or load_json(f"stock_{key}_annual_financials.json")
        if stock is None:
            print(f"⚠️ 找不到 data/stock_{key}.json，本次輸出會跳過這檔個股。")
        jp_stocks.append((key, stock, fin, quarterly, annual))

    for name, val in [("vix.json", vix), ("nikkei.json", nikkei), ("michigan.json", michigan),
                       ("murata_bb.json", murata), ("tw_pmi.json", tw_pmi),
                       ("tw_marketcap_m1b.json", tw_mc_m1b)]:
        if val is None:
            print(f"⚠️ 找不到 data/{name}，本次輸出會跳過對應區塊。")

    missing_idx = [k for k, v in us_indices if v is None]
    if missing_idx:
        print(f"⚠️ 找不到美股指數快取：{', '.join(missing_idx)}，本次報告會跳過這幾條線。")
    missing_fred = [m["id"] for m in US_FRED_CONFIG if m["id"] not in us_fred]
    if missing_fred:
        print(f"⚠️ 找不到 FRED 指標快取：{', '.join(missing_fred)}，本次報告不顯示這幾格。")

    html = build_html(taiex, vix, nikkei, michigan, murata, jp_stocks,
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
