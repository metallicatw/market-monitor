# -*- coding: utf-8 -*-
"""
每日全球市場與總經個股監控報告 — 純 GitHub Actions 自動化生成與 Email 發送腳本

【2026/08 全面重構版】改動重點：
1. 移除所有硬編碼假資料，改用 yfinance 抓取真實每日歷史數據（台股/VIX/日經/村田/7檔日股）
2. 密大消費者信心指數改用 FRED API（原規劃 investing.com 爬蟲因分頁限制無法一次取得完整歷史）
3. 村田 B/B Ratio 使用人工核實的 Excel Factbook + Murata IR 官方簡報資料（quarterly, 已驗證財年標籤對應）
4. 個股財務比率（PER/EPS/PBR/營益率）改用 yfinance（buffett-code.com 使用條款禁止自動化爬取）
5. 所有圖表新增 1D/5D/1M/3M/6M/YTD/1Y/3Y/5Y 範圍切換按鈕，預設 5Y，前端 JS 對真實日期資料切片，
   不補值、不插值、不製造假資料點
6. 台股加權指數新增成交量面板
7. 修正圖表來源列與 X 軸日期重疊的 CSS 問題

⚠️ 執行前置需求：
- pip install yfinance
- GitHub Secrets 需新增 FRED_API_KEY（免費申請：https://fred.stlouisfed.org/docs/api/api_key.html）
- 原有 GMAIL_USER / GMAIL_APP_PASSWORD 維持不變

⚠️ 已知限制：
- 台股加權指數成交金額（億元）yfinance 不提供，圖表僅呈現成交量（股數）替代，並於來源列註明
- 村田 B/B Ratio「主力MLCC」在 FY26 Q3/Q4 無公開資料，圖表上該兩點顯示為斷點（無資料），不編造數值
- 個股財務比率為即時快照值，非 buffett-code 式的逐季歷史時間序列
"""

import os
import sys
import json
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

_script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
sys.path.insert(0, os.path.join(_script_dir, 'pipeline'))
sys.path.insert(0, '/home/claude/work/pipeline')  # fallback for sandbox testing

from fetch_market_data import fetch_daily_history, get_latest_close, get_10day_avg_volume
from fetch_michigan_sentiment import fetch_michigan_sentiment, get_latest_reading
from fetch_financial_ratios import fetch_financial_ratios
from murata_bbr_data import MURATA_BBR_QUARTERS, MURATA_BBR_COMPANYWIDE, MURATA_BBR_CAPACITORS

# 真實資料時間範圍切片的 JS 邏輯（內嵌於腳本中，避免額外檔案依賴）
CORE_JS_HELPERS = r"""
function subtractDays(fromDate, days) { const d = new Date(fromDate); d.setDate(d.getDate() - days); return d; }
function subtractMonths(fromDate, months) { const d = new Date(fromDate); d.setMonth(d.getMonth() - months); return d; }
function subtractYears(fromDate, years) { const d = new Date(fromDate); d.setFullYear(d.getFullYear() - years); return d; }

// 依真實日期陣列切出時間範圍，不捏造任何資料點；範圍內交易日不足就照實顯示現有的
function sliceTimeframeReal(fullDates, fullValues, tf) {
  if (!fullDates || fullDates.length === 0) return { labels: [], data: [] };
  const latestDate = new Date(fullDates[fullDates.length - 1]);
  let cutoffDate;
  switch (tf) {
    case '1D':
      return { labels: [fullDates[fullDates.length - 1]], data: [fullValues[fullValues.length - 1]] };
    case '5D': cutoffDate = subtractDays(latestDate, 7); break;
    case '1M': cutoffDate = subtractMonths(latestDate, 1); break;
    case '3M': cutoffDate = subtractMonths(latestDate, 3); break;
    case '6M': cutoffDate = subtractMonths(latestDate, 6); break;
    case 'YTD': cutoffDate = new Date(latestDate.getFullYear(), 0, 1); break;
    case '1Y': cutoffDate = subtractYears(latestDate, 1); break;
    case '3Y': cutoffDate = subtractYears(latestDate, 3); break;
    case '5Y': default: cutoffDate = subtractYears(latestDate, 5); break;
  }
  const labels = [], data = [];
  for (let i = 0; i < fullDates.length; i++) {
    const d = new Date(fullDates[i]);
    if (d >= cutoffDate) { labels.push(fullDates[i]); data.push(fullValues[i]); }
  }
  return { labels, data };
}

// 依資料點數量動態決定 X 軸刻度上限，避免長天期(5Y)標籤重疊
function getMaxTicksForRange(labelCount) {
  if (labelCount <= 10) return labelCount;
  if (labelCount <= 30) return 8;
  if (labelCount <= 90) return 7;
  return 6;
}
"""

# ============================================================
# 警示門檻設定（維持原有數值）
# ============================================================
TAIEX_INDEX_ALERT = 38000
TAIEX_VOLUME_ALERT = 8000  # 億元 (yfinance 無法提供台股億元成交金額，此門檻暫無法自動判定)
VIX_ALERT = 20
MICH_LOW_ALERT = 60
MICH_HIGH_ALERT = 80
BBR_ALERT = 1.2
NIKKEI_ALERT = 56000

STOCKS = {
    "2802": {"ticker": "2802.T", "name": "味之素", "name_en": "Ajinomoto Co., Inc.", "warn_price": 4700, "num": 5},
    "8411": {"ticker": "8411.T", "name": "瑞穗金融集團", "name_en": "Mizuho Financial Group", "warn_price": 6000, "num": 6},
    "6506": {"ticker": "6506.T", "name": "安川電機", "name_en": "Yaskawa Electric Corporation", "warn_price": 4500, "num": 7},
    "5016": {"ticker": "5016.T", "name": "JX金屬", "name_en": "JX Advanced Metals Corporation", "warn_price": 3500, "num": 8},
    "5711": {"ticker": "5711.T", "name": "三菱材料", "name_en": "Mitsubishi Materials Corporation", "warn_price": 4000, "num": 9},
    "6501": {"ticker": "6501.T", "name": "日立製作所", "name_en": "Hitachi, Ltd.", "warn_price": 4800, "num": 10},
    "7012": {"ticker": "7012.T", "name": "川崎重工業", "name_en": "Kawasaki Heavy Industries, Ltd.", "warn_price": 2500, "num": 11},
}

print("=" * 60)
print("開始抓取真實市場資料...")
print("=" * 60)

# ============================================================
# 1. 抓取所有真實資料
# ============================================================
print("\n[1/5] 抓取台股加權指數...")
taiex_records = fetch_daily_history("^TWII", period="5y")

print("\n[2/5] 抓取 VIX 與密大消費者信心指數...")
vix_records = fetch_daily_history("^VIX", period="5y")
mich_records = fetch_michigan_sentiment(start_date="2020-01-01")

print("\n[3/5] 抓取日經225指數...")
nikkei_records = fetch_daily_history("^N225", period="5y")

print("\n[4/5] 抓取村田製作所股價...")
murata_price_records = fetch_daily_history("6981.T", period="5y")

print("\n[5/5] 抓取 7 檔日股個股資料...")
stock_data = {}
for code, meta in STOCKS.items():
    print(f"  -> {meta['name']} ({meta['ticker']})...")
    price_records = fetch_daily_history(meta["ticker"], period="5y")
    ratios = fetch_financial_ratios(meta["ticker"])
    stock_data[code] = {"price_records": price_records, "ratios": ratios}

print("\n" + "=" * 60)
print("資料抓取完成，開始產生報告...")
print("=" * 60)

# ============================================================
# 2. 資料整理與警示判定
# ============================================================
today_str = datetime.datetime.now().strftime('%Y/%m/%d')

taiex_available = bool(taiex_records)
taiex_dates = [r["date"] for r in taiex_records] if taiex_available else []
taiex_close = [r["close"] for r in taiex_records] if taiex_available else []
taiex_volume = [r["volume"] for r in taiex_records] if taiex_available else []
taiex_latest = get_latest_close(taiex_records) if taiex_available else None
taiex_prev = taiex_records[-2]["close"] if len(taiex_records) >= 2 else None
taiex_change = round(taiex_latest - taiex_prev, 2) if (taiex_latest and taiex_prev) else None
taiex_alert = (taiex_latest is not None) and (taiex_latest < TAIEX_INDEX_ALERT)

vix_available = bool(vix_records)
vix_dates = [r["date"] for r in vix_records] if vix_available else []
vix_values = [r["close"] for r in vix_records] if vix_available else []
vix_latest = get_latest_close(vix_records) if vix_available else None
vix_alert = (vix_latest is not None) and (vix_latest > VIX_ALERT)

mich_available = bool(mich_records)
mich_dates = [r["date"] for r in mich_records] if mich_available else []
mich_values = [r["value"] for r in mich_records] if mich_available else []
mich_latest = get_latest_reading(mich_records) if mich_available else None
mich_alert = (mich_latest is not None) and (mich_latest < MICH_LOW_ALERT or mich_latest > MICH_HIGH_ALERT)

nikkei_available = bool(nikkei_records)
nikkei_dates = [r["date"] for r in nikkei_records] if nikkei_available else []
nikkei_values = [r["close"] for r in nikkei_records] if nikkei_available else []
nikkei_latest = get_latest_close(nikkei_records) if nikkei_available else None
nikkei_prev = nikkei_records[-2]["close"] if len(nikkei_records) >= 2 else None
nikkei_change = round(nikkei_latest - nikkei_prev, 2) if (nikkei_latest and nikkei_prev) else None
nikkei_alert = (nikkei_latest is not None) and (nikkei_latest < NIKKEI_ALERT)

murata_price_available = bool(murata_price_records)
murata_price_dates = [r["date"] for r in murata_price_records] if murata_price_available else []
murata_price_values = [r["close"] for r in murata_price_records] if murata_price_available else []

bbr_latest_companywide = MURATA_BBR_COMPANYWIDE[-1]
bbr_latest_capacitors = next((v for v in reversed(MURATA_BBR_CAPACITORS) if v is not None), None)
bbr_alert = bbr_latest_companywide > BBR_ALERT

# 動態產生預警訊息（取代原本寫死的假警示文字）
alert_messages = []
if mich_alert and mich_available:
    direction = "低於" if mich_latest < MICH_LOW_ALERT else "超過"
    threshold = MICH_LOW_ALERT if mich_latest < MICH_LOW_ALERT else MICH_HIGH_ALERT
    alert_messages.append(
        f"<strong>美國密西根大學消費者信心指數</strong>：最新公布值為 <strong>{mich_latest:.1f}</strong>"
        f"（{direction}警戒門檻 <strong>{threshold}</strong>）。"
    )
if bbr_alert:
    alert_messages.append(
        f"<strong>日本村田製作所 B/B Ratio</strong>：最新數值為 <strong>{bbr_latest_companywide:.2f}</strong>"
        f"{f'（主力 MLCC {bbr_latest_capacitors:.2f}）' if bbr_latest_capacitors is not None else ''}"
        f"，突破 <strong>{BBR_ALERT}</strong> 警戒線。"
    )
if taiex_alert:
    alert_messages.append(f"<strong>台股加權指數</strong>：最新收盤 <strong>{taiex_latest:,.2f}</strong>，低於警戒門檻 <strong>{TAIEX_INDEX_ALERT:,}</strong> 點。")
if vix_alert:
    alert_messages.append(f"<strong>CBOE VIX 恐慌指數</strong>：最新值 <strong>{vix_latest:.2f}</strong>，超過警戒門檻 <strong>{VIX_ALERT}</strong>。")
if nikkei_alert:
    alert_messages.append(f"<strong>日經225指數</strong>：最新收盤 <strong>{nikkei_latest:,.2f}</strong>，低於警戒門檻 <strong>{NIKKEI_ALERT:,}</strong> 點。")

for code, meta in STOCKS.items():
    sd = stock_data[code]
    if sd["price_records"]:
        latest = sd["price_records"][-1]["close"]
        if latest < meta["warn_price"]:
            alert_messages.append(f"<strong>{meta['name']} ({code}.JP)</strong>：最新股價 <strong>{latest:,.1f}</strong> 日圓，已跌破買進門檻 <strong>{meta['warn_price']:,}</strong> 日圓。")

if not alert_messages:
    alert_messages.append("目前所有監控指標均未觸發預警門檻。")

alert_html_items = "<br>\n          ".join(
    f"{i+1}. {msg}" for i, msg in enumerate(alert_messages)
)

print(f"\n預警項目數: {len(alert_messages) if alert_messages[0] != '目前所有監控指標均未觸發預警門檻。' else 0}")
# ============================================================
# 3. HTML 樣板：CSS（含來源列與 X 軸重疊修正）
# ============================================================
HTML_HEAD = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日全球市場與總經個股監控報告</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {{
    --bg-main: #0a0f1a; --bg-card: #111827; --border-color: #1f2937;
    --text-main: #e5e7eb; --text-muted: #94a3b8;
    --accent-green: #10b981; --accent-red: #ef4444; --accent-amber: #f59e0b;
    --accent-blue: #3b82f6; --accent-purple: #8b5cf6;
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--bg-main); color: var(--text-main); font-family: -apple-system, "Noto Sans TC", sans-serif; margin: 0; padding: 20px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  .view-switcher {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .view-btn {{ padding: 6px 14px; border-radius: 6px; border: 1px solid var(--border-color); background: var(--bg-card); color: var(--text-muted); cursor: pointer; font-size: 12px; }}
  .view-btn.active {{ background: var(--accent-blue); color: #fff; border-color: var(--accent-blue); }}
  header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .subtitle {{ font-size: 12px; color: var(--text-muted); }}
  .badge {{ padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
  .badge-normal {{ background: rgba(16, 185, 129, 0.15); color: var(--accent-green); }}
  .badge-warning {{ background: rgba(239, 68, 68, 0.15); color: var(--accent-red); }}
  .badge-nobuy {{ background: rgba(239, 68, 68, 0.15); color: var(--accent-red); }}
  .alert-banner {{ background: rgba(127, 29, 29, 0.25); border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 10px; padding: 14px 16px; margin-bottom: 20px; display: flex; gap: 12px; align-items: flex-start; }}
  .alert-tag {{ background: var(--accent-red); color: #fff; font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 4px; white-space: nowrap; }}
  .section-card {{ background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 18px; margin-bottom: 18px; }}
  .section-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }}
  .section-title {{ font-size: 16px; font-weight: 700; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }}
  .stat-box {{ background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px 14px; }}
  .stat-label {{ font-size: 11.5px; color: var(--text-muted); margin-bottom: 4px; }}
  .stat-value {{ font-size: 20px; font-weight: 700; }}
  .stat-sub {{ font-size: 11px; color: var(--text-muted); margin-top: 4px; }}
  .timeframe-bar {{ display: flex; align-items: center; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; }}
  .tf-btn {{ padding: 4px 10px; border-radius: 5px; border: 1px solid var(--border-color); background: transparent; color: var(--text-muted); cursor: pointer; font-size: 11px; font-weight: 600; }}
  .tf-btn.active {{ background: var(--accent-blue); color: #fff; border-color: var(--accent-blue); }}
  .tf-btn:hover {{ border-color: var(--accent-blue); }}

  /* ==== 圖表容器：修正來源列與 X 軸重疊 (原問題：margin-top 不足，圖表底部與來源列文字互相覆蓋) ==== */
  .chart-container {{ position: relative; width: 100%; height: 300px; margin-top: 8px; margin-bottom: 8px; }}
  .chart-source-box {{
    margin-top: 44px;               /* 原本 36px 不足，加大間距確保不與 X 軸刻度重疊 */
    padding: 7px 10px;
    background: rgba(15, 23, 42, 0.5);
    border-radius: 6px;
    border: 1px solid var(--border-color);
    font-size: 10.5px;
    color: var(--text-muted);
    white-space: nowrap;             /* 強制單行，不換行造成版面跑掉 */
    overflow: hidden;
    text-overflow: ellipsis;         /* 過長時以省略號截斷，而非擠壓變形 */
  }}
  .chart-source-box strong {{ color: #94a3b8; white-space: nowrap; }}
  .chart-source-box a {{ color: #38bdf8 !important; text-decoration: underline !important; font-weight: 500; margin: 0 2px; white-space: nowrap; }}

  .custom-legend {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 6px; font-size: 11px; }}
  .legend-item {{ display: flex; align-items: center; gap: 4px; cursor: pointer; }}
  .legend-dot {{ width: 9px; height: 9px; border-radius: 2px; }}
  .stock-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
  .table-container {{ overflow-x: auto; margin-bottom: 10px; }}
  table.stock-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  table.stock-table th {{ text-align: center; padding: 6px 4px; color: var(--text-muted); font-weight: 600; border-bottom: 1px solid var(--border-color); font-size: 10.5px; }}
  table.stock-table td {{ text-align: center; padding: 6px 4px; border-bottom: 1px solid rgba(31, 41, 55, 0.5); }}

  @media (max-width: 768px) {{
    .stock-grid {{ grid-template-columns: 1fr; }}
    .grid-2 {{ grid-template-columns: 1fr; }}
    .chart-container {{ height: 230px !important; margin-bottom: 6px; }}
    .chart-source-box {{ font-size: 9px; padding: 6px 8px; margin-top: 34px; }}
  }}
  body.force-mobile .stock-grid {{ grid-template-columns: 1fr; }}
  body.force-mobile .grid-2 {{ grid-template-columns: 1fr; }}
  body.force-mobile .chart-container {{ height: 230px !important; margin-bottom: 6px; }}
  body.force-mobile .chart-source-box {{ font-size: 9px; padding: 6px 8px; margin-top: 34px; }}
  body.force-mobile table.stock-table th, body.force-mobile table.stock-table td {{ padding: 5px 1px; }}
</style>
</head>
<body>
<div class="container">
  <div class="view-switcher">
    <button class="view-btn active" id="btnDesktop" onclick="setViewMode('desktop')">🖥️ 電腦版 (寬螢幕)</button>
    <button class="view-btn" id="btnMobile" onclick="setViewMode('mobile')">📱 手機版 (最佳化)</button>
  </div>

  <header>
    <div>
      <h1>每日全球市場與總經個股監控報告</h1>
      <div class="subtitle">報告資料基準：{today_str} ｜ 真實每日歷史數據，無平滑化、無補值</div>
    </div>
    <div><span class="badge badge-normal">排程自動化運行</span></div>
  </header>

  <div class="alert-banner">
    <span class="alert-tag">預警通知</span>
    <div>
      <div style="font-size: 14px; font-weight: 700; color: #f87171; margin-bottom: 4px;">🚨 本日達到預警標準之指標項目：</div>
      <div style="font-size: 12.5px; color: #fecaca; line-height: 1.6;">
          {alert_html_items}
      </div>
    </div>
  </div>
"""

# ============================================================
# 4. JS 共用函式（Chart.js 通用設定 + 真實資料時間範圍切片）
# ============================================================
JS_COMMON_HELPERS = """
<script>
  const chartStore = {};
  const commonTooltip = {
    backgroundColor: 'rgba(17, 24, 39, 0.95)', titleColor: '#e5e7eb', bodyColor: '#e5e7eb',
    borderColor: '#374151', borderWidth: 1, padding: 10, displayColors: true
  };

  function buildCustomLegend(canvasId, chart) {
    const canvas = document.getElementById(canvasId);
    const container = document.createElement('div');
    container.className = 'custom-legend';
    chart.data.datasets.forEach((ds, i) => {
      const item = document.createElement('div');
      item.className = 'legend-item';
      item.innerHTML = `<span class="legend-dot" style="background:${ds.borderColor}"></span><span>${ds.label}</span>`;
      item.onclick = () => {
        const meta = chart.getDatasetMeta(i);
        meta.hidden = meta.hidden === null ? !chart.data.datasets[i].hidden : !meta.hidden;
        chart.update();
        item.style.opacity = meta.hidden ? 0.4 : 1;
      };
      container.appendChild(item);
    });
    canvas.parentElement.insertBefore(container, canvas.parentElement.firstChild);
  }

  function setViewMode(mode) {
    document.body.classList.toggle('force-mobile', mode === 'mobile');
    document.getElementById('btnDesktop').classList.toggle('active', mode === 'desktop');
    document.getElementById('btnMobile').classList.toggle('active', mode === 'mobile');
    Object.values(chartStore).forEach(c => c.resize());
  }
""" + CORE_JS_HELPERS + """
</script>
"""

print("HTML/CSS 樣板已產生（含來源列重疊修正）")
# ============================================================
# 5. 各區塊 HTML + JS 組裝
# ============================================================

# ---- 1. 台股加權指數 ----
taiex_change_color = "var(--accent-green)" if (taiex_change or 0) >= 0 else "var(--accent-red)"
taiex_change_sign = "+" if (taiex_change or 0) >= 0 else ""
avg_vol_10d = get_10day_avg_volume(taiex_records) if taiex_available else None

if taiex_available:
    taiex_stat_html = f"""
      <div class="grid-2">
        <div class="stat-box" style="border-color: {'var(--accent-red)' if taiex_alert else 'var(--border-color)'};">
          <div class="stat-label">最新加權指數 ({taiex_dates[-1]} 收盤)</div>
          <div class="stat-value" style="color: var(--accent-green);">{taiex_latest:,.2f}
            <span style="font-size: 13.5px; color: {taiex_change_color};">({taiex_change_sign}{taiex_change:,.2f})</span></div>
          <div class="stat-sub">警示門檻：&lt; {TAIEX_INDEX_ALERT:,} 點 ｜ {'🚨 觸發預警' if taiex_alert else '未達預警'}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">10日平均成交量 (股數，非億元)</div>
          <div class="stat-value">{f"{avg_vol_10d:,.0f}" if avg_vol_10d else '無資料'}</div>
          <div class="stat-sub">⚠️ yfinance 不提供台股億元成交金額，此處為股數成交量替代指標</div>
        </div>
      </div>
    """
else:
    taiex_stat_html = """
      <div class="stat-box" style="border-color: var(--accent-red);">
        <div class="stat-label">台股加權指數</div>
        <div class="stat-value" style="color: var(--text-muted);">⚠️ 資料抓取失敗</div>
        <div class="stat-sub">yfinance 無法取得 ^TWII 資料，請檢查網路連線或 GitHub Actions log</div>
      </div>
    """

TAIEX_SECTION_HTML = f"""
    <div class="section-card">
      <div class="section-header">
        <div class="section-title">1. 台股加權指數與成交量 (TAIEX)</div>
        <span class="badge {'badge-warning' if taiex_alert else 'badge-normal'}">{'觸發預警' if taiex_alert else '未達預警門檻'}</span>
      </div>
      {taiex_stat_html}
      <div class="timeframe-bar">
        <span style="font-size: 11px; color: #64748b; margin-right: 2px;">週期切換:</span>
        <button class="tf-btn" onclick="updateTaiexTimeframe('1D', this)">1D</button>
        <button class="tf-btn" onclick="updateTaiexTimeframe('5D', this)">5D</button>
        <button class="tf-btn" onclick="updateTaiexTimeframe('1M', this)">1M</button>
        <button class="tf-btn" onclick="updateTaiexTimeframe('3M', this)">3M</button>
        <button class="tf-btn" onclick="updateTaiexTimeframe('6M', this)">6M</button>
        <button class="tf-btn" onclick="updateTaiexTimeframe('YTD', this)">YTD</button>
        <button class="tf-btn" onclick="updateTaiexTimeframe('1Y', this)">1Y</button>
        <button class="tf-btn" onclick="updateTaiexTimeframe('3Y', this)">3Y</button>
        <button class="tf-btn active" onclick="updateTaiexTimeframe('5Y', this)">5Y</button>
      </div>
      <div class="chart-container"><canvas id="taiexChart"></canvas></div>
      <div class="chart-source-box">
        <strong>📌 資料來源：</strong>
        <a href="https://finance.yahoo.com/quote/%5ETWII" target="_blank">Yahoo Finance (^TWII)</a> ｜
        <a href="https://www.twse.com.tw/zh/trading/historical/fmtqik.html" target="_blank">臺灣證券交易所 (TWSE)</a>
      </div>
    </div>
"""

TAIEX_CHART_JS = "" if not taiex_available else f"""
  const taiexDatesReal = {json.dumps(taiex_dates)};
  const taiexCloseReal = {json.dumps(taiex_close)};
  const taiexVolumeReal = {json.dumps(taiex_volume)};
  chartStore['taiex'] = new Chart(document.getElementById('taiexChart'), {{
    type: 'line', data: {{ labels: taiexDatesReal, datasets: [
      {{ label: '台股加權指數', data: taiexCloseReal, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.1)', fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4, yAxisID: 'y' }},
      {{ label: '{TAIEX_INDEX_ALERT:,} 點警示線', data: Array(taiexDatesReal.length).fill({TAIEX_INDEX_ALERT}), borderColor: '#ef4444', borderDash: [5,5], borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'y' }},
      {{ label: '成交量(股數)', data: taiexVolumeReal, type: 'bar', backgroundColor: 'rgba(59,130,246,0.4)', borderRadius: 1, yAxisID: 'yVol' }}
    ]}},
    options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ tooltip: commonTooltip, legend: {{ display: false }} }},
      scales: {{
        x: {{ ticks: {{ font: {{ size: 9 }}, color: '#94a3b8', maxTicksLimit: getMaxTicksForRange(taiexDatesReal.length), maxRotation: 0 }}, grid: {{ color: 'rgba(38,51,77,0.4)' }} }},
        y: {{ type: 'linear', position: 'left', title: {{ display: true, text: '加權指數(點)', font: {{ size: 9.5 }} }} }},
        yVol: {{ type: 'linear', position: 'right', grid: {{ drawOnChartArea: false }}, title: {{ display: true, text: '成交量(股數)', font: {{ size: 9.5 }} }} }}
      }} }}
  }});
  buildCustomLegend('taiexChart', chartStore['taiex']);
  function updateTaiexTimeframe(tf, btnEl) {{
    btnEl.parentElement.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
    btnEl.classList.add('active');
    const c = sliceTimeframeReal(taiexDatesReal, taiexCloseReal, tf);
    const v = sliceTimeframeReal(taiexDatesReal, taiexVolumeReal, tf);
    const chart = chartStore['taiex'];
    chart.data.labels = c.labels; chart.data.datasets[0].data = c.data;
    chart.data.datasets[1].data = Array(c.labels.length).fill({TAIEX_INDEX_ALERT});
    chart.data.datasets[2].data = v.data;
    chart.options.scales.x.ticks.maxTicksLimit = getMaxTicksForRange(c.labels.length);
    chart.update();
  }}
  window.updateTaiexTimeframe = updateTaiexTimeframe;
"""

# ---- 2. VIX + 密大信心 ----
vix_stat = (f'<div class="stat-value" style="color: var(--accent-red);">{vix_latest:.2f}</div>'
            f'<div class="stat-sub">門檻：&gt; {VIX_ALERT} ｜ {"🚨 觸發預警" if vix_alert else "安全"}</div>') if vix_available else \
           '<div class="stat-value" style="color: var(--text-muted);">⚠️ 資料抓取失敗</div>'
mich_stat = (f'<div class="stat-value" style="color: var(--accent-blue);">{mich_latest:.1f}</div>'
             f'<div class="stat-sub">門檻：&lt;{MICH_LOW_ALERT} 或 &gt;{MICH_HIGH_ALERT} ｜ {"🚨 觸發預警" if mich_alert else "安全"} ({mich_dates[-1] if mich_dates else ""})</div>') if mich_available else \
            '<div class="stat-value" style="color: var(--text-muted);">⚠️ 資料抓取失敗</div><div class="stat-sub">需設定 FRED_API_KEY</div>'

VIX_MICH_SECTION_HTML = f"""
    <div class="section-card">
      <div class="section-header">
        <div class="section-title">2. VIX恐慌指數 與 密西根大學消費者信心指數</div>
        <span class="badge {'badge-warning' if (vix_alert or mich_alert) else 'badge-normal'}">{'觸發預警' if (vix_alert or mich_alert) else '未達預警門檻'}</span>
      </div>
      <div class="grid-2">
        <div class="stat-box" style="border-color: {'var(--accent-red)' if vix_alert else 'var(--border-color)'};">
          <div class="stat-label">CBOE VIX 恐慌指數</div>{vix_stat}
        </div>
        <div class="stat-box" style="border-color: {'var(--accent-red)' if mich_alert else 'var(--border-color)'};">
          <div class="stat-label">密西根大學消費者信心指數</div>{mich_stat}
        </div>
      </div>
      <div class="timeframe-bar">
        <span style="font-size: 11px; color: #64748b; margin-right: 2px;">週期切換:</span>
        <button class="tf-btn" onclick="updateUsTimeframe('1M', this)">1M</button>
        <button class="tf-btn" onclick="updateUsTimeframe('3M', this)">3M</button>
        <button class="tf-btn" onclick="updateUsTimeframe('6M', this)">6M</button>
        <button class="tf-btn" onclick="updateUsTimeframe('YTD', this)">YTD</button>
        <button class="tf-btn" onclick="updateUsTimeframe('1Y', this)">1Y</button>
        <button class="tf-btn" onclick="updateUsTimeframe('3Y', this)">3Y</button>
        <button class="tf-btn active" onclick="updateUsTimeframe('5Y', this)">5Y</button>
      </div>
      <div class="chart-container"><canvas id="usIndicatorsChart"></canvas></div>
      <div class="chart-source-box">
        <strong>📌 資料來源：</strong>
        <a href="https://finance.yahoo.com/quote/%5EVIX" target="_blank">Yahoo Finance (^VIX)</a> ｜
        <a href="https://fred.stlouisfed.org/series/UMCSENT" target="_blank">FRED (UMCSENT)</a>
      </div>
    </div>
"""

VIX_MICH_CHART_JS = "" if not (vix_available or mich_available) else f"""
  const vixDatesReal = {json.dumps(vix_dates)};
  const vixValuesReal = {json.dumps(vix_values)};
  const michDatesReal = {json.dumps(mich_dates)};
  const michValuesReal = {json.dumps(mich_values)};
  function alignMonthlyToDaily(dailyDates, monthlyDates, monthlyValues) {{
    const result = []; let mIdx = -1;
    for (let i = 0; i < dailyDates.length; i++) {{
      const dDate = dailyDates[i];
      while (mIdx + 1 < monthlyDates.length && monthlyDates[mIdx + 1] <= dDate) mIdx++;
      result.push(mIdx >= 0 ? monthlyValues[mIdx] : null);
    }}
    return result;
  }}
  const michAlignedToVixDates = (vixDatesReal.length > 0) ? alignMonthlyToDaily(vixDatesReal, michDatesReal, michValuesReal) : [];
  const usBaseDates = vixDatesReal.length > 0 ? vixDatesReal : michDatesReal;
  chartStore['us'] = new Chart(document.getElementById('usIndicatorsChart'), {{
    type: 'line', data: {{ labels: usBaseDates, datasets: [
      {{ label: 'VIX恐慌指數', data: vixValuesReal, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.1)', yAxisID: 'yVix', tension: 0, pointRadius: 0, pointHoverRadius: 4, spanGaps: false }},
      {{ label: 'VIX {VIX_ALERT} 警示線', data: Array(usBaseDates.length).fill({VIX_ALERT}), borderColor: '#f87171', borderDash: [5,5], borderWidth: 1.5, yAxisID: 'yVix', pointRadius: 0, fill: false }},
      {{ label: '密大消費者信心', data: michAlignedToVixDates.length > 0 ? michAlignedToVixDates : michValuesReal, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', yAxisID: 'yMich', tension: 0, pointRadius: 0, pointHoverRadius: 4, spanGaps: false }},
      {{ label: '信心{MICH_LOW_ALERT}警示', data: Array(usBaseDates.length).fill({MICH_LOW_ALERT}), borderColor: '#60a5fa', borderDash: [5,5], borderWidth: 1.5, yAxisID: 'yMich', pointRadius: 0, fill: false }},
      {{ label: '信心{MICH_HIGH_ALERT}警示', data: Array(usBaseDates.length).fill({MICH_HIGH_ALERT}), borderColor: '#93c5fd', borderDash: [5,5], borderWidth: 1.5, yAxisID: 'yMich', pointRadius: 0, fill: false }}
    ]}},
    options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ tooltip: commonTooltip, legend: {{ display: false }} }},
      scales: {{
        x: {{ ticks: {{ font: {{ size: 9 }}, color: '#94a3b8', maxTicksLimit: getMaxTicksForRange(usBaseDates.length), maxRotation: 0 }}, grid: {{ color: 'rgba(38,51,77,0.4)' }} }},
        yVix: {{ type: 'linear', position: 'left', title: {{ display: true, text: 'VIX', color: '#ef4444', font: {{ size: 9.5 }} }}, ticks: {{ color: '#ef4444' }} }},
        yMich: {{ type: 'linear', position: 'right', title: {{ display: true, text: '消費者信心', color: '#3b82f6', font: {{ size: 9.5 }} }}, ticks: {{ color: '#3b82f6' }}, grid: {{ drawOnChartArea: false }} }}
      }} }}
  }});
  buildCustomLegend('usIndicatorsChart', chartStore['us']);
  function updateUsTimeframe(tf, btnEl) {{
    btnEl.parentElement.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
    btnEl.classList.add('active');
    const vixRes = sliceTimeframeReal(usBaseDates, vixValuesReal.length > 0 ? vixValuesReal : usBaseDates.map(()=>null), tf);
    const michRes = sliceTimeframeReal(usBaseDates, michAlignedToVixDates.length > 0 ? michAlignedToVixDates : usBaseDates.map(()=>null), tf);
    const chart = chartStore['us'];
    chart.data.labels = vixRes.labels; chart.data.datasets[0].data = vixRes.data;
    chart.data.datasets[1].data = Array(vixRes.labels.length).fill({VIX_ALERT});
    chart.data.datasets[2].data = michRes.data;
    chart.data.datasets[3].data = Array(vixRes.labels.length).fill({MICH_LOW_ALERT});
    chart.data.datasets[4].data = Array(vixRes.labels.length).fill({MICH_HIGH_ALERT});
    chart.options.scales.x.ticks.maxTicksLimit = getMaxTicksForRange(vixRes.labels.length);
    chart.update();
  }}
  window.updateUsTimeframe = updateUsTimeframe;
"""
print("Part 3 (TAIEX + VIX/Michigan) 組裝完成")
# ---- 3. 日經225 ----
nikkei_change_color = "var(--accent-green)" if (nikkei_change or 0) >= 0 else "var(--accent-red)"
nikkei_change_sign = "+" if (nikkei_change or 0) >= 0 else ""

nikkei_stat_html = f"""
  <div class="stat-box" style="border-color: {'var(--accent-red)' if nikkei_alert else 'var(--border-color)'};">
    <div class="stat-label">最新收盤點位 ({nikkei_dates[-1] if nikkei_available else ''})</div>
    <div class="stat-value" style="color: var(--accent-green);">{f"{nikkei_latest:,.2f}" if nikkei_available else '⚠️ 資料抓取失敗'}
      {f'<span style="font-size:13.5px;color:{nikkei_change_color};">({nikkei_change_sign}{nikkei_change:,.2f})</span>' if nikkei_available and nikkei_change is not None else ''}</div>
    <div class="stat-sub">警示門檻：&lt; {NIKKEI_ALERT:,} 點 ｜ {'🚨 觸發預警' if nikkei_alert else '未達預警'}</div>
  </div>
""" if nikkei_available else """
  <div class="stat-box" style="border-color: var(--accent-red);">
    <div class="stat-label">日經225指數</div>
    <div class="stat-value" style="color: var(--text-muted);">⚠️ 資料抓取失敗</div>
  </div>
"""

NIKKEI_SECTION_HTML = f"""
    <div class="section-card">
      <div class="section-header">
        <div class="section-title">3. 日經225指數 (Nikkei 225)</div>
        <span class="badge {'badge-warning' if nikkei_alert else 'badge-normal'}">{'觸發預警' if nikkei_alert else '未達預警門檻'}</span>
      </div>
      {nikkei_stat_html}
      <div class="timeframe-bar">
        <span style="font-size: 11px; color: #64748b; margin-right: 2px;">週期切換:</span>
        <button class="tf-btn" onclick="updateNikkeiTimeframe('1D', this)">1D</button>
        <button class="tf-btn" onclick="updateNikkeiTimeframe('5D', this)">5D</button>
        <button class="tf-btn" onclick="updateNikkeiTimeframe('1M', this)">1M</button>
        <button class="tf-btn" onclick="updateNikkeiTimeframe('3M', this)">3M</button>
        <button class="tf-btn" onclick="updateNikkeiTimeframe('6M', this)">6M</button>
        <button class="tf-btn" onclick="updateNikkeiTimeframe('YTD', this)">YTD</button>
        <button class="tf-btn" onclick="updateNikkeiTimeframe('1Y', this)">1Y</button>
        <button class="tf-btn" onclick="updateNikkeiTimeframe('3Y', this)">3Y</button>
        <button class="tf-btn active" onclick="updateNikkeiTimeframe('5Y', this)">5Y</button>
      </div>
      <div class="chart-container"><canvas id="nikkeiChart"></canvas></div>
      <div class="chart-source-box">
        <strong>📌 資料來源：</strong>
        <a href="https://finance.yahoo.com/quote/%5EN225" target="_blank">Yahoo Finance (^N225)</a>
      </div>
    </div>
"""

NIKKEI_CHART_JS = "" if not nikkei_available else f"""
  const nikkeiDatesReal = {json.dumps(nikkei_dates)};
  const nikkeiValuesReal = {json.dumps(nikkei_values)};
  chartStore['nikkei'] = new Chart(document.getElementById('nikkeiChart'), {{
    type: 'line', data: {{ labels: nikkeiDatesReal, datasets: [
      {{ label: '日經225指數', data: nikkeiValuesReal, borderColor: '#06b6d4', backgroundColor: 'rgba(6,182,212,0.1)', fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4 }},
      {{ label: '{NIKKEI_ALERT:,} 點警示線', data: Array(nikkeiDatesReal.length).fill({NIKKEI_ALERT}), borderColor: '#f59e0b', borderDash: [5,5], borderWidth: 1.5, pointRadius: 0, fill: false }}
    ]}},
    options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ tooltip: commonTooltip, legend: {{ display: false }} }},
      scales: {{ x: {{ ticks: {{ font: {{ size: 9 }}, color: '#94a3b8', maxTicksLimit: getMaxTicksForRange(nikkeiDatesReal.length), maxRotation: 0 }}, grid: {{ color: 'rgba(38,51,77,0.4)' }} }},
                 y: {{ title: {{ display: true, text: '日經指數(點)', font: {{ size: 9.5 }} }} }} }} }}
  }});
  buildCustomLegend('nikkeiChart', chartStore['nikkei']);
  function updateNikkeiTimeframe(tf, btnEl) {{
    btnEl.parentElement.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
    btnEl.classList.add('active');
    const res = sliceTimeframeReal(nikkeiDatesReal, nikkeiValuesReal, tf);
    const chart = chartStore['nikkei'];
    chart.data.labels = res.labels; chart.data.datasets[0].data = res.data;
    chart.data.datasets[1].data = Array(res.labels.length).fill({NIKKEI_ALERT});
    chart.options.scales.x.ticks.maxTicksLimit = getMaxTicksForRange(res.labels.length);
    chart.update();
  }}
  window.updateNikkeiTimeframe = updateNikkeiTimeframe;
"""

# ---- 4. 村田製作所 ----
MURATA_SECTION_HTML = f"""
    <div class="section-card">
      <div class="section-header">
        <div class="section-title">4. 村田製作所 B/B Ratio 與股價 (6981.JP)</div>
        <span class="badge {'badge-warning' if bbr_alert else 'badge-normal'}">{'最新 ' + f'{bbr_latest_companywide:.2f}' + ' 超過 ' + str(BBR_ALERT) + ' 警示線' if bbr_alert else '未達預警門檻'}</span>
      </div>
      <div class="grid-2">
        <div class="stat-box" style="border-color: {'var(--accent-red)' if bbr_alert else 'var(--border-color)'};">
          <div class="stat-label">最新全公司綜合 B/B Ratio ({MURATA_BBR_QUARTERS[-1]})</div>
          <div class="stat-value" style="color: var(--accent-amber);">{bbr_latest_companywide:.2f}</div>
          <div class="stat-sub">門檻：&gt; {BBR_ALERT} ｜ {'🚨 觸發預警' if bbr_alert else '安全'}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">主力 MLCC (コンデンサ) B/B Ratio</div>
          <div class="stat-value" style="color: var(--accent-purple);">{f"{bbr_latest_capacitors:.2f}" if bbr_latest_capacitors is not None else '⚠️ 無資料'}</div>
          <div class="stat-sub">資料來源：Excel Factbook + Murata IR 決算說明會簡報（人工核實）</div>
        </div>
      </div>

      <h4 style="font-size: 13px; color: var(--text-muted); margin: 14px 0 6px;">村田股價走勢</h4>
      <div class="timeframe-bar">
        <button class="tf-btn" onclick="updateMurataPriceTimeframe('1D', this)">1D</button>
        <button class="tf-btn" onclick="updateMurataPriceTimeframe('5D', this)">5D</button>
        <button class="tf-btn" onclick="updateMurataPriceTimeframe('1M', this)">1M</button>
        <button class="tf-btn" onclick="updateMurataPriceTimeframe('3M', this)">3M</button>
        <button class="tf-btn" onclick="updateMurataPriceTimeframe('6M', this)">6M</button>
        <button class="tf-btn" onclick="updateMurataPriceTimeframe('YTD', this)">YTD</button>
        <button class="tf-btn" onclick="updateMurataPriceTimeframe('1Y', this)">1Y</button>
        <button class="tf-btn" onclick="updateMurataPriceTimeframe('3Y', this)">3Y</button>
        <button class="tf-btn active" onclick="updateMurataPriceTimeframe('5Y', this)">5Y</button>
      </div>
      <div class="chart-container"><canvas id="murataPriceChart"></canvas></div>

      <h4 style="font-size: 13px; color: var(--text-muted); margin: 14px 0 6px;">B/B Ratio 季度趨勢 (近 {len(MURATA_BBR_QUARTERS)} 季)</h4>
      <div class="chart-container" style="height: 260px;"><canvas id="murataBbrChart"></canvas></div>

      <div class="chart-source-box">
        <strong>📌 資料來源：</strong>
        <a href="https://finance.yahoo.com/quote/6981.T" target="_blank">Yahoo Finance (6981.T)</a> ｜
        Murata IR 決算說明會簡報 + Excel Factbook（人工核實 B/B Ratio）
      </div>
    </div>
"""

MURATA_PRICE_CHART_JS = "" if not murata_price_available else f"""
  const murataPriceDatesReal = {json.dumps(murata_price_dates)};
  const murataPriceValuesReal = {json.dumps(murata_price_values)};
  chartStore['murata_price'] = new Chart(document.getElementById('murataPriceChart'), {{
    type: 'line', data: {{ labels: murataPriceDatesReal, datasets: [
      {{ label: '村田股價(日圓)', data: murataPriceValuesReal, borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.1)', fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4 }}
    ]}},
    options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ tooltip: commonTooltip, legend: {{ display: false }} }},
      scales: {{ x: {{ ticks: {{ font: {{ size: 9 }}, color: '#94a3b8', maxTicksLimit: getMaxTicksForRange(murataPriceDatesReal.length), maxRotation: 0 }}, grid: {{ color: 'rgba(38,51,77,0.4)' }} }},
                 y: {{ title: {{ display: true, text: '股價(日圓)', font: {{ size: 9.5 }} }} }} }} }}
  }});
  buildCustomLegend('murataPriceChart', chartStore['murata_price']);
  function updateMurataPriceTimeframe(tf, btnEl) {{
    btnEl.parentElement.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
    btnEl.classList.add('active');
    const res = sliceTimeframeReal(murataPriceDatesReal, murataPriceValuesReal, tf);
    const chart = chartStore['murata_price'];
    chart.data.labels = res.labels; chart.data.datasets[0].data = res.data;
    chart.options.scales.x.ticks.maxTicksLimit = getMaxTicksForRange(res.labels.length);
    chart.update();
  }}
  window.updateMurataPriceTimeframe = updateMurataPriceTimeframe;
"""

MURATA_BBR_CHART_JS = f"""
  chartStore['murata_bbr'] = new Chart(document.getElementById('murataBbrChart'), {{
    type: 'line', data: {{ labels: {json.dumps(MURATA_BBR_QUARTERS)}, datasets: [
      {{ label: '全公司綜合B/BRatio', data: {json.dumps(MURATA_BBR_COMPANYWIDE)}, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.15)', fill: true, tension: 0, pointRadius: 3, spanGaps: false }},
      {{ label: '主力MLCC B/BRatio', data: {json.dumps(MURATA_BBR_CAPACITORS)}, borderColor: '#ec4899', backgroundColor: 'rgba(236,72,153,0.1)', fill: false, tension: 0, pointRadius: 3, spanGaps: false }},
      {{ label: '{BBR_ALERT} 警戒線', data: Array({len(MURATA_BBR_QUARTERS)}).fill({BBR_ALERT}), borderColor: '#ef4444', borderWidth: 1.5, pointRadius: 0, fill: false }}
    ]}},
    options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ tooltip: {{ ...commonTooltip, callbacks: {{ label: function(ctx) {{ if (ctx.raw === null) return ctx.dataset.label + '：無資料'; return ctx.dataset.label + '：' + ctx.raw.toFixed(2); }} }} }}, legend: {{ display: false }} }},
      scales: {{ x: {{ ticks: {{ font: {{ size: 9.5 }}, color: '#94a3b8', maxRotation: 0 }}, grid: {{ color: 'rgba(38,51,77,0.4)' }} }},
                 y: {{ min: 0.6, max: 1.4, title: {{ display: true, text: 'B/BRatio(倍)', font: {{ size: 9.5 }} }} }} }} }}
  }});
  buildCustomLegend('murataBbrChart', chartStore['murata_bbr']);
"""
print("Part 4 (Nikkei + Murata) 組裝完成")
# ---- 5-11. 日本焦點個股 ----
stock_cards_html = []
stock_charts_js = []

for code, meta in STOCKS.items():
    sd = stock_data[code]
    price_records = sd["price_records"]
    ratios = sd["ratios"]
    price_available = bool(price_records)

    p_dates = [r["date"] for r in price_records] if price_available else []
    p_values = [r["close"] for r in price_records] if price_available else []
    latest_price = get_latest_close(price_records) if price_available else None
    below_warn = (latest_price is not None) and (latest_price < meta["warn_price"])

    price_stat = (
        f'<div class="stat-value" style="color: {"var(--accent-red)" if below_warn else "var(--accent-green)"};">{latest_price:,.1f} 円</div>'
        f'<div class="stat-sub">買進門檻：&lt;{meta["warn_price"]:,} 円 ｜ {"🚨 已跌破" if below_warn else "未跌破"}</div>'
    ) if price_available else (
        '<div class="stat-value" style="color: var(--text-muted);">⚠️ 資料抓取失敗</div>'
    )

    ratio_cells = f"""
        <td>{f"{ratios['per']:.1f}倍" if ratios['per'] is not None else '無資料'}</td>
        <td>{f"{ratios['eps']:.1f}" if ratios['eps'] is not None else '無資料'}</td>
        <td>{f"{ratios['pbr']:.2f}倍" if ratios['pbr'] is not None else '無資料'}</td>
        <td>{f"{ratios['operating_margin']:.1f}%" if ratios['operating_margin'] is not None else '無資料'}</td>
    """

    card_html = f"""
      <div class="section-card">
        <div class="section-header"><div><div class="section-title">{meta['num']}. {meta['name']} ({code}.JP)</div><div class="subtitle">{meta['name_en']}</div></div></div>
        <div class="table-container">
          <table class="stock-table">
            <thead><tr>
              <th>最新股價</th><th>PER (即時)</th><th>EPS (即時)</th><th>PBR (即時)</th><th>營益率 (即時)</th><th>買進門檻</th><th>狀態</th>
            </tr></thead>
            <tbody><tr>
              <td><strong>{f"{latest_price:,.1f} 円" if price_available else '無資料'}</strong></td>
              {ratio_cells}
              <td>&lt;{meta['warn_price']:,} 円</td>
              <td><span class="badge {'badge-nobuy' if below_warn else 'badge-normal'}">{'不適合買進' if below_warn else '可留意'}</span></td>
            </tr></tbody>
          </table>
        </div>
        <div class="timeframe-bar">
          <span style="font-size: 11px; color: #64748b; margin-right: 2px;">股價週期:</span>
          <button class="tf-btn" onclick="updateStock{code}Timeframe('1D', this)">1D</button>
          <button class="tf-btn" onclick="updateStock{code}Timeframe('5D', this)">5D</button>
          <button class="tf-btn" onclick="updateStock{code}Timeframe('1M', this)">1M</button>
          <button class="tf-btn" onclick="updateStock{code}Timeframe('3M', this)">3M</button>
          <button class="tf-btn" onclick="updateStock{code}Timeframe('6M', this)">6M</button>
          <button class="tf-btn" onclick="updateStock{code}Timeframe('YTD', this)">YTD</button>
          <button class="tf-btn" onclick="updateStock{code}Timeframe('1Y', this)">1Y</button>
          <button class="tf-btn" onclick="updateStock{code}Timeframe('3Y', this)">3Y</button>
          <button class="tf-btn active" onclick="updateStock{code}Timeframe('5Y', this)">5Y</button>
        </div>
        <div class="chart-container"><canvas id="stock{code}Chart"></canvas></div>
        <div class="chart-source-box">
          <strong>📌 資料來源：</strong>
          <a href="https://finance.yahoo.com/quote/{code}.T" target="_blank">Yahoo Finance ({code}.T)</a> ｜
          財務比率：yfinance 即時快照（buffett-code.com 使用條款禁止自動化爬取，不使用）
        </div>
      </div>
    """
    stock_cards_html.append(card_html)

    if price_available:
        chart_js = f"""
  const stock{code}DatesReal = {json.dumps(p_dates)};
  const stock{code}ValuesReal = {json.dumps(p_values)};
  chartStore['price_{code}'] = new Chart(document.getElementById('stock{code}Chart'), {{
    type: 'line', data: {{ labels: stock{code}DatesReal, datasets: [
      {{ label: '{meta["name"]}股價(日圓)', data: stock{code}ValuesReal, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4 }},
      {{ label: '買進門檻({meta["warn_price"]}円)', data: Array(stock{code}DatesReal.length).fill({meta["warn_price"]}), borderColor: '#ef4444', borderWidth: 1.5, borderDash: [5,5], pointRadius: 0, fill: false }}
    ]}},
    options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ tooltip: commonTooltip, legend: {{ display: false }} }},
      scales: {{ x: {{ ticks: {{ font: {{ size: 9 }}, color: '#94a3b8', maxTicksLimit: getMaxTicksForRange(stock{code}DatesReal.length), maxRotation: 0 }}, grid: {{ color: 'rgba(38,51,77,0.4)' }} }},
                 y: {{ title: {{ display: true, text: '股價(日圓)', font: {{ size: 9.5 }} }} }} }} }}
  }});
  buildCustomLegend('stock{code}Chart', chartStore['price_{code}']);
  function updateStock{code}Timeframe(tf, btnEl) {{
    btnEl.parentElement.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
    btnEl.classList.add('active');
    const res = sliceTimeframeReal(stock{code}DatesReal, stock{code}ValuesReal, tf);
    const chart = chartStore['price_{code}'];
    chart.data.labels = res.labels; chart.data.datasets[0].data = res.data;
    chart.data.datasets[1].data = Array(res.labels.length).fill({meta["warn_price"]});
    chart.options.scales.x.ticks.maxTicksLimit = getMaxTicksForRange(res.labels.length);
    chart.update();
  }}
  window.updateStock{code}Timeframe = updateStock{code}Timeframe;
        """
    else:
        chart_js = f"// {meta['name']} ({code})：股價無資料，略過圖表初始化"
    stock_charts_js.append(chart_js)

STOCKS_SECTION_HTML = f"""
    <h2 style="font-size: 20px; margin: 28px 0 14px; color: #fff;">5～11. 日本焦點個股追蹤 (真實日資料，財務比率為即時快照)</h2>
    <div class="stock-grid">
      {''.join(stock_cards_html)}
    </div>
"""
STOCKS_CHART_JS = "\n".join(stock_charts_js)

print(f"Part 5 (7檔日股) 組裝完成，共 {len(STOCKS)} 檔")
# ============================================================
# 6. 組裝完整 HTML 並寫檔
# ============================================================
FULL_HTML = HTML_HEAD + TAIEX_SECTION_HTML + VIX_MICH_SECTION_HTML + NIKKEI_SECTION_HTML + MURATA_SECTION_HTML + STOCKS_SECTION_HTML + f"""
  <div style="text-align:center; color: var(--text-muted); font-size: 11px; margin-top: 24px; padding: 16px;">
    報告由 GitHub Actions 自動生成 ｜ 資料來源：Yahoo Finance, FRED, Murata IR ｜ 產生時間：{today_str}
  </div>
</div>
""" + JS_COMMON_HELPERS.replace("</script>", "") + TAIEX_CHART_JS + VIX_MICH_CHART_JS + NIKKEI_CHART_JS + MURATA_PRICE_CHART_JS + MURATA_BBR_CHART_JS + STOCKS_CHART_JS + """
</script>
</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(FULL_HTML)

print(f"\n✅ index.html 已產生，共 {len(FULL_HTML):,} 字元")


# ============================================================
# 7. Email 發送（動態數字，測試階段僅寄給 nirvanatw@gmail.com）
# ============================================================
def send_summary_email():
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_password = os.environ.get('GMAIL_APP_PASSWORD')

    if not gmail_user or not gmail_password:
        print("⚠️ 提示: 未偵測到 GMAIL_USER 或 GMAIL_APP_PASSWORD，略過發信步驟。")
        return

    # ⚠️ 測試階段：僅寄給 nirvanatw@gmail.com。正式上線後請改回兩人清單：
    # recipients = ["nirvanatw@gmail.com", "doris.yang1108@gmail.com"]
    recipients = ["nirvanatw@gmail.com"]

    subject = f"【每日市場監控報告】{today_str}"

    alert_text_lines = "\n".join(f"  {i+1}. {msg.replace('<strong>', '').replace('</strong>', '')}" for i, msg in enumerate(alert_messages))

    body = f"""每日全球市場與總經個股監控報告 - {today_str}

【本日預警項目】
{alert_text_lines}

【關鍵指標快照】
- 台股加權指數：{f"{taiex_latest:,.2f}" if taiex_available else '資料抓取失敗'}
- VIX恐慌指數：{f"{vix_latest:.2f}" if vix_available else '資料抓取失敗'}
- 密大消費者信心指數：{f"{mich_latest:.1f}" if mich_available else '資料抓取失敗'}
- 日經225指數：{f"{nikkei_latest:,.2f}" if nikkei_available else '資料抓取失敗'}
- 村田B/BRatio（全公司）：{bbr_latest_companywide:.2f}
- 村田B/BRatio（主力MLCC）：{f"{bbr_latest_capacitors:.2f}" if bbr_latest_capacitors is not None else '無資料'}

完整報告請見：https://metallicatw.github.io/market-monitor/

--
此為系統自動發送郵件，測試階段僅寄送至 nirvanatw@gmail.com。
"""

    msg = MIMEMultipart()
    msg['From'] = gmail_user
    msg['To'] = ", ".join(recipients)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())
        server.quit()
        print(f"✅ Email 已發送至: {', '.join(recipients)}")
    except Exception as e:
        print(f"❌ Email 發送失敗: {e}")


if __name__ == "__main__":
    send_summary_email()
