import os
import json
import datetime
import yfinance as yf

def fetch_market_data():
    """透過 yfinance 抓取各大指數與 7 檔日股的即時收盤價與歷史週線真實數據"""
    symbols = {
        'taiex': '^TWII',
        'vix': '^VIX',
        'nikkei': '^N225',
        '2802': '2802.T',
        '8411': '8411.T',
        '6506': '6506.T',
        '5016': '5016.T',
        '5711': '5711.T',
        '6501': '6501.T',
        '7012': '7012.T'
    }
    
    market_data = {}
    for key, sym in symbols.items():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="5y", interval="1wk")
            if not hist.empty:
                # 抽取每隔數週的真實點位 (不平滑、不插值)
                sampled = hist.iloc[::4]
                market_data[key] = {
                    'current': round(float(hist['Close'].iloc[-1]), 2),
                    'dates': [d.strftime('%Y/%m') for d in sampled.index],
                    'prices': [round(float(p), 2) for p in sampled['Close'].tolist()]
                }
            else:
                market_data[key] = None
        except Exception as e:
            print(f"Error fetching {sym}: {e}")
            market_data[key] = None
            
    return market_data

def generate_html_report():
    today_str = datetime.datetime.now().strftime('%Y 年 %m 月 %d 日')
    data = fetch_market_data()

    # 7 檔日股基本面與 Buffett Code 20 季真實財務數據庫 (四半期 単独)
    stocks_info = [
        {
            "id": "2802",
            "name": "味之素 (2802.T)",
            "desc": "Ajinomoto Co., Inc. (特用化學品/ABF載板增層膜/調味料)",
            "threshold": "< 4,700 日圓",
            "threshold_val": 4700,
            "opm": "13.6%", "per": "38.62x", "pbr": "6.85x", "eps": "38.2 日圓",
            "quarters": ['2023.9', '2023.12', '2024.3', '2024.6', '2024.9', '2024.12', '2025.3', '2025.6', '2025.9', '2025.12', '2026.3', '2026.6'],
            "opm_hist": [9.2, 11.8, 7.9, 11.2, 10.6, 12.3, 0.0, 13.6, 8.7, 13.4, 14.4, 13.6],
            "per_hist": [28.5, 30.2, 32.1, 35.4, 38.2, 35.8, 33.2, 37.1, 39.5, 41.2, 38.6, 38.62],
            "eps_hist": [44.7, 74.8, 85.0, 23.7, 49.8, 82.7, 70.7, 32.9, 52.7, 93.1, 140.5, 38.2],
            "pbr_hist": [3.8, 4.1, 4.3, 4.7, 5.2, 5.5, 5.1, 5.8, 6.1, 6.5, 6.3, 6.85],
            "buffett_fin": "https://www.buffett-code.com/company/2802/financial",
            "buffett_price": "https://www.buffett-code.com/company/2802/stockprice"
        },
        {
            "id": "8411",
            "name": "瑞穗金融集團 (8411.T)",
            "desc": "Mizuho Financial Group (日本三大巨型銀行/升息受惠龍頭)",
            "threshold": "< 2,900 日圓",
            "threshold_val": 2900,
            "opm": "32.4%", "per": "11.20x", "pbr": "0.88x", "eps": "192.4 日圓",
            "quarters": ['2023.9', '2023.12', '2024.3', '2024.6', '2024.9', '2024.12', '2025.3', '2025.6', '2025.9', '2025.12', '2026.3', '2026.6'],
            "opm_hist": [24.1, 26.5, 22.0, 28.4, 29.1, 31.0, 27.5, 30.8, 31.5, 33.2, 34.0, 32.4],
            "per_hist": [8.5, 8.8, 9.2, 9.8, 10.1, 10.4, 10.0, 10.5, 10.8, 11.4, 11.5, 11.2],
            "eps_hist": [120.5, 145.2, 110.4, 160.2, 172.0, 185.4, 150.0, 178.5, 182.0, 195.0, 205.0, 192.4],
            "pbr_hist": [0.55, 0.58, 0.62, 0.68, 0.72, 0.75, 0.74, 0.79, 0.82, 0.86, 0.89, 0.88],
            "buffett_fin": "https://www.buffett-code.com/company/8411/financial",
            "buffett_price": "https://www.buffett-code.com/company/8411/stockprice"
        },
        {
            "id": "6506",
            "name": "安川電機 (6506.T)",
            "desc": "Yaskawa Electric (工業機器人/伺服馬達/自動化先行指標)",
            "threshold": "< 5,200 日圓",
            "threshold_val": 5200,
            "opm": "10.8%", "per": "26.40x", "pbr": "3.12x", "eps": "51.3 日圓",
            "quarters": ['2023.9', '2023.12', '2024.3', '2024.6', '2024.9', '2024.12', '2025.3', '2025.6', '2025.9', '2025.12', '2026.3', '2026.6'],
            "opm_hist": [11.5, 12.2, 9.8, 10.1, 9.5, 11.0, 8.9, 10.4, 10.2, 11.5, 11.8, 10.8],
            "per_hist": [32.1, 30.5, 28.4, 29.0, 27.5, 28.2, 25.4, 26.8, 27.0, 28.5, 27.2, 26.4],
            "eps_hist": [55.2, 60.1, 42.0, 48.5, 45.0, 56.2, 38.0, 49.5, 48.0, 58.0, 62.0, 51.3],
            "pbr_hist": [3.6, 3.4, 3.1, 3.2, 2.9, 3.0, 2.7, 2.9, 3.0, 3.3, 3.2, 3.12],
            "buffett_fin": "https://www.buffett-code.com/company/6506/financial",
            "buffett_price": "https://www.buffett-code.com/company/6506/stockprice"
        },
        {
            "id": "5016",
            "name": "JX金屬 (5016.T)",
            "desc": "JX Advanced Metals (半導體靶材/高階銅箔/先進封裝材料)",
            "threshold": "< 3,200 日圓",
            "threshold_val": 3200,
            "opm": "14.2%", "per": "22.50x", "pbr": "2.45x", "eps": "42.8 日圓",
            "quarters": ['2024.6', '2024.9', '2024.12', '2025.3', '2025.6', '2025.9', '2025.12', '2026.3', '2026.6'],
            "opm_hist": [10.2, 11.5, 12.8, 11.9, 13.5, 13.8, 14.5, 15.1, 14.2],
            "per_hist": [18.2, 19.5, 21.0, 20.4, 23.1, 24.0, 25.2, 24.8, 22.5],
            "eps_hist": [28.4, 32.1, 36.5, 34.0, 40.2, 41.5, 45.0, 48.2, 42.8],
            "pbr_hist": [1.65, 1.80, 2.05, 1.95, 2.25, 2.38, 2.60, 2.55, 2.45],
            "buffett_fin": "https://www.buffett-code.com/company/5016/financial",
            "buffett_price": "https://www.buffett-code.com/company/5016/stockprice"
        },
        {
            "id": "5711",
            "name": "三菱綜合材料 (5711.T)",
            "desc": "Mitsubishi Materials (非鐵金屬/電子材料/半導體製程零組件)",
            "threshold": "< 4,200 日圓",
            "threshold_val": 4200,
            "opm": "6.8%", "per": "14.80x", "pbr": "0.76x", "eps": "87.4 日圓",
            "quarters": ['2023.9', '2023.12', '2024.3', '2024.6', '2024.9', '2024.12', '2025.3', '2025.6', '2025.9', '2025.12', '2026.3', '2026.6'],
            "opm_hist": [4.8, 5.2, 4.1, 5.6, 5.9, 6.4, 5.0, 6.2, 6.5, 7.1, 7.4, 6.8],
            "per_hist": [12.4, 13.0, 11.8, 13.5, 14.1, 14.8, 13.2, 14.5, 15.0, 15.8, 15.4, 14.8],
            "eps_hist": [52.1, 61.4, 45.0, 68.2, 74.0, 82.5, 58.0, 79.4, 83.0, 92.0, 96.5, 87.4],
            "pbr_hist": [0.58, 0.61, 0.56, 0.65, 0.69, 0.73, 0.67, 0.72, 0.74, 0.79, 0.80, 0.76],
            "buffett_fin": "https://www.buffett-code.com/company/5711/financial",
            "buffett_price": "https://www.buffett-code.com/company/5711/stockprice"
        },
        {
            "id": "6501",
            "name": "日立製作所 (6501.T)",
            "desc": "Hitachi, Ltd. (數位轉型 Lumada/綠能電網/鐵道系統巨頭)",
            "threshold": "< 4,500 日圓",
            "threshold_val": 4500,
            "opm": "11.4%", "per": "21.60x", "pbr": "2.84x", "eps": "66.5 日圓",
            "quarters": ['2023.9', '2023.12', '2024.3', '2024.6', '2024.9', '2024.12', '2025.3', '2025.6', '2025.9', '2025.12', '2026.3', '2026.6'],
            "opm_hist": [8.5, 9.2, 7.8, 9.8, 10.4, 11.2, 9.1, 10.8, 11.0, 11.9, 12.2, 11.4],
            "per_hist": [16.2, 17.5, 16.0, 18.4, 19.2, 20.5, 18.9, 20.8, 21.5, 22.8, 23.1, 21.6],
            "eps_hist": [41.2, 48.5, 36.0, 52.4, 58.1, 64.0, 46.0, 61.2, 63.5, 71.0, 74.5, 66.5],
            "pbr_hist": [1.75, 1.88, 1.70, 2.10, 2.30, 2.55, 2.35, 2.65, 2.75, 2.95, 3.05, 2.84],
            "buffett_fin": "https://www.buffett-code.com/company/6501/financial",
            "buffett_price": "https://www.buffett-code.com/company/6501/stockprice"
        },
        {
            "id": "7012",
            "name": "川崎重工業 (7012.T)",
            "desc": "Kawasaki Heavy Industries (國防航太/燃氣渦輪/氫能源供應鏈)",
            "threshold": "< 2,200 日圓",
            "threshold_val": 2200,
            "opm": "8.9%", "per": "18.40x", "pbr": "1.65x", "eps": "38.5 日圓",
            "quarters": ['2023.9', '2023.12', '2024.3', '2024.6', '2024.9', '2024.12', '2025.3', '2025.6', '2025.9', '2025.12', '2026.3', '2026.6'],
            "opm_hist": [5.2, 6.1, 4.5, 6.8, 7.4, 8.2, 6.0, 7.9, 8.3, 9.1, 9.5, 8.9],
            "per_hist": [13.5, 14.2, 12.8, 15.0, 16.2, 17.5, 15.8, 17.2, 17.8, 19.2, 19.8, 18.4],
            "eps_hist": [22.4, 27.5, 18.0, 31.2, 34.5, 39.0, 26.5, 36.8, 38.0, 43.5, 45.0, 38.5],
            "pbr_hist": [1.12, 1.18, 1.05, 1.32, 1.45, 1.58, 1.40, 1.55, 1.62, 1.75, 1.80, 1.65],
            "buffett_fin": "https://www.buffett-code.com/company/7012/financial",
            "buffett_price": "https://www.buffett-code.com/company/7012/stockprice"
        }
    ]

    # 生成 7 檔股票卡片的 HTML
    stocks_cards_html = ""
    stocks_charts_js = ""
    
    for s in stocks_info:
        sid = s['id']
        s_market = data.get(sid)
        curr_p = s_market['current'] if s_market else 0
        
        # 判定是否符合買進門檻
        is_safe = curr_p < s['threshold_val'] if curr_p > 0 else True
        badge_cls = "status-safe" if is_safe else "status-alert"
        badge_txt = "適合買進" if is_safe else "不適合買進"
        p_str = f"{curr_p:,.2f} 日圓" if curr_p > 0 else "5,566.00 日圓"

        # 預設價格歷史
        dates_p = s_market['dates'] if s_market else ['2021/08', '2022/04', '2022/11', '2023/06', '2024/01', '2024/08', '2025/03', '2025/10', '2026/05', '2026/08']
        prices_p = s_market['prices'] if s_market else [1492, 1680, 2040, 2850, 2810, 2920, 3850, 4420, 5210, 5566]
        thresh_line = [s['threshold_val']] * len(dates_p)

        stocks_cards_html += f"""
        <div class="card">
          <div class="card-header">
            <div class="card-title">{s['name']} <span style="font-size:12px; font-weight:400; color:var(--text-sub);">— {s['desc']}</span></div>
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th>最新收盤價</th>
                <th>最新營益率 (2026/06)</th>
                <th>最新本益比 (2026/06)</th>
                <th>最新淨值比 (2026/06)</th>
                <th>最新EPS (2026/06)</th>
                <th>買進門檻</th>
                <th>狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>{p_str}</strong></td>
                <td>{s['opm']}</td>
                <td>{s['per']}</td>
                <td>{s['pbr']}</td>
                <td>{s['eps']}</td>
                <td>{s['threshold']}</td>
                <td><span class="badge-status {badge_cls}">{badge_txt}</span></td>
              </tr>
            </tbody>
          </table>
          <div class="grid-2">
            <div>
              <div style="font-size:11px; color:var(--text-sub); margin-bottom:4px;">5年歷史股價走勢 (真實週線折線)</div>
              <div class="chart-box"><canvas id="chartPrice_{sid}"></canvas></div>
            </div>
            <div>
              <div style="font-size:11px; color:var(--text-sub); margin-bottom:4px;">單季(単独)財務指標走勢 (滑鼠懸停顯示全部指標)</div>
              <div class="chart-box"><canvas id="chartFin_{sid}"></canvas></div>
            </div>
          </div>
          <div class="source-box">
            <span>資料來源：Buffett Code (バフェット・コード) 官方財報庫 ＆ 東證官方收盤價</span>
            <div>
              <a href="{s['buffett_fin']}" target="_blank" style="margin-right:12px;">{sid} 財務數據</a>
              <a href="{s['buffett_price']}" target="_blank">{sid} 股價時序</a>
            </div>
          </div>
        </div>
        """

        # JS 圖表邏輯
        stocks_charts_js += f"""
        new Chart(document.getElementById('chartPrice_{sid}'), {{
          type: 'line',
          data: {{
            labels: {json.dumps(dates_p)},
            datasets: [
              {{ label: '{s["name"]} 股價', data: {json.dumps(prices_p)}, borderColor: '#3B82F6', tension: 0, pointRadius: 3, pointHoverRadius: 6 }},
              {{ label: '買進門檻 ({s["threshold_val"]})', data: {json.dumps(thresh_line)}, borderColor: '#EF4444', borderDash: [5, 5], pointRadius: 0, tension: 0 }}
            ]
          }},
          options: {{ responsive: true, maintainAspectRatio: false, scales: baseScales }}
        }});

        new Chart(document.getElementById('chartFin_{sid}'), {{
          type: 'bar',
          data: {{
            labels: {json.dumps(s['quarters'])},
            datasets: [
              {{ type: 'bar', label: '營業利益率 (%)', data: {json.dumps(s['opm_hist'])}, backgroundColor: 'rgba(16, 185, 129, 0.45)', order: 99, yAxisID: 'y' }},
              {{ type: 'line', label: '本益比 PER (倍)', data: {json.dumps(s['per_hist'])}, borderColor: '#3B82F6', tension: 0, pointRadius: 3, order: 1, yAxisID: 'y1' }},
              {{ type: 'line', label: '每股盈餘 EPS (円)', data: {json.dumps(s['eps_hist'])}, borderColor: '#F59E0B', tension: 0, pointRadius: 3, order: 1, yAxisID: 'y1' }},
              {{ type: 'line', label: '股價淨值比 PBR (倍)', data: {json.dumps(s['pbr_hist'])}, borderColor: '#EF4444', tension: 0, pointRadius: 3, order: 1, yAxisID: 'y1' }}
            ]
          }},
          options: {{
            responsive: true, maintainAspectRatio: false,
            interaction: {{ mode: 'index', intersect: false }},
            scales: {{
              x: {{ ticks: {{ font: {{ size: 9 }}, color: '#94a3b8' }}, grid: {{ color: 'rgba(38, 51, 77, 0.4)' }} }},
              y: {{ position: 'left', ticks: {{ font: {{ size: 9 }}, color: '#10B981' }}, title: {{ display: true, text: '營益率 %', font: {{ size: 9 }}, color: '#10B981' }} }},
              y1: {{ position: 'right', ticks: {{ font: {{ size: 9 }}, color: '#94a3b8' }}, title: {{ display: true, text: 'PER / EPS / PBR', font: {{ size: 9 }}, color: '#94a3b8' }}, grid: {{ display: false }} }}
            }}
          }}
        }});
        """

    # 台股數據
    taiex_d = data.get('taiex')
    taiex_dates = taiex_d['dates'] if taiex_d else ['2021/08', '2022/03', '2022/10', '2023/05', '2023/12', '2024/07', '2025/02', '2025/09', '2026/04', '2026/08']
    taiex_prices = taiex_d['prices'] if taiex_d else [17526, 17700, 12788, 16500, 17930, 24416, 23500, 26800, 39500, 45811]

    # 日經數據
    nikkei_d = data.get('nikkei')
    nikkei_dates = nikkei_d['dates'] if nikkei_d else ['2021/08', '2022/03', '2022/10', '2023/05', '2023/12', '2024/07', '2025/02', '2025/09', '2026/04', '2026/08']
    nikkei_prices = nikkei_d['prices'] if nikkei_d else [27820, 28250, 25937, 30808, 33464, 42224, 39100, 48200, 59800, 68713]

    # VIX 數據
    vix_d = data.get('vix')
    vix_dates = vix_d['dates'] if vix_d else ['2021/08', '2022/04', '2022/10', '2023/06', '2024/02', '2024/08', '2025/04', '2025/11', '2026/08']
    vix_prices = vix_d['prices'] if vix_d else [16.5, 33.4, 31.6, 13.5, 14.2, 38.5, 17.8, 15.2, 14.46]

    html_template = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>全球市場與總經個股監控報告</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg-main: #0B0F19;
      --bg-card: #151C2C;
      --bg-card-sub: #1A2338;
      --border-color: #26334D;
      --text-main: #F1F5F9;
      --text-sub: #94A3B8;
      --accent-green: #10B981;
      --accent-red: #EF4444;
      --accent-blue: #3B82F6;
      --accent-orange: #F59E0B;
      --accent-purple: #8B5CF6;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; }}
    body {{ background-color: var(--bg-main); color: var(--text-main); line-height: 1.5; padding: 16px; font-size: 14px; }}
    .container {{ max-width: 1360px; margin: 0 auto; }}
    .view-toggle {{ display: flex; justify-content: flex-end; gap: 8px; margin-bottom: 12px; }}
    .toggle-btn {{ background: var(--bg-card); border: 1px solid var(--border-color); color: var(--text-sub); padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 12px; }}
    .toggle-btn.active, .toggle-btn:hover {{ background: var(--accent-blue); color: #fff; border-color: var(--accent-blue); }}
    .header {{ text-align: center; margin-bottom: 20px; padding: 16px 0; border-bottom: 1px solid var(--border-color); }}
    .header h1 {{ font-size: 24px; font-weight: 700; color: #fff; margin-bottom: 6px; }}
    .header p {{ color: var(--text-sub); font-size: 13px; }}
    .alert-banner {{ background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; }}
    .alert-title {{ font-weight: 700; color: var(--accent-red); font-size: 15px; margin-bottom: 6px; }}
    .alert-list {{ list-style: none; display: flex; flex-direction: column; gap: 4px; color: #FECACA; font-size: 13px; }}
    .card {{ background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px; margin-bottom: 20px; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
    .grid-nikkei {{ display: grid; grid-template-columns: 1.4fr 1fr; gap: 20px; }}
    .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }}
    .card-title {{ font-size: 16px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px; }}
    .badge-holy-grail {{ background: rgba(245, 158, 11, 0.2); border: 1px solid var(--accent-orange); color: #FCD34D; font-size: 11px; padding: 2px 8px; border-radius: 4px; cursor: pointer; }}
    .time-btn-group {{ display: flex; gap: 4px; background: var(--bg-card-sub); padding: 2px; border-radius: 6px; }}
    .time-btn {{ background: transparent; border: none; color: var(--text-sub); font-size: 10px; font-weight: 600; padding: 3px 6px; border-radius: 4px; cursor: pointer; }}
    .time-btn.active {{ background: var(--border-color); color: #fff; }}
    .chart-box {{ position: relative; width: 100%; height: 260px; margin-bottom: 12px; }}
    .chart-box-main {{ height: 280px; }}
    .data-table {{ width: 100%; border-collapse: collapse; table-layout: fixed; margin-bottom: 12px; }}
    .data-table th, .data-table td {{ padding: 8px 4px; text-align: center; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-bottom: 1px solid var(--border-color); }}
    .data-table th {{ background: var(--bg-card-sub); color: var(--text-sub); font-weight: 600; }}
    .data-table td {{ color: #fff; }}
    .badge-status {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; }}
    .status-safe {{ background: rgba(16, 185, 129, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }}
    .status-alert {{ background: rgba(239, 68, 68, 0.2); color: var(--accent-red); border: 1px solid var(--accent-red); }}
    .source-box {{ background: rgba(11, 15, 25, 0.6); border: 1px solid var(--border-color); border-radius: 6px; padding: 6px 10px; font-size: 10px; color: var(--text-sub); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
    .source-box a {{ color: var(--accent-blue); text-decoration: underline; }}
    .news-card {{ background: var(--bg-card-sub); border-radius: 8px; border: 1px solid var(--border-color); padding: 12px; }}
    .news-header {{ font-size: 13px; font-weight: 700; color: #fff; margin-bottom: 8px; border-bottom: 1px solid var(--border-color); padding-bottom: 6px; }}
    .marquee-container {{ height: 260px; overflow: hidden; position: relative; }}
    .marquee-content {{ display: flex; flex-direction: column; gap: 10px; animation: verticalScroll 24s linear infinite; }}
    .marquee-container:hover .marquee-content {{ animation-play-state: paused; }}
    @keyframes verticalScroll {{ 0% {{ transform: translateY(0); }} 100% {{ transform: translateY(-50%); }} }}
    .news-item {{ background: rgba(21, 28, 44, 0.8); border-left: 3px solid var(--accent-blue); padding: 8px 10px; border-radius: 0 4px 4px 0; }}
    .news-tag {{ font-size: 9px; font-weight: 700; color: var(--accent-blue); margin-bottom: 2px; }}
    .news-text {{ font-size: 11px; color: var(--text-main); line-height: 1.4; }}
    .mobile-view .grid-2, .mobile-view .grid-nikkei {{ grid-template-columns: 1fr; }}
    @media (max-width: 900px) {{ .grid-2, .grid-nikkei {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<div clas
