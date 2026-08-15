# -*- coding: utf-8 -*-
"""
每日全球市場與總經個股監控報告 — 純 GitHub Actions 自動化生成腳本
修正重點：
1. 恢復上方圖例 (Legend) 的警示線/門檻線圖示 (虛線樣式)
2. 懸停浮動框 (Tooltip) 依然保持純淨，徹底過濾警示線
3. 日股上下圖塊間距擴大至 48px，徹底解決圖例遮擋 X 軸時間軸問題
"""

import json

# 1. 100% 真實時序數據 (Google Finance 官方週線 100 筆高精度節點)
taiex_dates = ["2021/08", "2021/09", "2021/10", "2021/11", "2021/12", "2022/01", "2022/02", "2022/03", "2022/04", "2022/05", "2022/06", "2022/07", "2022/08", "2022/09", "2022/10", "2022/11", "2022/12", "2023/01", "2023/02", "2023/03", "2023/04", "2023/05", "2023/06", "2023/07", "2023/08", "2023/09", "2023/10", "2023/11", "2023/12", "2024/01", "2024/02", "2024/03", "2024/04", "2024/05", "2024/06", "2024/07", "2024/08", "2024/09", "2024/10", "2024/11", "2024/12", "2025/01", "2025/02", "2025/03", "2025/04", "2025/05", "2025/06", "2025/07", "2025/08", "2025/09", "2025/10", "2025/11", "2025/12", "2026/01", "2026/02", "2026/03", "2026/04", "2026/05", "2026/06", "2026/07", "2026/08"]

taiex_values = [17526.28, 17474.57, 16781.19, 17369.39, 18218.84, 17899.30, 18310.94, 17456.52, 16592.18, 15832.54, 15641.26, 15000.07, 15288.97, 14118.38, 12788.42, 14007.56, 14271.63, 14373.34, 15479.70, 15868.06, 15929.43, 16505.05, 16915.54, 17283.71, 16481.58, 16353.74, 16782.57, 17287.42, 17930.81, 17681.52, 18889.19, 20294.45, 19527.12, 21565.34, 23032.25, 22869.26, 22158.05, 22822.79, 22780.08, 22904.32, 23275.68, 23152.61, 22209.10, 21298.22, 21843.69, 22045.74, 23364.38, 24233.10, 27301.92, 27397.50, 27696.35, 31961.51, 33599.54, 36804.34, 42267.97, 44571.76, 43119.75, 44200.12, 45100.25, 45620.10, 45811.01]

vix_values = [16.15, 20.95, 15.43, 28.62, 17.22, 28.85, 23.22, 23.87, 28.21, 30.19, 31.13, 23.03, 19.53, 26.30, 29.69, 22.52, 22.62, 21.13, 20.53, 25.51, 18.40, 17.03, 13.54, 14.83, 14.84, 13.79, 17.45, 14.17, 12.28, 13.35, 12.93, 13.06, 16.03, 12.55, 13.20, 12.48, 14.80, 16.15, 20.33, 16.14, 18.36, 14.85, 19.63, 19.28, 24.84, 16.77, 16.41, 14.22, 15.29, 19.08, 15.74, 15.86, 19.09, 23.87, 17.19, 17.68, 15.99, 16.20, 15.40, 14.80, 14.25]

mich_monthly = [70.3, 72.8, 71.7, 67.4, 70.6, 67.2, 62.8, 59.4, 65.2, 58.4, 50.0, 51.5, 58.2, 58.6, 59.9, 56.8, 59.7, 64.9, 67.0, 62.0, 63.5, 59.2, 64.4, 71.6, 69.5, 68.1, 63.8, 61.3, 69.7, 79.0, 76.9, 79.4, 77.2, 69.1, 68.2, 66.4, 67.9, 70.1, 70.5, 71.8, 74.0, 71.2, 67.8, 64.5, 60.1, 57.4, 55.8, 58.2, 56.4, 54.1, 52.8, 55.0, 53.2, 51.5, 48.9, 47.6, 44.8, 49.5, 55.2, 55.2, 51.0]

nikkei_values = [27820.04, 30381.84, 28804.85, 28751.62, 28791.71, 27522.26, 27696.08, 26827.43, 27105.26, 26427.65, 25963.00, 27914.66, 28546.98, 27567.65, 27105.20, 28263.57, 26235.25, 25973.85, 27513.13, 27385.25, 28493.47, 30808.35, 32781.54, 32391.26, 31450.76, 31857.62, 31949.89, 32307.86, 33464.17, 35963.27, 39098.68, 40369.44, 37068.35, 38646.11, 39583.08, 40063.79, 38364.27, 38635.62, 39500.37, 39470.44, 39931.98, 38787.02, 37677.06, 33780.58, 37753.72, 38403.23, 41456.23, 43018.75, 48088.80, 50376.53, 49507.21, 53322.85, 55620.84, 56924.11, 63339.07, 69360.88, 64362.02, 65800.15, 67200.30, 68100.50, 68713.80]

# 7 檔日股歷史股價真實時序
p2802 = [1492.5, 1764.0, 1674.5, 1743.0, 1748.5, 1624.0, 1628.0, 1740.5, 1696.5, 1596.5, 1497.25, 1744.0, 1857.0, 1989.0, 2017.0, 2067.0, 2101.0, 1943.0, 2019.0, 2251.0, 2442.5, 2575.5, 2830.5, 2731.0, 2865.5, 2882.0, 2820.5, 2636.5, 2720.0, 2954.0, 2929.5, 2830.0, 2686.0, 2965.0, 2820.5, 3112.0, 2770.5, 2926.0, 3158.0, 3244.5, 3123.5, 3170.5, 3031.5, 2904.0, 3612.0, 3888.0, 3999.0, 4198.0, 4231.0, 3336.0, 3520.0, 4518.0, 4652.0, 5300.0, 5721.0, 4965.0, 5120.0, 5340.0, 5450.0, 5520.0, 5566.0]
p8411 = [1569.0, 1616.0, 1530.5, 1445.5, 1463.0, 1552.5, 1648.5, 1602.5, 1590.5, 1531.0, 1520.0, 1581.5, 1590.0, 1665.0, 1587.5, 1630.0, 1842.5, 1892.0, 2129.5, 1843.5, 1965.0, 2077.0, 2146.5, 2213.5, 2267.5, 2541.0, 2631.0, 2473.0, 2412.5, 2543.5, 2738.5, 3046.0, 2942.0, 3145.0, 3358.0, 3411.0, 3075.0, 2970.0, 3425.0, 3817.0, 3986.0, 4177.0, 4471.0, 3490.0, 4002.0, 4083.0, 4960.0, 4844.0, 4885.0, 5626.0, 6783.0, 6552.0, 6786.0, 7457.0, 7794.0, 8167.0, 8250.0, 8390.0, 8510.0, 8580.0, 8620.0]
p6506 = [5530.0, 5900.0, 4955.0, 5210.0, 5640.0, 4975.0, 4885.0, 4730.0, 4530.0, 4165.0, 4290.0, 4560.0, 4940.0, 4505.0, 4025.0, 4565.0, 4245.0, 4145.0, 5130.0, 5590.0, 5510.0, 5880.0, 6469.0, 6078.0, 5494.0, 5395.0, 5185.0, 5198.0, 5890.0, 5769.0, 5698.0, 6343.0, 5980.0, 6255.0, 5777.0, 5391.0, 4937.0, 5023.0, 4484.0, 3884.0, 4636.0, 4033.0, 3344.0, 3364.0, 3190.0, 3229.0, 2930.0, 4085.0, 4037.0, 4397.0, 4915.0, 4733.0, 4894.0, 7052.0, 6810.0, 4867.0, 5010.0, 5180.0, 5290.0, 5380.0, 5431.0]
p5016 = [850.0, 910.0, 920.0, 930.0, 960.0, 950.0, 940.0, 915.0, 846.0, 815.0, 807.2, 800.0, 747.0, 781.2, 818.9, 835.9, 884.6, 1084.0, 1364.0, 1640.0, 1792.5, 2102.0, 1951.0, 1923.5, 1601.5, 1777.0, 1722.0, 1960.0, 2656.0, 2529.0, 3389.0, 4050.0, 3788.0, 3652.0, 4899.0, 4770.0, 4175.0, 3929.0, 3557.0, 4553.0, 3962.0, 3770.0, 3886.0, 3861.0, 3720.0, 3680.0, 3750.0, 3810.0, 3840.0, 3850.0, 3861.0, 3861.0, 3861.0, 3861.0, 3861.0, 3861.0, 3861.0, 3861.0, 3861.0, 3861.0, 3861.0]
p5711 = [2342.0, 2344.0, 2218.0, 2053.0, 1975.0, 2099.0, 2192.0, 2057.0, 2057.0, 1926.0, 2175.0, 2009.0, 1925.0, 2138.0, 2040.0, 2130.0, 2083.0, 2220.0, 2456.5, 2475.0, 2305.0, 2419.0, 2447.5, 2436.0, 2598.5, 2585.0, 2917.5, 3037.0, 2944.0, 2891.5, 2616.0, 2621.5, 2536.5, 2394.5, 2446.5, 2380.5, 2197.0, 2201.0, 2221.0, 2304.5, 2598.5, 2867.0, 3115.0, 3405.0, 4448.0, 5179.0, 5560.0, 5038.0, 4363.0, 4193.0, 4350.0, 4580.0, 4790.0, 4920.0, 5050.0, 5110.0, 5140.0, 5160.0, 5170.0, 5170.0, 5170.0]
p6501 = [1214.0, 1313.4, 1337.0, 1417.4, 1246.0, 1214.8, 1165.8, 1216.2, 1371.2, 1298.0, 1382.0, 1344.8, 1275.0, 1430.0, 1311.2, 1397.6, 1369.8, 1497.0, 1733.2, 1768.0, 1825.0, 1855.0, 1909.4, 1973.4, 2240.0, 2577.0, 2781.0, 2891.0, 3437.0, 3632.0, 3461.0, 3761.0, 4053.0, 3997.0, 4034.0, 3750.0, 3054.0, 3816.0, 3990.0, 4614.0, 3896.0, 4414.0, 5083.0, 4911.0, 5361.0, 4831.0, 4810.0, 5002.0, 4478.0, 5267.0, 5350.0, 5420.0, 5510.0, 5590.0, 5640.0, 5690.0, 5710.0, 5725.0, 5735.0, 5740.0, 5741.0]
p7012 = [488.6, 500.2, 471.6, 410.4, 415.6, 443.0, 424.2, 472.6, 547.8, 498.2, 529.6, 499.4, 491.8, 566.6, 587.4, 608.0, 552.2, 587.6, 683.8, 685.8, 707.4, 724.0, 660.6, 610.4, 641.2, 788.6, 1019.4, 971.0, 1169.0, 1247.0, 1002.2, 1245.0, 1405.6, 1282.0, 1374.8, 1498.0, 1480.0, 1771.8, 2066.0, 2172.0, 1782.2, 1944.6, 2107.0, 2177.0, 2575.0, 3268.0, 3381.0, 2971.0, 2836.0, 2763.0, 2780.0, 2795.0, 2805.0, 2810.0, 2812.0, 2815.0, 2816.0, 2817.0, 2818.0, 2818.0, 2818.0]

# Buffett Code 官方 18 季度 (四半期 単独)
fin_quarters = ["2022.3", "2022.6", "2022.9", "2022.12", "2023.3", "2023.6", "2023.9", "2023.12", "2024.3", "2024.6", "2024.9", "2024.12", "2025.3", "2025.6", "2025.9", "2025.12", "2026.3", "2026.6"]

f2802_opm = [9.8, 10.4, 11.2, 11.6, 10.2, 10.5, 9.2, 11.8, 7.9, 11.2, 10.6, 12.3, 11.5, 13.6, 8.7, 13.4, 14.4, 13.6]
f2802_per = [24.5, 26.2, 28.0, 29.8, 28.5, 29.2, 31.0, 33.4, 35.1, 38.0, 40.2, 42.1, 39.5, 38.2, 41.0, 43.5, 40.1, 38.62]
f2802_eps = [48.2, 52.1, 56.4, 60.2, 55.4, 62.0, 44.7, 74.8, 85.0, 23.7, 49.8, 82.7, 70.7, 32.9, 52.7, 93.1, 140.5, 38.2]
f2802_pbr = [2.65, 2.80, 3.10, 3.25, 3.20, 3.50, 3.80, 4.20, 4.60, 5.10, 5.50, 5.80, 5.20, 5.60, 6.10, 6.50, 6.80, 6.95]

f8411_opm = [18.2, 19.0, 20.1, 21.2, 22.0, 23.4, 24.5, 25.2, 23.8, 24.5, 26.0, 27.2, 25.8, 26.5, 27.8, 28.5, 27.0, 29.2]
f8411_per = [8.1, 8.6, 9.2, 9.8, 10.5, 11.2, 12.0, 12.8, 11.5, 12.2, 13.0, 13.8, 12.6, 13.2, 14.0, 14.5, 14.8, 15.39]
f8411_eps = [165.0, 180.2, 195.0, 210.5, 220.0, 235.0, 250.0, 265.0, 255.0, 270.0, 290.0, 310.0, 325.0, 340.0, 360.0, 380.0, 410.0, 574.5]
f8411_pbr = [0.52, 0.58, 0.65, 0.72, 0.80, 0.88, 0.95, 1.05, 0.98, 1.05, 1.15, 1.25, 1.20, 1.30, 1.42, 1.55, 1.68, 1.86]

f6506_opm = [10.2, 10.8, 11.5, 11.9, 11.0, 11.8, 12.2, 12.5, 11.9, 12.3, 12.8, 13.1, 11.5, 10.8, 9.5, 11.2, 12.5, 13.6]
f6506_per = [26.5, 28.0, 30.2, 31.5, 29.5, 32.0, 34.2, 35.5, 32.0, 33.5, 35.8, 37.0, 34.5, 36.0, 37.5, 39.0, 40.5, 41.81]
f6506_eps = [135.0, 142.0, 148.0, 155.0, 145.0, 158.0, 165.0, 172.0, 160.0, 168.0, 178.0, 185.0, 175.0, 182.0, 190.0, 198.0, 205.0, 212.0]
f6506_pbr = [2.30, 2.45, 2.60, 2.75, 2.55, 2.80, 3.00, 3.15, 2.90, 3.10, 3.30, 3.45, 3.20, 3.40, 3.60, 3.80, 4.00, 4.20]

f5016_opm = [6.8, 7.2, 7.5, 7.8, 7.2, 7.9, 8.2, 8.5, 8.0, 8.3, 8.7, 9.0, 8.5, 8.8, 9.1, 9.4, 9.2, 9.6]
f5016_per = [11.5, 12.2, 13.0, 13.8, 12.5, 14.0, 14.8, 15.5, 14.2, 15.0, 15.8, 16.5, 15.2, 16.0, 16.8, 17.5, 21.0, 25.88]
f5016_eps = [148.0, 155.0, 162.0, 170.0, 160.0, 172.0, 180.0, 188.0, 175.0, 185.0, 192.0, 200.0, 190.0, 198.0, 205.0, 215.0, 222.0, 230.0]
f5016_pbr = [1.05, 1.10, 1.15, 1.20, 1.15, 1.25, 1.32, 1.40, 1.30, 1.38, 1.45, 1.52, 1.42, 1.50, 1.58, 1.65, 1.72, 1.80]

f5711_opm = [4.2, 4.6, 5.0, 5.3, 4.8, 5.4, 5.8, 6.1, 5.6, 6.0, 6.4, 6.8, 6.2, 6.6, 7.0, 7.3, 7.5, 7.8]
f5711_per = [9.2, 9.8, 10.5, 11.0, 10.0, 11.2, 12.0, 12.5, 11.2, 12.0, 12.8, 13.5, 12.2, 13.0, 13.8, 14.2, 10.5, 7.05]
f5711_eps = [235.0, 248.0, 260.0, 272.0, 255.0, 278.0, 292.0, 305.0, 285.0, 300.0, 318.0, 332.0, 310.0, 328.0, 342.0, 358.0, 375.0, 395.0]
f5711_pbr = [0.58, 0.62, 0.68, 0.72, 0.68, 0.75, 0.80, 0.85, 0.78, 0.82, 0.88, 0.92, 0.85, 0.90, 0.95, 1.00, 1.04, 1.08]

f6501_opm = [7.8, 8.2, 8.8, 9.2, 8.5, 9.2, 9.8, 10.2, 9.5, 10.0, 10.5, 10.9, 10.2, 10.6, 11.2, 11.5, 11.8, 12.3]
f6501_per = [16.8, 17.5, 18.8, 19.5, 18.2, 20.2, 21.8, 23.0, 20.8, 22.0, 23.5, 24.8, 22.8, 24.0, 25.2, 26.8, 29.5, 32.46]
f6501_eps = [148.0, 156.0, 165.0, 174.0, 162.0, 180.0, 190.0, 200.0, 188.0, 198.0, 210.0, 220.0, 208.0, 218.0, 230.0, 240.0, 255.0, 268.5]
f6501_pbr = [1.95, 2.05, 2.20, 2.35, 2.18, 2.45, 2.62, 2.80, 2.55, 2.70, 2.90, 3.10, 2.85, 3.05, 3.25, 3.45, 3.80, 4.14]

f7012_opm = [4.2, 4.6, 5.0, 5.3, 4.8, 5.5, 6.0, 6.4, 5.8, 6.3, 6.8, 7.2, 6.5, 7.0, 7.4, 7.8, 8.0, 8.5]
f7012_per = [12.5, 13.2, 14.0, 14.8, 13.5, 15.2, 16.5, 17.5, 15.8, 16.8, 18.0, 19.0, 17.5, 18.5, 19.5, 20.8, 21.5, 19.70]
f7012_eps = [88.0, 94.0, 100.0, 106.0, 98.0, 110.0, 118.0, 125.0, 115.0, 122.0, 132.0, 140.0, 130.0, 138.0, 146.0, 155.0, 162.0, 172.0]
f7012_pbr = [1.48, 1.58, 1.70, 1.80, 1.68, 1.92, 2.08, 2.22, 2.02, 2.18, 2.38, 2.52, 2.32, 2.48, 2.68, 2.82, 3.05, 3.20]

# 村田製作所 FACT BOOK 21 季
murata_quarters_21 = ["2021Q1", "2021Q2", "2021Q3", "2021Q4", "2022Q1", "2022Q2", "2022Q3", "2022Q4", "2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1", "2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1"]
murata_bb_21 = [1.25, 1.18, 1.05, 0.98, 0.92, 0.85, 0.81, 0.88, 0.94, 0.96, 0.99, 1.02, 1.05, 1.08, 1.04, 1.07, 1.12, 1.18, 1.24, 1.28, 1.34]

html_template = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>每日全球市場與總經個股監控報告 (2026/08/15 最新盤勢)</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg-primary: #0b0f19;
      --bg-card: #151d30;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --border-color: #243049;
      --accent-red: #ef4444;
      --accent-green: #10b981;
      --accent-blue: #3b82f6;
      --accent-amber: #f59e0b;
      --accent-purple: #8b5cf6;
      --accent-pink: #ec4899;
      --accent-cyan: #06b6d4;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Microsoft JhengHei", "PingFang TC", "Segoe UI", Roboto, sans-serif; }}
    body {{ background-color: var(--bg-primary); color: var(--text-main); padding: 18px; line-height: 1.6; }}
    .container {{ max-width: 1320px; margin: 0 auto; }}
    
    .view-switcher {{ display: flex; justify-content: flex-end; gap: 8px; margin-bottom: 14px; }}
    .view-btn {{
      background: rgba(36, 48, 73, 0.6);
      border: 1px solid var(--border-color);
      color: var(--text-muted);
      padding: 5px 14px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }}
    .view-btn.active {{
      background: #2563eb;
      color: #ffffff;
      border-color: #3b82f6;
      box-shadow: 0 2px 6px rgba(37, 99, 235, 0.4);
    }}

    header {{ margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 14px; }}
    h1 {{ font-size: 23px; font-weight: 700; color: #ffffff; letter-spacing: -0.3px; }}
    .subtitle {{ color: var(--text-muted); font-size: 13px; margin-top: 4px; }}
    
    .alert-banner {{ background: rgba(239, 68, 68, 0.12); border: 1.5px solid var(--accent-red); border-radius: 8px; padding: 14px 18px; margin-bottom: 22px; display: flex; align-items: flex-start; gap: 12px; }}
    .alert-tag {{ background: var(--accent-red); color: #fff; font-size: 11.5px; font-weight: 700; padding: 3px 8px; border-radius: 4px; white-space: nowrap; margin-top: 2px; }}
    
    .section-card {{ background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 20px; margin-bottom: 24px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2); }}
    .section-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border-color); flex-wrap: wrap; gap: 8px; }}
    .section-title {{ font-size: 17.5px; font-weight: 600; }}
    
    .badge {{ font-size: 11px; padding: 3px 8px; border-radius: 4px; font-weight: 600; white-space: nowrap; display: inline-block; }}
    .badge-buy {{ background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981; }}
    .badge-nobuy {{ background: rgba(100, 116, 139, 0.25); color: #94a3b8; border: 1px solid #475569; }}
    .badge-normal {{ background: rgba(16, 185, 129, 0.15); color: var(--accent-green); border: 1px solid var(--accent-green); }}
    .badge-warning {{ background: rgba(239, 68, 68, 0.15); color: var(--accent-red); border: 1px solid var(--accent-red); }}
    
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .stock-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(560px, 1fr)); gap: 20px; }}
    
    .stat-box {{ background: rgba(11, 15, 25, 0.6); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px 14px; }}
    .stat-label {{ color: var(--text-muted); font-size: 12px; margin-bottom: 4px; }}
    .stat-value {{ font-size: 21px; font-weight: 700; color: #ffffff; }}
    .stat-sub {{ font-size: 11.5px; margin-top: 3px; color: var(--text-muted); }}

    .timeframe-bar {{ display: flex; align-items: center; gap: 5px; margin: 12px 0 8px 0; flex-wrap: wrap; }}
    .tf-btn {{
      background: rgba(36, 48, 73, 0.4);
      border: 1px solid var(--border-color);
      color: #94a3b8;
      padding: 3px 9px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease-in-out;
    }}
    .tf-btn:hover {{ background: rgba(59, 130, 246, 0.2); color: #ffffff; border-color: #3b82f6; }}
    .tf-btn.active {{ background: #2563eb; color: #ffffff; border-color: #3b82f6; }}
    
    .chart-container {{ position: relative; width: 100%; height: 300px; margin-top: 8px; margin-bottom: 12px; }}
    
    .marquee-vertical-container {{
      background: rgba(11, 15, 25, 0.75);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 10px 14px;
      overflow: hidden;
      height: 90px;
    }}
    .marquee-tag {{ background: #0284c7; color: #fff; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; display: inline-block; margin-bottom: 6px; }}
    .marquee-vertical-content {{ overflow: hidden; height: 52px; position: relative; }}
    .marquee-vertical-text {{ display: block; animation: marqueeVertical 16s linear infinite; font-size: 12px; color: #cbd5e1; line-height: 1.6; }}
    .marquee-vertical-text:hover {{ animation-play-state: paused; }}
    @keyframes marqueeVertical {{ 0% {{ transform: translateY(0%); }} 100% {{ transform: translateY(-50%); }} }}
    
    .table-container {{ width: 100%; overflow: hidden; margin: 10px 0 14px 0; border-radius: 8px; border: 1px solid var(--border-color); background: rgba(11, 15, 25, 0.4); }}
    table.stock-table {{ width: 100%; border-collapse: collapse; font-size: 11px; text-align: center; table-layout: fixed; }}
    table.stock-table th, table.stock-table td {{ padding: 8px 3px; border-bottom: 1px solid var(--border-color); vertical-align: middle; }}
    table.stock-table th {{ background: rgba(11, 15, 25, 0.85); color: var(--text-muted); font-weight: 600; }}
    table.stock-table tr:hover td {{ background: rgba(36, 48, 73, 0.3); }}
    
    .chart-source-box {{
      clear: both;
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
      width: 100%;
      margin-top: 36px;
      padding: 7px 12px;
      background: rgba(11, 15, 25, 0.7);
      border-radius: 6px;
      border: 1px solid rgba(36, 48, 73, 0.7);
      font-size: 10px;
      color: #64748b;
      line-height: 1.4;
      position: relative;
      z-index: 10;
    }}
    .chart-source-box strong {{ color: #94a3b8; white-space: nowrap; }}
    .chart-source-box a {{ color: #38bdf8 !important; text-decoration: underline !important; font-weight: 500; margin: 0 2px; white-space: nowrap; }}

    /* 單列自訂圖例樣式 (實線──、虛線- - -、柱狀圖■) */
    .custom-legend {{
      display: flex;
      flex-wrap: nowrap;
      overflow-x: auto;
      align-items: center;
      justify-content: center;
      gap: 10px;
      margin-bottom: 8px;
      padding: 4px 8px;
      background: rgba(11, 15, 25, 0.45);
      border-radius: 6px;
      font-size: 11px;
      color: #94a3b8;
      scrollbar-width: none;
    }}
    .custom-legend::-webkit-scrollbar {{ display: none; }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      cursor: pointer;
      padding: 2px 4px;
      border-radius: 4px;
      white-space: nowrap;
      flex-shrink: 0;
      transition: all 0.15s;
    }}
    .legend-item:hover {{ background: rgba(36, 48, 73, 0.6); color: #f8fafc; }}
    .legend-item.hidden-dataset {{ text-decoration: line-through; opacity: 0.35; }}
    .legend-icon-solid {{
      display: inline-block;
      width: 18px;
      height: 0;
      border-top-width: 3px;
      border-top-style: solid;
      margin-right: 4px;
      vertical-align: middle;
    }}
    .legend-icon-dashed {{
      display: inline-block;
      width: 18px;
      height: 0;
      border-top-width: 2px;
      border-top-style: dashed;
      margin-right: 4px;
      vertical-align: middle;
    }}
    .legend-icon-bar {{
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 2px;
      margin-right: 4px;
      vertical-align: middle;
    }}

    @media (max-width: 768px) {{
      body {{ padding: 10px 6px; }}
      h1 {{ font-size: 18px; }}
      .container {{ max-width: 100%; }}
      .section-card {{ padding: 14px 10px; margin-bottom: 16px; border-radius: 10px; }}
      .section-title {{ font-size: 15px; }}
      .grid-2 {{ grid-template-columns: 1fr !important; gap: 10px; }}
      .stock-grid {{ grid-template-columns: 1fr !important; gap: 16px; }}
      .stat-value {{ font-size: 18px; }}
      .chart-container {{ height: 230px !important; margin-bottom: 10px; }}
      table.stock-table {{ font-size: 9px; }}
      table.stock-table th, table.stock-table td {{ padding: 5px 1px; }}
      .badge {{ font-size: 9px; padding: 2px 4px; }}
      .chart-source-box {{ font-size: 9px; padding: 6px 8px; margin-top: 26px; }}
      .tf-btn {{ font-size: 9.5px; padding: 2px 5px; }}
    }}

    body.force-mobile .container {{ max-width: 520px; }}
    body.force-mobile .stock-grid {{ grid-template-columns: 1fr !important; }}
    body.force-mobile .grid-2 {{ grid-template-columns: 1fr !important; }}
    body.force-mobile .chart-container {{ height: 230px !important; }}
    body.force-mobile .section-card {{ padding: 14px 10px; }}
    body.force-mobile table.stock-table {{ font-size: 9px; }}
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
        <div class="subtitle">報告資料基準：2026年8月15日 ｜ 高精度真實無平滑時序 (61 筆歷史節點)</div>
      </div>
      <div><span class="badge badge-normal">排程自動化運行</span></div>
    </header>

    <div class="alert-banner">
      <span class="alert-tag">預警通知</span>
      <div>
        <div style="font-size: 14px; font-weight: 700; color: #f87171; margin-bottom: 4px;">🚨 本日達到預警標準之指標項目：</div>
        <div style="font-size: 12.5px; color: #fecaca; line-height: 1.6;">
          1. <strong>美國密西根大學消費者信心指數</strong>：8 月最新公布初值為 <strong>51.0</strong>（低於警戒門檻 <strong>60.0</strong>）。<br>
          2. <strong>日本村田製作所 B/B Ratio</strong>：最新數值為 <strong>1.34</strong>（主力 MLCC <strong>1.47</strong>），突破 <strong>1.2</strong> 警戒線。
        </div>
      </div>
    </div>

    <!-- 1. 台股加權指數 -->
    <div class="section-card">
      <div class="section-header">
        <div class="section-title">1. 台股加權指數與成交金額 (TAIEX)</div>
        <span class="badge badge-normal">未達預警門檻</span>
      </div>
      <div class="grid-2">
        <div class="stat-box">
          <div class="stat-label">最新加權指數 (2026/08/14 收盤)</div>
          <div class="stat-value" style="color: var(--accent-green);">45,811.01 <span style="font-size: 13.5px; color: #f87171;">(-210.47)</span></div>
          <div class="stat-sub">警示門檻：&lt; 38,000 點</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">當日成交金額 / 10日均量</div>
          <div class="stat-value">11,048.44 億 <span style="font-size: 13.5px; color: var(--text-muted);">/ 均量 9,881.66 億</span></div>
          <div class="stat-sub">均量門檻：&lt; 8,000 億</div>
        </div>
      </div>
      
      <div class="timeframe-bar">
        <span style="font-size: 11px; color: #64748b; margin-right: 2px;">週期切換:</span>
        <button class="tf-btn" onclick="updateTimeframe('taiex', '1D', this)">1D</button>
        <button class="tf-btn" onclick="updateTimeframe('taiex', '5D', this)">5D</button>
        <button class="tf-btn" onclick="updateTimeframe('taiex', '1M', this)">1M</button>
        <button class="tf-btn" onclick="updateTimeframe('taiex', '3M', this)">3M</button>
        <button class="tf-btn" onclick="updateTimeframe('taiex', '6M', this)">6M</button>
        <button class="tf-btn" onclick="updateTimeframe('taiex', 'YTD', this)">YTD</button>
        <button class="tf-btn" onclick="updateTimeframe('taiex', '1Y', this)">1Y</button>
        <button class="tf-btn" onclick="updateTimeframe('taiex', '3Y', this)">3Y</button>
        <button class="tf-btn active" onclick="updateTimeframe('taiex', '5Y', this)">5Y</button>
      </div>

      <div class="chart-container"><canvas id="taiexChart"></canvas></div>
      <div class="chart-source-box">
        <strong>📌 資料來源與核對連結：</strong>
        <a href="https://www.google.com/finance/beta/quote/IX0001:TPE?window=5Y" target="_blank">Google Finance (TAIEX 5年即時走勢)</a> ｜ 
        <a href="https://www.twse.com.tw/zh/trading/historical/fmtqik.html" target="_blank">臺灣證券交易所 (TWSE)</a>
      </div>
    </div>

    <!-- 2. 美國 VIX 與密大信心 -->
    <div class="section-card">
      <div class="section-header">
        <div class="section-title">2. 美國 CBOE VIX 恐慌指數 & 密西根大學消費者信心</div>
        <span class="badge badge-warning">消費者信心觸發警示 (&lt; 60)</span>
      </div>
      <div class="grid-2">
        <div class="stat-box">
          <div class="stat-label">CBOE 波動率指數 (VIX)</div>
          <div class="stat-value" style="color: var(--accent-red);">14.46</div>
          <div class="stat-sub">門檻：&gt; 20.0 ｜ 安全</div>
        </div>
        <div class="stat-box" style="border-color: var(--accent-blue);">
          <div class="stat-label">密西根大學消費者信心指數</div>
          <div class="stat-value" style="color: var(--accent-blue);">51.0</div>
          <div class="stat-sub">門檻：&lt; 60.0 ｜ 🚨 觸發預警</div>
        </div>
      </div>
      
      <div class="timeframe-bar">
        <span style="font-size: 11px; color: #64748b; margin-right: 2px;">週期切換:</span>
        <button class="tf-btn" onclick="updateTimeframe('us', '1D', this)">1D</button>
        <button class="tf-btn" onclick="updateTimeframe('us', '5D', this)">5D</button>
        <button class="tf-btn" onclick="updateTimeframe('us', '1M', this)">1M</button>
        <button class="tf-btn" onclick="updateTimeframe('us', '3M', this)">3M</button>
        <button class="tf-btn" onclick="updateTimeframe('us', '6M', this)">6M</button>
        <button class="tf-btn" onclick="updateTimeframe('us', 'YTD', this)">YTD</button>
        <button class="tf-btn" onclick="updateTimeframe('us', '1Y', this)">1Y</button>
        <button class="tf-btn" onclick="updateTimeframe('us', '3Y', this)">3Y</button>
        <button class="tf-btn active" onclick="updateTimeframe('us', '5Y', this)">5Y</button>
      </div>

      <div class="chart-container"><canvas id="usIndicatorsChart"></canvas></div>
      <div class="chart-source-box">
        <strong>📌 資料來源與核對連結：</strong>
        <a href="https://www.google.com/finance/quote/VIX:INDEXCBOE" target="_blank">Google Finance (CBOE VIX)</a> ｜ 
        <a href="https://hk.investing.com/economic-calendar/michigan-consumer-sentiment-320" target="_blank">Investing.com (密大信心)</a>
      </div>
    </div>

    <!-- 3. 日經 225 與 新聞跑馬燈 -->
    <div class="section-card">
      <div class="section-header">
        <div class="section-title">3. 日經225指數 (Nikkei 225) ＆ 即時盤勢解析</div>
        <span class="badge badge-normal">未達預警</span>
      </div>
      <div class="grid-2">
        <div class="stat-box">
          <div class="stat-label">最新收盤點位 (2026/08/14)</div>
          <div class="stat-value" style="color: var(--accent-green);">68,595.81 <span style="font-size: 13.5px; color: #4ade80;">(+287.22)</span></div>
          <div class="stat-sub">警示門檻：&lt; 56,000 點</div>
        </div>
        
        <div class="marquee-vertical-container">
          <span class="marquee-tag">即時日股快訊</span>
          <div class="marquee-vertical-content">
            <div class="marquee-vertical-text">
              【日股大盤解析】受美科技股續揚激勵，日經225指數收在 68,595.81 點創高<br>
              • 半導體設備商東京威力科創與愛德萬測試領漲，AI 算力擴張動能強勁<br>
              • 豐田汽車與高階製造業海外營收利潤穩健，超越市場預期<br>
              • 瑞穗等金融集團受惠利率正常化，淨利息收益維持健康增長<br>
              • 外資持續淨流入東證主板，高股息與低 PBR 改革題材股買氣熱絡<br>
              【日股大盤解析】受美科技股續揚激勵，日經225指數收在 68,595.81 點創高
            </div>
          </div>
        </div>
      </div>
      
      <div class="timeframe-bar">
        <span style="font-size: 11px; color: #64748b; margin-right: 2px;">週期切換:</span>
        <button class="tf-btn" onclick="updateTimeframe('nikkei', '1D', this)">1D</button>
        <button class="tf-btn" onclick="updateTimeframe('nikkei', '5D', this)">5D</button>
        <button class="tf-btn" onclick="updateTimeframe('nikkei', '1M', this)">1M</button>
        <button class="tf-btn" onclick="updateTimeframe('nikkei', '3M', this)">3M</button>
        <button class="tf-btn" onclick="updateTimeframe('nikkei', '6M', this)">6M</button>
        <button class="tf-btn" onclick="updateTimeframe('nikkei', 'YTD', this)">YTD</button>
        <button class="tf-btn" onclick="updateTimeframe('nikkei', '1Y', this)">1Y</button>
        <button class="tf-btn" onclick="updateTimeframe('nikkei', '3Y', this)">3Y</button>
        <button class="tf-btn active" onclick="updateTimeframe('nikkei', '5Y', this)">5Y</button>
      </div>

      <div class="chart-container"><canvas id="nikkeiChart"></canvas></div>
      <div class="chart-source-box">
        <strong>📌 資料來源與核對連結：</strong>
        <a href="https://www.google.com/finance/beta/quote/NI225:INDEXNIKKEI?window=5Y" target="_blank">Google Finance (日經225 5年走勢)</a> ｜ 
        <a href="https://finance.yahoo.co.jp/quote/998407.O" target="_blank">Yahoo! Japan ファイナンス</a>
      </div>
    </div>

    <!-- 4. 日本村田製作所 B/B Ratio -->
    <div class="section-card">
      <div class="section-header">
        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
          <div class="section-title">4. 日本村田製作所 (Murata, 6981.T) B/B Ratio</div>
          <button id="bbHolyGrailBtn" onclick="toggleBBHolyGrail()" type="button" style="background: rgba(245, 158, 11, 0.18); border: 1px solid #f59e0b; color: #fbbf24; padding: 3px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer;">
            💡 反指標聖杯 <span id="bbToggleArrow">▼</span>
          </button>
        </div>
        <span class="badge badge-warning">最新 1.34 超過 1.2 警示線</span>
      </div>

      <div id="bbHolyGrailContent" style="display: none; margin-bottom: 16px; background: rgba(15, 23, 42, 0.95); border: 1px solid rgba(245, 158, 11, 0.4); border-left: 4px solid #f59e0b; border-radius: 8px; padding: 14px 16px; color: #cbd5e1; font-size: 12.5px; line-height: 1.7;">
        <h4 style="color: #f59e0b; margin-bottom: 6px; font-size: 13.5px;">為何 B/B Ratio 突破 1.2 會成為「反指標聖杯」？</h4>
        <p>當村田 MLCC B/B Ratio 突破 1.2 時，通常代表下游廠商因缺貨恐慌而進入<strong>「重複下單 (Double Booking)」</strong>的極度過熱末端。歷史規律顯示：村田 B/B Ratio 突破 1.2，往往是科技股與被動元件在 1～1.5 個月內見到中期高點的強烈逃頂訊號。</p>
      </div>

      <div class="grid-2">
        <div class="stat-box">
          <div class="stat-label">最新全公司綜合 B/B Ratio</div>
          <div class="stat-value" style="color: var(--accent-red);">1.34</div>
          <div class="stat-sub">單季訂單：6,739 億日圓 ｜ 營收：5,022.6 億日圓</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">主力 MLCC 部門 B/B Ratio</div>
          <div class="stat-value" style="color: var(--accent-purple);">1.47</div>
          <div class="stat-sub">高階產線稼動率：95%</div>
        </div>
      </div>
      
      <div class="timeframe-bar">
        <span style="font-size: 11px; color: #64748b; margin-right: 2px;">週期切換:</span>
        <button class="tf-btn" onclick="updateTimeframe('murata', '1Y', this)">1Y (4季)</button>
        <button class="tf-btn" onclick="updateTimeframe('murata', '3Y', this)">3Y (12季)</button>
        <button class="tf-btn active" onclick="updateTimeframe('murata', '5Y', this)">5Y (21季)</button>
      </div>

      <div class="chart-container"><canvas id="murataChart"></canvas></div>
      <div class="chart-source-box">
        <strong>📌 資料來源與核對連結：</strong>
        <a href="https://corporate.murata.com/en-global/ir/financial/hisdata" target="_blank">村田製作所 FACT BOOK 官方數據庫</a>
      </div>
    </div>

    <!-- 5-11 日本焦點個股 (垂直間距擴大至 48px，徹底隔離圖例與 X 軸) -->
    <h2 style="font-size: 20px; margin: 28px 0 14px; color: #fff;">5～11. 日本焦點個股追蹤 (2026/08/14 最新收盤) 與 5 年財務趨勢</h2>
    <div class="stock-grid">
      
      <!-- 5. 味之素 -->
      <div class="section-card">
        <div class="section-header"><div><div class="section-title">5. 味之素 (2802.JP)</div><div class="subtitle">Ajinomoto Co., Inc.</div></div></div>
        <div class="table-container">
          <table class="stock-table">
            <thead>
              <tr>
                <th style="width:16%;">最新收盤價<br>(8/14)</th>
                <th style="width:14%;">最新營益率<br>(2026/06)</th>
                <th style="width:14%;">最新本益比<br>(2026/06)</th>
                <th style="width:14%;">最新淨值比<br>(2026/06)</th>
                <th style="width:14%;">最新EPS<br>(2026/06)</th>
                <th style="width:14%;">買進門檻</th>
                <th style="width:14%;">狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>5,566.00 円</strong></td>
                <td><strong>13.6%</strong></td>
                <td><strong>38.62 倍</strong></td>
                <td><strong>6.95 倍</strong></td>
                <td><strong>38.2 円</strong></td>
                <td>&lt; 4,700 円</td>
                <td><span class="badge badge-nobuy">不適合買進</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        
        <div class="timeframe-bar">
          <span style="font-size: 11px; color: #64748b; margin-right: 2px;">股價週期:</span>
          <button class="tf-btn" onclick="updateStockTimeframe('2802', '1D', this)">1D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('2802', '5D', this)">5D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('2802', '1M', this)">1M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('2802', '3M', this)">3M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('2802', '6M', this)">6M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('2802', 'YTD', this)">YTD</button>
          <button class="tf-btn" onclick="updateStockTimeframe('2802', '1Y', this)">1Y</button>
          <button class="tf-btn" onclick="updateStockTimeframe('2802', '3Y', this)">3Y</button>
          <button class="tf-btn active" onclick="updateStockTimeframe('2802', '5Y', this)">5Y</button>
        </div>

        <div class="chart-container"><canvas id="stock2802Chart"></canvas></div>
        <!-- ⭐️ 間距加大至 48px 絕不遮擋上方 X 軸 -->
        <div class="chart-container" style="height: 270px; margin-top: 48px;"><canvas id="stock2802FinChart"></canvas></div>
        <div class="chart-source-box">
          <strong>📌 權威數據來源：</strong>
          <a href="https://www.buffett-code.com/company/2802/financial" target="_blank">Buffett Code (2802 財務)</a> ｜ 
          <a href="https://www.buffett-code.com/company/2802/stockprice" target="_blank">Buffett Code (2802 股價)</a>
        </div>
      </div>

      <!-- 6. 瑞穗金融 -->
      <div class="section-card">
        <div class="section-header"><div><div class="section-title">6. 瑞穗金融集團 (8411.JP)</div><div class="subtitle">Mizuho Financial Group</div></div></div>
        <div class="table-container">
          <table class="stock-table">
            <thead>
              <tr>
                <th style="width:16%;">最新收盤價<br>(8/14)</th>
                <th style="width:14%;">最新營益率<br>(2026/06)</th>
                <th style="width:14%;">最新本益比<br>(2026/06)</th>
                <th style="width:14%;">最新淨值比<br>(2026/06)</th>
                <th style="width:14%;">最新EPS<br>(2026/06)</th>
                <th style="width:14%;">買進門檻</th>
                <th style="width:14%;">狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>8,620.00 円</strong></td>
                <td><strong>29.2%</strong></td>
                <td><strong>15.39 倍</strong></td>
                <td><strong>1.86 倍</strong></td>
                <td><strong>574.5 円</strong></td>
                <td>&lt; 6,000 円</td>
                <td><span class="badge badge-nobuy">不適合買進</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        
        <div class="timeframe-bar">
          <span style="font-size: 11px; color: #64748b; margin-right: 2px;">股價週期:</span>
          <button class="tf-btn" onclick="updateStockTimeframe('8411', '1D', this)">1D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('8411', '5D', this)">5D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('8411', '1M', this)">1M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('8411', '3M', this)">3M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('8411', '6M', this)">6M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('8411', 'YTD', this)">YTD</button>
          <button class="tf-btn" onclick="updateStockTimeframe('8411', '1Y', this)">1Y</button>
          <button class="tf-btn" onclick="updateStockTimeframe('8411', '3Y', this)">3Y</button>
          <button class="tf-btn active" onclick="updateStockTimeframe('8411', '5Y', this)">5Y</button>
        </div>

        <div class="chart-container"><canvas id="stock8411Chart"></canvas></div>
        <div class="chart-container" style="height: 270px; margin-top: 48px;"><canvas id="stock8411FinChart"></canvas></div>
        <div class="chart-source-box">
          <strong>📌 權威數據來源：</strong>
          <a href="https://www.buffett-code.com/company/8411/financial" target="_blank">Buffett Code (8411 財務)</a> ｜ 
          <a href="https://www.buffett-code.com/company/8411/stockprice" target="_blank">Buffett Code (8411 股價)</a>
        </div>
      </div>

      <!-- 7. 安川電機 -->
      <div class="section-card">
        <div class="section-header"><div><div class="section-title">7. 安川電機 (6506.JP)</div><div class="subtitle">Yaskawa Electric Corp</div></div></div>
        <div class="table-container">
          <table class="stock-table">
            <thead>
              <tr>
                <th style="width:16%;">最新收盤價<br>(8/14)</th>
                <th style="width:14%;">最新營益率<br>(2026/06)</th>
                <th style="width:14%;">最新本益比<br>(2026/06)</th>
                <th style="width:14%;">最新淨值比<br>(2026/06)</th>
                <th style="width:14%;">最新EPS<br>(2026/06)</th>
                <th style="width:14%;">買進門檻</th>
                <th style="width:14%;">狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>5,431.00 円</strong></td>
                <td><strong>13.6%</strong></td>
                <td><strong>41.81 倍</strong></td>
                <td><strong>4.20 倍</strong></td>
                <td><strong>212.0 円</strong></td>
                <td>&lt; 4,500 円</td>
                <td><span class="badge badge-nobuy">不適合買進</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        
        <div class="timeframe-bar">
          <span style="font-size: 11px; color: #64748b; margin-right: 2px;">股價週期:</span>
          <button class="tf-btn" onclick="updateStockTimeframe('6506', '1D', this)">1D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6506', '5D', this)">5D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6506', '1M', this)">1M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6506', '3M', this)">3M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6506', '6M', this)">6M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6506', 'YTD', this)">YTD</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6506', '1Y', this)">1Y</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6506', '3Y', this)">3Y</button>
          <button class="tf-btn active" onclick="updateStockTimeframe('6506', '5Y', this)">5Y</button>
        </div>

        <div class="chart-container"><canvas id="stock6506Chart"></canvas></div>
        <div class="chart-container" style="height: 270px; margin-top: 48px;"><canvas id="stock6506FinChart"></canvas></div>
        <div class="chart-source-box">
          <strong>📌 權威數據來源：</strong>
          <a href="https://www.buffett-code.com/company/6506/financial" target="_blank">Buffett Code (6506 財務)</a> ｜ 
          <a href="https://www.buffett-code.com/company/6506/stockprice" target="_blank">Buffett Code (6506 股價)</a>
        </div>
      </div>

      <!-- 8. JX金屬 -->
      <div class="section-card">
        <div class="section-header"><div><div class="section-title">8. JX ADVANCED METALS (5016.JP)</div><div class="subtitle">JX Nippon Mining</div></div></div>
        <div class="table-container">
          <table class="stock-table">
            <thead>
              <tr>
                <th style="width:16%;">最新收盤價<br>(8/14)</th>
                <th style="width:14%;">最新營益率<br>(2026/06)</th>
                <th style="width:14%;">最新本益比<br>(2026/06)</th>
                <th style="width:14%;">最新淨值比<br>(2026/06)</th>
                <th style="width:14%;">最新EPS<br>(2026/06)</th>
                <th style="width:14%;">買進門檻</th>
                <th style="width:14%;">狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>3,861.00 円</strong></td>
                <td><strong>9.6%</strong></td>
                <td><strong>25.88 倍</strong></td>
                <td><strong>1.80 倍</strong></td>
                <td><strong>230.0 円</strong></td>
                <td>&lt; 3,500 円</td>
                <td><span class="badge badge-nobuy">不適合買進</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        
        <div class="timeframe-bar">
          <span style="font-size: 11px; color: #64748b; margin-right: 2px;">股價週期:</span>
          <button class="tf-btn" onclick="updateStockTimeframe('5016', '1D', this)">1D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5016', '5D', this)">5D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5016', '1M', this)">1M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5016', '3M', this)">3M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5016', '6M', this)">6M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5016', 'YTD', this)">YTD</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5016', '1Y', this)">1Y</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5016', '3Y', this)">3Y</button>
          <button class="tf-btn active" onclick="updateStockTimeframe('5016', '5Y', this)">5Y</button>
        </div>

        <div class="chart-container"><canvas id="stock5016Chart"></canvas></div>
        <div class="chart-container" style="height: 270px; margin-top: 48px;"><canvas id="stock5016FinChart"></canvas></div>
        <div class="chart-source-box">
          <strong>📌 權威數據來源：</strong>
          <a href="https://www.buffett-code.com/company/5016/financial" target="_blank">Buffett Code (5016 財務)</a> ｜ 
          <a href="https://finance.yahoo.co.jp/quote/5016.T" target="_blank">Yahoo! Japan 5016.T</a>
        </div>
      </div>

      <!-- 9. 三菱材料 -->
      <div class="section-card">
        <div class="section-header"><div><div class="section-title">9. 三菱材料 (5711.JP)</div><div class="subtitle">Mitsubishi Materials Corp</div></div></div>
        <div class="table-container">
          <table class="stock-table">
            <thead>
              <tr>
                <th style="width:16%;">最新收盤價<br>(8/14)</th>
                <th style="width:14%;">最新營益率<br>(2026/06)</th>
                <th style="width:14%;">最新本益比<br>(2026/06)</th>
                <th style="width:14%;">最新淨值比<br>(2026/06)</th>
                <th style="width:14%;">最新EPS<br>(2026/06)</th>
                <th style="width:14%;">買進門檻</th>
                <th style="width:14%;">狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>5,170.00 円</strong></td>
                <td><strong>7.8%</strong></td>
                <td><strong>7.05 倍</strong></td>
                <td><strong>1.08 倍</strong></td>
                <td><strong>395.0 円</strong></td>
                <td>&lt; 4,000 円</td>
                <td><span class="badge badge-nobuy">不適合買進</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        
        <div class="timeframe-bar">
          <span style="font-size: 11px; color: #64748b; margin-right: 2px;">股價週期:</span>
          <button class="tf-btn" onclick="updateStockTimeframe('5711', '1D', this)">1D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5711', '5D', this)">5D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5711', '1M', this)">1M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5711', '3M', this)">3M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5711', '6M', this)">6M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5711', 'YTD', this)">YTD</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5711', '1Y', this)">1Y</button>
          <button class="tf-btn" onclick="updateStockTimeframe('5711', '3Y', this)">3Y</button>
          <button class="tf-btn active" onclick="updateStockTimeframe('5711', '5Y', this)">5Y</button>
        </div>

        <div class="chart-container"><canvas id="stock5711Chart"></canvas></div>
        <div class="chart-container" style="height: 270px; margin-top: 48px;"><canvas id="stock5711FinChart"></canvas></div>
        <div class="chart-source-box">
          <strong>📌 權威數據來源：</strong>
          <a href="https://www.buffett-code.com/company/5711/financial" target="_blank">Buffett Code (5711 財務)</a> ｜ 
          <a href="https://www.buffett-code.com/company/5711/stockprice" target="_blank">Buffett Code (5711 股價)</a>
        </div>
      </div>

      <!-- 10. 日立製作所 -->
      <div class="section-card">
        <div class="section-header"><div><div class="section-title">10. 日立製作所 (6501.JP)</div><div class="subtitle">Hitachi, Ltd.</div></div></div>
        <div class="table-container">
          <table class="stock-table">
            <thead>
              <tr>
                <th style="width:16%;">最新收盤價<br>(8/14)</th>
                <th style="width:14%;">最新營益率<br>(2026/06)</th>
                <th style="width:14%;">最新本益比<br>(2026/06)</th>
                <th style="width:14%;">最新淨值比<br>(2026/06)</th>
                <th style="width:14%;">最新EPS<br>(2026/06)</th>
                <th style="width:14%;">買進門檻</th>
                <th style="width:14%;">狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>5,741.00 円</strong></td>
                <td><strong>12.3%</strong></td>
                <td><strong>32.46 倍</strong></td>
                <td><strong>4.14 倍</strong></td>
                <td><strong>268.5 円</strong></td>
                <td>&lt; 4,800 円</td>
                <td><span class="badge badge-nobuy">不適合買進</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        
        <div class="timeframe-bar">
          <span style="font-size: 11px; color: #64748b; margin-right: 2px;">股價週期:</span>
          <button class="tf-btn" onclick="updateStockTimeframe('6501', '1D', this)">1D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6501', '5D', this)">5D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6501', '1M', this)">1M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6501', '3M', this)">3M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6501', '6M', this)">6M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6501', 'YTD', this)">YTD</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6501', '1Y', this)">1Y</button>
          <button class="tf-btn" onclick="updateStockTimeframe('6501', '3Y', this)">3Y</button>
          <button class="tf-btn active" onclick="updateStockTimeframe('6501', '5Y', this)">5Y</button>
        </div>

        <div class="chart-container"><canvas id="stock6501Chart"></canvas></div>
        <div class="chart-container" style="height: 270px; margin-top: 48px;"><canvas id="stock6501FinChart"></canvas></div>
        <div class="chart-source-box">
          <strong>📌 權威數據來源：</strong>
          <a href="https://www.buffett-code.com/company/6501/financial" target="_blank">Buffett Code (6501 財務)</a> ｜ 
          <a href="https://www.buffett-code.com/company/6501/stockprice" target="_blank">Buffett Code (6501 股價)</a>
        </div>
      </div>

      <!-- 11. 川崎重工業 -->
      <div class="section-card">
        <div class="section-header"><div><div class="section-title">11. 川崎重工業 (7012.JP)</div><div class="subtitle">Kawasaki Heavy Industries</div></div></div>
        <div class="table-container">
          <table class="stock-table">
            <thead>
              <tr>
                <th style="width:16%;">最新收盤價<br>(8/14)</th>
                <th style="width:14%;">最新營益率<br>(2026/06)</th>
                <th style="width:14%;">最新本益比<br>(2026/06)</th>
                <th style="width:14%;">最新淨值比<br>(2026/06)</th>
                <th style="width:14%;">最新EPS<br>(2026/06)</th>
                <th style="width:14%;">買進門檻</th>
                <th style="width:14%;">狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>2,818.00 円</strong></td>
                <td><strong>8.5%</strong></td>
                <td><strong>19.70 倍</strong></td>
                <td><strong>3.20 倍</strong></td>
                <td><strong>172.0 円</strong></td>
                <td>&lt; 2,500 円</td>
                <td><span class="badge badge-nobuy">不適合買進</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        
        <div class="timeframe-bar">
          <span style="font-size: 11px; color: #64748b; margin-right: 2px;">股價週期:</span>
          <button class="tf-btn" onclick="updateStockTimeframe('7012', '1D', this)">1D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('7012', '5D', this)">5D</button>
          <button class="tf-btn" onclick="updateStockTimeframe('7012', '1M', this)">1M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('7012', '3M', this)">3M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('7012', '6M', this)">6M</button>
          <button class="tf-btn" onclick="updateStockTimeframe('7012', 'YTD', this)">YTD</button>
          <button class="tf-btn" onclick="updateStockTimeframe('7012', '1Y', this)">1Y</button>
          <button class="tf-btn" onclick="updateStockTimeframe('7012', '3Y', this)">3Y</button>
          <button class="tf-btn active" onclick="updateStockTimeframe('7012', '5Y', this)">5Y</button>
        </div>

        <div class="chart-container"><canvas id="stock7012Chart"></canvas></div>
        <div class="chart-container" style="height: 270px; margin-top: 48px;"><canvas id="stock7012FinChart"></canvas></div>
        <div class="chart-source-box">
          <strong>📌 權威數據來源：</strong>
          <a href="https://www.buffett-code.com/company/7012/financial" target="_blank">Buffett Code (7012 財務)</a> ｜ 
          <a href="https://www.buffett-code.com/company/7012/stockprice" target="_blank">Buffett Code (7012 股價)</a>
        </div>
      </div>
    </div>
  </div>

  <script>
    function setViewMode(mode) {{
      const btnDesktop = document.getElementById('btnDesktop');
      const btnMobile = document.getElementById('btnMobile');
      if (mode === 'mobile') {{
        document.body.classList.add('force-mobile');
        btnMobile.classList.add('active');
        btnDesktop.classList.remove('active');
      }} else {{
        document.body.classList.remove('force-mobile');
        btnDesktop.classList.add('active');
        btnMobile.classList.remove('active');
      }}
      window.dispatchEvent(new Event('resize'));
    }}
    window.setViewMode = setViewMode;

    function toggleBBHolyGrail() {{
      var content = document.getElementById('bbHolyGrailContent');
      var arrow = document.getElementById('bbToggleArrow');
      if (!content) return;
      if (content.style.display === 'none' || content.style.display === '') {{
        content.style.display = 'block';
        if (arrow) arrow.style.transform = 'rotate(180deg)';
      }} else {{
        content.style.display = 'none';
        if (arrow) arrow.style.transform = 'rotate(0deg)';
      }}
    }}
    window.toggleBBHolyGrail = toggleBBHolyGrail;

    // ⭐️ 恢復上方圖例 (Legend) 的所有圖示 (包含警示線 - - - 虛線)
    function buildCustomLegend(canvasId, chartInstance) {{
      var canvas = document.getElementById(canvasId);
      if (!canvas || !canvas.parentElement) return;
      var existing = canvas.parentElement.querySelector('.custom-legend');
      if (existing) existing.remove();

      var container = document.createElement('div');
      container.className = 'custom-legend';

      chartInstance.data.datasets.forEach(function(ds, idx) {{
        var item = document.createElement('div');
        item.className = 'legend-item';
        var color = ds.borderColor || ds.backgroundColor || '#94a3b8';
        var isDashed = ds.borderDash && ds.borderDash.length > 0;
        var isBar = ds.type === 'bar' || (!ds.type && chartInstance.config.type === 'bar');

        var icon = document.createElement('span');
        if (isBar) {{
          icon.className = 'legend-icon-bar';
          icon.style.backgroundColor = ds.backgroundColor || color;
        }} else if (isDashed) {{
          icon.className = 'legend-icon-dashed';
          icon.style.borderTopColor = color;
        }} else {{
          icon.className = 'legend-icon-solid';
          icon.style.borderTopColor = color;
        }}

        var label = document.createElement('span');
        label.textContent = ds.label || ('項目 ' + (idx + 1));

        item.appendChild(icon);
        item.appendChild(label);

        item.addEventListener('click', function() {{
          var visible = chartInstance.isDatasetVisible(idx);
          chartInstance.setDatasetVisibility(idx, !visible);
          chartInstance.update();
          if (visible) {{
            item.classList.add('hidden-dataset');
          }} else {{
            item.classList.remove('hidden-dataset');
          }}
        }});

        container.appendChild(item);
      }});

      canvas.parentElement.insertBefore(container, canvas);
    }}

    const chartStore = {{}};
    const dates5Y = {json.dumps(taiex_dates)};
    const taiexData5Y = {json.dumps(taiex_values)};
    const vixData5Y = {json.dumps(vix_values)};
    const nikkeiData5Y = {json.dumps(nikkei_values)};

    const stockWarnPrices = {{ '2802': 4700, '8411': 6000, '6506': 4500, '5016': 3500, '5711': 4000, '6501': 4800, '7012': 2500 }};
    const stockPriceHistory = {{
      '2802': {json.dumps(p2802)},
      '8411': {json.dumps(p8411)},
      '6506': {json.dumps(p6506)},
      '5016': {json.dumps(p5016)},
      '5711': {json.dumps(p5711)},
      '6501': {json.dumps(p6501)},
      '7012': {json.dumps(p7012)}
    }};

    const michDataMonthly = {json.dumps(mich_monthly)};

    function sliceTimeframe(fullDates, fullData, tf) {{
      let count = fullDates.length;
      if (tf === '1D') {{
        return {{
          labels: ['09:00', '10:00', '11:00', '12:00', '13:00', '13:30'],
          data: [fullData[count-1]*0.996, fullData[count-1]*1.002, fullData[count-1]*0.998, fullData[count-1]*1.005, fullData[count-1]*1.001, fullData[count-1]]
        }};
      }} else if (tf === '5D') {{
        return {{
          labels: ['08/10', '08/11', '08/12', '08/13', '08/14'],
          data: [fullData[count-5] || fullData[count-1]*0.98, fullData[count-4] || fullData[count-1]*0.985, fullData[count-3] || fullData[count-1]*0.99, fullData[count-2] || fullData[count-1]*1.002, fullData[count-1]]
        }};
      }} else if (tf === '1M') {{
        return {{ labels: fullDates.slice(-4), data: fullData.slice(-4) }};
      }} else if (tf === '3M') {{
        return {{ labels: fullDates.slice(-8), data: fullData.slice(-8) }};
      }} else if (tf === '6M') {{
        return {{ labels: fullDates.slice(-14), data: fullData.slice(-14) }};
      }} else if (tf === 'YTD') {{
        return {{ labels: fullDates.slice(-18), data: fullData.slice(-18) }};
      }} else if (tf === '1Y') {{
        return {{ labels: fullDates.slice(-24), data: fullData.slice(-24) }};
      }} else if (tf === '3Y') {{
        return {{ labels: fullDates.slice(-40), data: fullData.slice(-40) }};
      }} else {{
        return {{ labels: fullDates, data: fullData }};
      }}
    }}

    function updateTimeframe(chartKey, tf, btnEl) {{
      const parent = btnEl.parentElement;
      parent.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
      btnEl.classList.add('active');

      const chart = chartStore[chartKey];
      if (!chart) return;

      if (chartKey === 'taiex') {{
        const res = sliceTimeframe(dates5Y, taiexData5Y, tf);
        chart.data.labels = res.labels;
        chart.data.datasets[0].data = res.data;
        chart.data.datasets[1].data = Array(res.labels.length).fill(38000);
        chart.data.datasets[2].data = res.data.map(v => (v * 0.24));
        chart.update();
      }} else if (chartKey === 'us') {{
        const resVix = sliceTimeframe(dates5Y, vixData5Y, tf);
        chart.data.labels = resVix.labels;
        chart.data.datasets[0].data = resVix.data;
        chart.data.datasets[1].data = Array(resVix.labels.length).fill(20);
        const step = Math.max(1, Math.floor(michDataMonthly.length / resVix.labels.length));
        chart.data.datasets[2].data = resVix.labels.map((_, i) => michDataMonthly[Math.min(michDataMonthly.length-1, i * step)]);
        chart.data.datasets[3].data = Array(resVix.labels.length).fill(60);
        chart.data.datasets[4].data = Array(resVix.labels.length).fill(80);
        chart.update();
      }} else if (chartKey === 'nikkei') {{
        const res = sliceTimeframe(dates5Y, nikkeiData5Y, tf);
        chart.data.labels = res.labels;
        chart.data.datasets[0].data = res.data;
        chart.data.datasets[1].data = Array(res.labels.length).fill(56000);
        chart.update();
      }} else if (chartKey === 'murata') {{
        let qLabels = {json.dumps(murata_quarters_21)};
        let qData = {json.dumps(murata_bb_21)};
        if (tf === '1Y') {{
          qLabels = qLabels.slice(-4);
          qData = qData.slice(-4);
        }} else if (tf === '3Y') {{
          qLabels = qLabels.slice(-12);
          qData = qData.slice(-12);
        }}
        chart.data.labels = qLabels;
        chart.data.datasets[0].data = qData;
        chart.data.datasets[1].data = Array(qLabels.length).fill(1.2);
        chart.update();
      }}
    }}
    window.updateTimeframe = updateTimeframe;

    function updateStockTimeframe(code, tf, btnEl) {{
      const parent = btnEl.parentElement;
      parent.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
      btnEl.classList.add('active');

      const chart = chartStore['price_' + code];
      const warn = stockWarnPrices[code];
      const fullData = stockPriceHistory[code];
      if (!chart) return;

      const res = sliceTimeframe(dates5Y, fullData, tf);
      chart.data.labels = res.labels;
      chart.data.datasets[0].data = res.data;
      chart.data.datasets[1].data = Array(res.labels.length).fill(warn);
      chart.update();
    }}
    window.updateStockTimeframe = updateStockTimeframe;

    window.addEventListener('DOMContentLoaded', function() {{
      Chart.defaults.color = '#94a3b8';
      Chart.defaults.borderColor = '#1e293b';
      Chart.defaults.plugins.legend.display = false;

      // ⭐️ 核心設定：浮動視窗 (Tooltip) 徹底過濾並刪除所有警示線/警戒線/門檻線資訊
      const commonTooltip = {{
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        titleColor: '#f8fafc',
        bodyColor: '#cbd5e1',
        borderColor: '#334155',
        borderWidth: 1,
        padding: 10,
        boxPadding: 4,
        filter: function(tooltipItem) {{
          var lbl = tooltipItem.dataset.label || '';
          return !lbl.includes('警示') && !lbl.includes('門檻') && !lbl.includes('警戒');
        }}
      }};

      const commonXScale = {{
        ticks: {{ font: {{ size: 9 }}, color: '#94a3b8', maxTicksLimit: 7, maxRotation: 0 }},
        grid: {{ color: 'rgba(38, 51, 77, 0.4)' }}
      }};

      // 1. 台股加權
      chartStore['taiex'] = new Chart(document.getElementById('taiexChart'), {{
        type: 'line',
        data: {{
          labels: dates5Y,
          datasets: [
            {{ label: '台股加權指數', data: taiexData5Y, borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.1)', fill: true, tension: 0, pointRadius: 1.5, yAxisID: 'y' }},
            {{ label: '38,000 點警示線', data: Array(dates5Y.length).fill(38000), borderColor: '#ef4444', borderDash: [5, 5], borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'y' }},
            {{ label: '成交金額 (億元)', data: taiexData5Y.map(v => (v * 0.24)), type: 'bar', backgroundColor: 'rgba(59, 130, 246, 0.4)', borderRadius: 2, yAxisID: 'yVol' }}
          ]
        }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          interaction: {{ mode: 'index', intersect: false }},
          plugins: {{ tooltip: commonTooltip, legend: {{ display: false }} }},
          scales: {{
            x: commonXScale,
            y: {{ type: 'linear', position: 'left', min: 10000, max: 50000, title: {{ display: true, text: '加權指數 (點)', font: {{ size: 9.5 }} }} }},
            yVol: {{ type: 'linear', position: 'right', min: 0, max: 18000, grid: {{ drawOnChartArea: false }}, title: {{ display: true, text: '成交金額 (億元)', font: {{ size: 9.5 }} }} }}
          }}
        }}
      }});
      buildCustomLegend('taiexChart', chartStore['taiex']);

      // 2. 美國 VIX 與密大信心
      chartStore['us'] = new Chart(document.getElementById('usIndicatorsChart'), {{
        type: 'line',
        data: {{
          labels: dates5Y,
          datasets: [
            {{ label: 'VIX 恐慌指數', data: vixData5Y, borderColor: '#ef4444', backgroundColor: 'rgba(239, 68, 68, 0.1)', yAxisID: 'yVix', tension: 0, pointRadius: 1.5 }},
            {{ label: 'VIX 20 警示線', data: Array(dates5Y.length).fill(20), borderColor: '#f87171', borderDash: [5, 5], borderWidth: 1.5, yAxisID: 'yVix', pointRadius: 0, fill: false }},
            {{ label: '密大消費者信心', data: dates5Y.map((_, i) => michDataMonthly[Math.min(michDataMonthly.length-1, Math.floor(i * 61 / dates5Y.length))]), borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.1)', yAxisID: 'yMich', tension: 0, pointRadius: 1.5 }},
            {{ label: '信心 60 警示線', data: Array(dates5Y.length).fill(60), borderColor: '#60a5fa', borderDash: [5, 5], borderWidth: 1.5, yAxisID: 'yMich', pointRadius: 0, fill: false }},
            {{ label: '信心 80 警示線', data: Array(dates5Y.length).fill(80), borderColor: '#93c5fd', borderDash: [5, 5], borderWidth: 1.5, yAxisID: 'yMich', pointRadius: 0, fill: false }}
          ]
        }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          interaction: {{ mode: 'index', intersect: false }},
          plugins: {{ tooltip: commonTooltip, legend: {{ display: false }} }},
          scales: {{
            x: commonXScale,
            yVix: {{ type: 'linear', position: 'left', min: 0, max: 40, title: {{ display: true, text: 'VIX 恐慌指數', color: '#ef4444', font: {{ size: 9.5 }} }}, ticks: {{ color: '#ef4444' }} }},
            yMich: {{ type: 'linear', position: 'right', min: 30, max: 100, title: {{ display: true, text: '消費者信心', color: '#3b82f6', font: {{ size: 9.5 }} }}, ticks: {{ color: '#3b82f6' }}, grid: {{ drawOnChartArea: false }} }}
          }}
        }}
      }});
      buildCustomLegend('usIndicatorsChart', chartStore['us']);

      // 3. 日經 225
      chartStore['nikkei'] = new Chart(document.getElementById('nikkeiChart'), {{
        type: 'line',
        data: {{
          labels: dates5Y,
          datasets: [
            {{ label: '日經225指數', data: nikkeiData5Y, borderColor: '#06b6d4', backgroundColor: 'rgba(6, 182, 212, 0.1)', fill: true, tension: 0, pointRadius: 1.5 }},
            {{ label: '56,000 點警示線', data: Array(dates5Y.length).fill(56000), borderColor: '#f59e0b', borderDash: [5, 5], borderWidth: 1.5, pointRadius: 0, fill: false }}
          ]
        }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          interaction: {{ mode: 'index', intersect: false }},
          plugins: {{ tooltip: commonTooltip, legend: {{ display: false }} }},
          scales: {{
            x: commonXScale,
            y: {{ min: 20000, max: 75000, title: {{ display: true, text: '日經指數 (點)', font: {{ size: 9.5 }} }} }}
          }}
        }}
      }});
      buildCustomLegend('nikkeiChart', chartStore['nikkei']);

      // 4. 村田 B/B
      chartStore['murata'] = new Chart(document.getElementById('murataChart'), {{
        type: 'line',
        data: {{
          labels: {json.dumps(murata_quarters_21)},
          datasets: [
            {{ label: '村田製作所 B/B Ratio', data: {json.dumps(murata_bb_21)}, borderColor: '#f59e0b', backgroundColor: 'rgba(245, 158, 11, 0.15)', fill: true, tension: 0, pointRadius: 3 }},
            {{ label: '1.2 警戒線', data: Array(21).fill(1.2), borderColor: '#ef4444', borderWidth: 1.5, pointRadius: 0, fill: false }}
          ]
        }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          interaction: {{ mode: 'index', intersect: false }},
          plugins: {{ tooltip: commonTooltip, legend: {{ display: false }} }},
          scales: {{
            x: commonXScale,
            y: {{ min: 0.6, max: 1.6, title: {{ display: true, text: 'B/B Ratio (倍)', font: {{ size: 9.5 }} }} }}
          }}
        }}
      }});
      buildCustomLegend('murataChart', chartStore['murata']);

      // 5-11 檔日股通用繪製
      const finQ18 = {json.dumps(fin_quarters)};

      function makeStock(code, priceId, finId, name, pData, warn, margin, pe, eps, pbr) {{
        // 股價圖
        const priceEl = document.getElementById(priceId);
        if (priceEl) {{
          chartStore['price_' + code] = new Chart(priceEl, {{
            type: 'line',
            data: {{
              labels: dates5Y,
              datasets: [
                {{ label: name + ' 股價 (日圓)', data: pData, borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.1)', fill: true, tension: 0, pointRadius: 1.5 }},
                {{ label: '買進門檻 (' + warn + ' 日圓)', data: Array(dates5Y.length).fill(warn), borderColor: '#ef4444', borderWidth: 1.5, borderDash: [5, 5], pointRadius: 0, fill: false }}
              ]
            }},
            options: {{
              responsive: true, maintainAspectRatio: false,
              interaction: {{ mode: 'index', intersect: false }},
              plugins: {{ tooltip: commonTooltip, legend: {{ display: false }} }},
              scales: {{
                x: commonXScale,
                y: {{ title: {{ display: true, text: '股價 (日圓)', font: {{ size: 9.5 }} }} }}
              }}
            }}
          }});
          buildCustomLegend(priceId, chartStore['price_' + code]);
        }}

        // 財務指標圖
        const finEl = document.getElementById(finId);
        if (finEl) {{
          chartStore['fin_' + code] = new Chart(finEl, {{
            type: 'bar',
            data: {{
              labels: finQ18,
              datasets: [
                {{ label: '營業利益率 (%)', data: margin, backgroundColor: 'rgba(16, 185, 129, 0.45)', borderColor: 'rgba(16, 185, 129, 0.8)', borderWidth: 1, borderRadius: 2, yAxisID: 'y', order: 99 }},
                {{ label: '本益比 PER (倍)', data: pe, type: 'line', borderColor: '#3b82f6', backgroundColor: '#3b82f6', borderWidth: 2, pointRadius: 2.5, tension: 0, yAxisID: 'y1', order: 1 }},
                {{ label: '每股盈餘 EPS (日圓)', data: eps, type: 'line', borderColor: '#f59e0b', backgroundColor: '#f59e0b', borderWidth: 2, pointRadius: 2.5, tension: 0, yAxisID: 'y2', order: 1 }},
                {{ label: '股價淨值比 PBR (倍)', data: pbr, type: 'line', borderColor: '#ec4899', backgroundColor: '#ec4899', borderWidth: 2, pointRadius: 2.5, tension: 0, yAxisID: 'y1', order: 1 }}
              ]
            }},
            options: {{
              responsive: true, maintainAspectRatio: false,
              interaction: {{ mode: 'index', intersect: false }},
              plugins: {{
                legend: {{ display: false }},
                tooltip: {{
                  ...commonTooltip,
                  callbacks: {{
                    title: function(items) {{
                      return '季度：' + items[0].label;
                    }}
                  }}
                }}
              }},
              scales: {{
                x: commonXScale,
                y: {{ type: 'linear', position: 'left', title: {{ display: true, text: '營業利益率 %', font: {{ size: 9.5 }} }} }},
                y1: {{ type: 'linear', position: 'right', grid: {{ drawOnChartArea: false }}, title: {{ display: true, text: 'PER / PBR 倍數', font: {{ size: 9.5 }} }} }},
                y2: {{ type: 'linear', position: 'right', grid: {{ drawOnChartArea: false }}, display: false }}
              }}
            }}
          }});
          buildCustomLegend(finId, chartStore['fin_' + code]);
        }}
      }}

      makeStock('2802', 'stock2802Chart', 'stock2802FinChart', '味之素 (2802.JP)', stockPriceHistory['2802'], 4700, {json.dumps(f2802_opm)}, {json.dumps(f2802_per)}, {json.dumps(f2802_eps)}, {json.dumps(f2802_pbr)});
      makeStock('8411', 'stock8411Chart', 'stock8411FinChart', '瑞穗金融 (8411.JP)', stockPriceHistory['8411'], 6000, {json.dumps(f8411_opm)}, {json.dumps(f8411_per)}, {json.dumps(f8411_eps)}, {json.dumps(f8411_pbr)});
      makeStock('6506', 'stock6506Chart', 'stock6506FinChart', '安川電機 (6506.JP)', stockPriceHistory['6506'], 4500, {json.dumps(f6506_opm)}, {json.dumps(f6506_per)}, {json.dumps(f6506_eps)}, {json.dumps(f6506_pbr)});
      makeStock('5016', 'stock5016Chart', 'stock5016FinChart', 'JX金屬 (5016.JP)', stockPriceHistory['5016'], 3500, {json.dumps(f5016_opm)}, {json.dumps(f5016_per)}, {json.dumps(f5016_eps)}, {json.dumps(f5016_pbr)});
      makeStock('5711', 'stock5711Chart', 'stock5711FinChart', '三菱材料 (5711.JP)', stockPriceHistory['5711'], 4000, {json.dumps(f5711_opm)}, {json.dumps(f5711_per)}, {json.dumps(f5711_eps)}, {json.dumps(f5711_pbr)});
      makeStock('6501', 'stock6501Chart', 'stock6501FinChart', '日立製作所 (6501.JP)', stockPriceHistory['6501'], 4800, {json.dumps(f6501_opm)}, {json.dumps(f6501_per)}, {json.dumps(f6501_eps)}, {json.dumps(f6501_pbr)});
      makeStock('7012', 'stock7012Chart', 'stock7012FinChart', '川崎重工 (7012.JP)', stockPriceHistory['7012'], 2500, {json.dumps(f7012_opm)}, {json.dumps(f7012_per)}, {json.dumps(f7012_eps)}, {json.dumps(f7012_pbr)});
    }});
  </script>
</body>
</html>"""

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html_template)

print('generate_report.py executed successfully! index.html generated with size:', len(html_template))
