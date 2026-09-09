# reference/samples — 端點原始回應

每個 `*.raw.gz` 都是**真的打過**該端點拿到的原始 bytes，配一個 `*.meta.json`
（url、method、bytes、sha256、抓取時間、User-Agent、第一行、以及這個檔案的結論）。

gzip 用 `mtime=0` 壓，所以同樣的回應重壓會產生位元組相同的檔案 —— diff 有變動
就代表端點真的變了。

**沒用的端點也留著**，並在 meta 的 `note` 寫明為什麼不是它。不留的話，六個月後
會有人再去試一次同一個 URL。

## 現況

| 檔案 | 結論 |
| --- | --- |
| `ndc_pmi_ndc6100` | ✅ 台灣 PMI／NMI 月資料 |
| `cbc_ef15m01_money_aggregates` | ✅ M1B 餘額（日平均數） |
| `fsc_t49_11138_market_overview` | ✅ 上市櫃總市值（新臺幣十億元） |
| `datagov_dropdown_*` | ✅ data.gov.tw 唯一能過濾的搜尋端點 |
| `cbc_ef19m01_m1b_factors` | ❌ 欄名幾乎一樣但值是「變動額」不是餘額 |
| `fsc_t32_103955_global_marketcap` | ❌ 單位是美元、且不含上櫃 |
| `twse_mi_index_tables_20260831` | ❌ 9 張表沒有任何一張有市值 |

## 重新抓取

```bash
python3 -c "import gzip;print(gzip.open('samples/<name>.raw.gz','rb').read().decode('utf-8-sig')[:2000])"
```

寫 parser 之前先讀這個檔，不要照文件猜欄位。
