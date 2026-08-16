# -*- coding: utf-8 -*-
"""
Murata Manufacturing (6981.T) B/B Ratio — verified quarterly dataset
Sources:
  - FY2024 (Apr2023-Mar2024) & FY2025 (Apr2024-Mar2025): factbook2026Excel.xlsm
    Sheet '事業別セグメント受注動向 Orders', rows 10/12 (FY24) and 27/29 (FY25)
    BBR = Orders Received / Revenue, pre-calculated by Murata
  - FY2026 Q1-Q2 (Apr-Sep 2025): Murata IR deck transcript, 2026年3月期第2四半期決算説明会 (2025/10/31)
    https://corporate.murata.com/-/media/corporate/about/newsroom/news/irnews/irnews/2025/1031b/25q2-j.ashx
  - FY2026 Q1-Q4 company-wide: Murata IR decks, 2025年度第3四半期決算説明会 (2026/2/2) chart
    + 2025年度決算説明会 (2026/4/30) chart
    https://corporate.murata.com/-/media/corporate/about/newsroom/news/irnews/irnews/2026/0202b/25q3-j-speach.ashx
    https://corporate.murata.com/-/media/corporate/about/newsroom/news/irnews/irnews/2026/0430b/25q4-j-speach.ashx
  - FY2026 Q3-Q4 Capacitors-only (MLCC): NOT FOUND — labeled None (no data), per user instruction
    not to interpolate or substitute.

Fiscal year convention: FY24 = Apr 2023 - Mar 2024 (old-style Murata IR labeling, confirmed by
cross-checking Order Amount figures against Excel's calendar-year-start labels).
"""

MURATA_BBR_QUARTERS = [
    "FY24 Q1", "FY24 Q2", "FY24 Q3", "FY24 Q4",
    "FY25 Q1", "FY25 Q2", "FY25 Q3", "FY25 Q4",
    "FY26 Q1", "FY26 Q2", "FY26 Q3", "FY26 Q4",
]

# Company-wide (コンポーネント計 / Components total) BBR - used as "全公司綜合" proxy
MURATA_BBR_COMPANYWIDE = [
    0.9757, 0.9721, 1.0134, 1.0628,   # FY24 Q1-Q4 (Excel)
    1.0517, 0.9540, 0.9783, 1.0304,   # FY25 Q1-Q4 (Excel)
    1.04, 1.00, 1.07, 1.24,           # FY26 Q1-Q4 (IR decks: Q1/Q2 transcript + Q3/Q4 chart)
]

# Capacitors (コンデンサ / MLCC) BBR - used as "主力MLCC" line
MURATA_BBR_CAPACITORS = [
    0.9696, 0.9660, 1.0285, 1.0609,   # FY24 Q1-Q4 (Excel)
    1.0488, 0.9565, 0.9724, 1.0304,   # FY25 Q1-Q4 (Excel)
    1.03, 1.01, None, None,           # FY26 Q1-Q2 (IR transcript), Q3-Q4: no data found
]

assert len(MURATA_BBR_QUARTERS) == len(MURATA_BBR_COMPANYWIDE) == len(MURATA_BBR_CAPACITORS)
