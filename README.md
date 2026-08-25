# 每日全球市場與總經個股監控報告

追蹤台股加權、VIX、日經 225、密大消費者信心、村田 B/B Ratio，以及一組日本焦點個股的
股價與季度財報趨勢，產生一份可以每天打開來看的 HTML 報告。

---

## 只要記一個指令

```bash
python run.py
```

瀏覽器會自動打開控制台，更新資料、調整設定、產生報告都在同一個畫面完成。
不需要 Python 以外的任何套件。

控制台有三個分頁：

| 分頁 | 做什麼 |
|---|---|
| **每日操作** | 按「更新資料並產生報告」就結束了。旁邊可以直接開啟報告 |
| **追蹤個股** | 增刪個股、拖曳排序、暫時隱藏、設定各股的布局門檻 |
| **警示門檻** | 調整大盤與總經指標的警示線、本益比布局的預設值 |

改完設定按「儲存設定」會直接寫回 `config.json`，右側會先讓你看到即將寫入的內容。

---

## 布局訊號怎麼來的

報告有兩種進場參考，觸發時該欄位會亮起來，頁首也會列出：

- **股價布局** — 收盤價低於個股設定的 `price_buy`
- **本益比布局** — 本益比低於 `per_buy`（沒設就用全域預設，預設 20 倍）

本益比一律用**近四季 EPS 加總**（TTM）計算，避免單季淡旺季造成失真。
所以剛上市、歷史不滿四季的個股會留白，這是刻意的，不是資料缺漏。

---

## 新增一檔個股

1. 控制台 →「追蹤個股」→「＋ 新增個股」
2. 填代號（輸入 `4063` 即可，會自動補成 `4063.T`）、英文代號、公司名稱
3. 按該列的「查證」確認是不是你要的公司
4. 儲存設定 → 回「每日操作」按「更新資料並產生報告」

新個股一開始只有股價圖。季度財報需要人工建立
`data/stock_<英文代號>_quarterly_financials.json`，格式可以參考現有的檔案。

> **日股代號只能用 `.T`**（Yahoo Finance 的東證寫法）。
> `.JP`、`.TO`、`.TYO` 是其他資料商的格式，抓不到資料，控制台會自動幫你換掉。

---

## 財報更新

季度財報**不會**隨股價自動更新。日本沒有統一的財報發布日，只有「各季結束後原則 45 天內」的
上限規定（2024 年 4 月起第 1、3 季已一本化為四半期決算短信）。

### 新加入個股：自動建立歷史

控制台 →「財報登錄」→「自動建立歷史資料」，選好回溯年數按「開始建立」，
過程會即時顯示進度。

資料來源是 **J-Quants API**（日本取引所グループ JPX 官方），回傳的是各公司決算短信的
XBRL 摘要，也就是人工翻 PDF 時讀的同一份官方資料，欄位為結構化標記
（NetSales／OperatingProfit／OrdinaryProfit／Profit…），`TypeOfDocument` 並標明
會計準則（JGAAP／IFRS／US-GAAP）。

程式會自動把「期首起算的累計值」還原成單季（Q2＝上半年−Q1，依此類推）、計算營益率、
在官方季報未揭露 BVPS 時以「自己資本÷（發行股數−庫藏股）」推算，最後把四季加總與
官方全年數字核對，對不上會明白標示要人工確認。

**需要 API 金鑰**：到 https://jpx-jquants.com/ 免費註冊後，在
[儀表板](https://jpx-jquants.com/ja/dashboard) 產生 API Key，
貼進控制台「財報登錄」分頁的金鑰欄位即可（會存進 `secrets.json`，已列入 .gitignore）。
也可以改用環境變數 `JQUANTS_API_KEY`。

> J-Quants 已於 2026-06-01 終止 V1 API，認證從「帳密換 token」改為 API 金鑰，
> 本專案使用的是 V2 端點 `/v2/fins/summary`。
> **不要把金鑰放進 `config.json`**，那個檔案會被 commit 到 GitHub。

> **免費方案的限制**：資料期間約近 2 年、延遲約 12 週。
> 所以能自動建立約 8 季，最新一至兩季要用下面的手動方式補上。

也可以不開控制台：`python build_financial_history.py 4063 --years 2`
（加 `--dry-run` 只看結果不寫檔；覆寫前原檔會自動備份成 `.bak`）

### 每季更新：手動登錄

控制台 →「財報登錄」分頁：

1. 按「哪幾檔該更新了？」看誰已經進入公布窗口
2. 選個股 → 畫面顯示最近 6 季，以及既有缺漏
3. 季別標籤與期末日會自動推算好，只要填數字
4. 填營收與本業獲利時，營益率即時自動算出，表格也會即時預覽新的一列
5. 按「新增這一季」

系統會把六個欄位同步寫入趨勢檔，並更新快照檔的公布日與來源標註。
寫入前會擋掉重複季別、順序顛倒的期末日，以及陣列長度不一致的損壞狀態。

沒把握的欄位可以留白，報告會顯示為缺漏，不會用推估值填補。

> **本業獲利的科目定義每家不同**：日立用調整後營業利益、川崎重工用事業利益、
> 味之素用營業利益、瑞穗（銀行）用經常利益。務必核對官方決算短信的原始科目。

**為什麼不從第三方財經網站抓？** 這個專案曾經因此出過嚴重的錯：
某網站對 IFRS 公司的「經常益」欄位填的是稅前利益，不是本業的事業利益，
整條獲利數列因此錯誤。J-Quants 之所以可用，正是因為它是交易所官方、欄位有明確定義，
而不是二手整理。即使如此，建立完仍請對照官方決算短信抽查一次。

---

## 財報資料結構

`data/stock_<key>_quarterly_financials.json` 是**平行陣列**，同一個索引代表同一季：

```
fiscal_years            季別標籤        ["FY26Q4", "FY27Q1"]
fiscal_year_end_dates   期末日          ["2026-03-31", "2026-06-30"]
revenue_oku_jpy         營收（億円）
business_profit_oku_jpy 本業獲利
operating_margin_pct    營益率（自動算）
net_income_oku_jpy      淨利
eps_jpy                 每股盈餘
bvps_jpy                每股淨值
```

報告卡片上的 PER／EPS／PBR／營益率**取自這些陣列的最後一筆**，不是讀快照檔，
這樣卡片數字與下方趨勢圖的最後一點永遠一致。快照檔
`data/stock_<key>_financials.json` 只負責資料來源連結與財報公布日。

用控制台登錄就不必手動維護這些陣列的對齊。

---

## 部署到 GitHub Pages

### 第一次設定（電腦上做一次就好）

1. **建立 repo 並推上去**（`secrets.json` 已列入 .gitignore，不會被推上去）
2. **Settings → Pages**：Source 選 `Deploy from a branch`，分支 `main`，資料夾 `/ (root)`
3. **Settings → Actions → General → Workflow permissions**：選 `Read and write permissions`
4. **Settings → Secrets and variables → Actions → New repository secret**
   名稱填 `JQUANTS_API_KEY`，值貼上你的 J-Quants 金鑰

報告網址：`https://<你的帳號>.github.io/<專案名>/`

### 之後就全自動

`.github/workflows/daily-update.yml` 每個工作日早上自動更新並推送，你不用做任何事。

---

## 用手機操作

控制台（`run.py`）是本機伺服器，GitHub Pages 放不了。手機上改用 **GitHub Actions** 當遠端執行引擎。

### 事前準備（一次）

手機裝 **GitHub App**（App Store / Play 商店搜尋 GitHub），登入後進到你的 repo。

### 操作清單

**Actions → 管理追蹤名單 → Run workflow**，填完送出，約 1～2 分鐘跑完。

| 想做的事 | 動作欄選 | 代號欄填 | 其他欄位 |
|---|---|---|---|
| 立刻更新報告 | 只更新報告 | 留空 | — |
| 加一檔新股（含季報） | 新增個股並建立季報 | `4063` | 可填布局線 |
| 加一檔新股（只要股價） | 新增個股 | `4063` | 可填布局線 |
| 幫既有股補季報 | 建立或重建季報 | `shinetsu` | 回溯年數 |
| 暫時不看某檔 | 隱藏個股 | `organo` | — |
| 恢復顯示 | 恢復顯示 | `organo` | — |
| 從名單移除 | 移除個股 | `organo` | — |
| 確認目前有哪些股 | 列出目前名單 | 留空 | — |

代號欄可填股票代號（`4063`）或檔名代號（`shinetsu`）都行。
名稱會自動帶出台灣慣用寫法（信越化学工業 → 信越化學），與電腦版結果一致。

### 看報告

直接開 `https://<你的帳號>.github.io/<專案名>/`，不需要登入。
建議用瀏覽器的「加入主畫面」，之後像 App 一樣一點就開。

### 改警示門檻

在 GitHub App 裡開 `config.json` → 右上角鉛筆圖示 → 改數字 → Commit。
存檔後跑一次「只更新報告」即可。

### 手機上做不到的事

**手動登錄季報數字**。那需要逐欄對照官方決算短信，小螢幕容易看錯——
這個專案最大的一次錯誤（獲利科目誤用）就是核對不確實造成的。建議回電腦用控制台做。

---

## 分享給別人看

**只是要看報告**：把網址給他就好。GitHub Pages 是公開的，對方不需要 GitHub 帳號、
不需要安裝任何東西，手機瀏覽器直接開。教他「加入主畫面」就跟 App 一樣。

報告每個工作日早上自動更新，所以對方也不需要手動觸發任何東西。

**如果對方要能改名單**：請他自己註冊一個免費的 GitHub 帳號，
你到 Settings → Collaborators 邀請他。他用自己的帳號登入就能操作 Actions。

> **絕對不要把帳號密碼或 Personal Access Token 給別人。**
> 密碼等於整個帳號，Token 等於一把可以改你所有 repo 的鑰匙，兩者都收不回來。
> 協作一律用「邀請對方的帳號」，隨時可以撤銷。

**不希望報告公開**：GitHub Pages 免費版一律是公開的。
要限制存取需要 GitHub Enterprise，或改用其他有密碼保護的靜態網站服務。

---

## 部署前的整理

```bash
python cleanup.py            # 先看有哪些可以刪
python cleanup.py --delete   # 確認後執行
```

會找出：暫存檔、重複下載的副本（檔名帶 `(1)`）、`.bak` 備份、
已經不在名單裡的孤兒資料檔，以及 `__pycache__`、`local_test/`。
同時檢查 `.gitignore` 有沒有正確排除 `secrets.json`。

## 檔案結構

```
├── run.py                  單一入口：控制台與所有指令
├── panel.html              控制台介面
├── config.json             你的設定（個股名單、警示門檻）
├── config_loader.py        設定載入與驗證
├── fetch_market_data.py    抓價格資料
├── generate_report_local.py 產生報告
├── check_earnings_due.py   財報公布窗口偵測
├── verify_stock_code.py    股票代號查證
├── build_financial_history.py  季報歷史自動建立（J-Quants）
├── manage_stock.py         名單管理命令列（給 GitHub Actions 用）
├── name_utils.py           公司名稱與檔名代號處理
├── cleanup.py              部署前整理檢查
├── secrets.json            API 金鑰（不進版控）
├── index.html              產生出來的正式報告（GitHub Pages 讀這個）
├── local_test/index.html   測試版報告，不影響正式版
└── data/                   價格與財報資料
```

---

## 不開控制台時的指令

```bash
python run.py update        更新資料並產生正式報告
python run.py fetch         只更新價格
python run.py report --local  只產生測試報告
python run.py earnings      檢查財報公布窗口
python run.py verify 4063   查證股票代號
```

---

## 資料來源與限制

- 價格：Yahoo Finance（增量更新，只抓上次之後的新交易日）
- 財報：人工登錄自各公司官方決算短信，來源與科目定義記在每個資料檔的 `methodology` 欄位
- 報告不會編造數字。缺漏的資料就是留白，不會用推估值填補
