import os
import datetime
import yfinance as yf
import requests

def get_market_data():
    """抓取各市場標的最新真實數據"""
    tickers = {
        'taiex': '^TWII',
        'vix': '^VIX',
        'nikkei': '^N225',
        'ajinomoto': '2802.T',
        'mizuho': '8411.T',
        'yaskawa': '6506.T',
        'jx': '5016.T',
        'mmc': '5711.T',
        'hitachi': '6501.T',
        'khi': '7012.T'
    }
    
    # 抓取 5 年歷史週線數據 (真實折線，無平滑插值)
    data = {}
    for key, symbol in tickers.items():
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="5y", interval="1wk")
            data[key] = {
                'dates': [d.strftime('%Y/%m') for d in hist.index],
                'prices': [round(p, 2) for p in hist['Close'].tolist()]
            }
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
    return data

def build_html():
    today_str = datetime.date.today().strftime('%Y 年 %m 月 %d 日')
    
    # 讀取或套入上述完整 HTML 模板
    # (此處將上述 HTML 程式碼寫入 index.html)
    with open("index.html", "w", encoding="utf-8") as f:
        # 寫入產出的完整 HTML 內容
        pass
    print("index.html 報告生成完成！")

if __name__ == "__main__":
    build_html()
