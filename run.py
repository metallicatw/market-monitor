# -*- coding: utf-8 -*-
"""
每日全球市場與總經個股監控報告 — 單一入口
=========================================

只要記這一個指令：

    python run.py

會啟動本機控制台並自動開啟瀏覽器，更新資料、調整設定、查證代號、產生報告
全部在同一個畫面完成，不用再記其他指令。

其他用法（給自動化或不想開瀏覽器時用）：

    python run.py update      更新資料並產生正式報告（GitHub Actions 用這個）
    python run.py fetch       只更新價格資料
    python run.py report      只產生報告（--local 產生測試版）
    python run.py earnings    檢查財報公布窗口
    python run.py verify 4063 查證股票代號

控制台只在你自己的電腦上執行，不會對外開放。
"""
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable or "python3"
DEFAULT_PORT = 8787


def _setup_console_encoding():
    """Windows 主控台預設是地區編碼（繁中為 cp950），遇到圖示會整支程式中斷。
    這裡統一改成 UTF-8，無法顯示的字元以替代字元代過。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_console_encoding()


def _child_env():
    """子程式也要用 UTF-8 輸出，否則在 Windows 上會因為編碼而中斷。"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


# ---------------------------------------------------------------------------
# 長時間作業：在背景執行，前端輪詢進度
# ---------------------------------------------------------------------------
class Job:
    """一次只跑一個長作業，進度以文字行累積，讓前端可以持續顯示。"""

    def __init__(self):
        self.lines = []
        self.running = False
        self.done = False
        self.ok = None
        self.title = ""
        self.lock = threading.Lock()

    def log(self, text=""):
        with self.lock:
            self.lines.append(str(text))

    def snapshot(self):
        with self.lock:
            return {"running": self.running, "done": self.done, "ok": self.ok,
                    "title": self.title, "output": "\n".join(self.lines)}

    def start(self, title, fn):
        if self.running:
            return False
        with self.lock:
            self.lines = []
            self.running = True
            self.done = False
            self.ok = None
            self.title = title

        def runner():
            try:
                fn(self.log)
                self.ok = True
            except Exception as e:
                self.log("")
                self.log(f"❌ {e}")
                self.ok = False
            finally:
                self.running = False
                self.done = True

        threading.Thread(target=runner, daemon=True).start()
        return True


JOB = Job()


# ---------------------------------------------------------------------------
# 共用：執行子程式並收集輸出
# ---------------------------------------------------------------------------
def run_script(args, timeout=600):
    """執行同目錄下的 python 程式，回傳 (成功與否, 輸出文字)。"""
    cmd = [PYTHON] + args
    try:
        p = subprocess.run(
            cmd, cwd=BASE_DIR, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
            env=_child_env(),
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode == 0, out.strip() or "（沒有輸出）"
    except subprocess.TimeoutExpired:
        return False, f"執行超過 {timeout} 秒被中止，可能是網路太慢或卡住了。"
    except FileNotFoundError:
        return False, f"找不到程式：{args[0]}　請確認檔案跟 run.py 放在同一層。"
    except Exception as e:
        return False, f"執行失敗：{e}"


def cmd_fetch(include_hidden=False):
    args = ["fetch_market_data.py"]
    if include_hidden:
        args.append("--include-hidden")
    return run_script(args)


def cmd_report(local=False):
    args = ["generate_report_local.py"]
    if local:
        args.append("--local")
    return run_script(args)


def cmd_earnings():
    return run_script(["check_earnings_due.py"])


def cmd_verify(codes):
    return run_script(["verify_stock_code.py"] + list(codes), timeout=120)


# ---------------------------------------------------------------------------
# 控制台伺服器
# ---------------------------------------------------------------------------
class PanelHandler(BaseHTTPRequestHandler):
    server_version = "MarketMonitorPanel"

    def log_message(self, fmt, *args):
        pass  # 不要把每個請求都印在終端機，保持畫面乾淨

    # ---- 工具 ----
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _serve_file(self, path, ctype):
        if not os.path.exists(path):
            self._send(404, {"error": "檔案不存在：" + os.path.basename(path)})
            return
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---- 路由 ----
    def do_GET(self):
        route = urlparse(self.path).path

        if route in ("/", "/index.html"):
            self._serve_file(os.path.join(BASE_DIR, "panel.html"), "text/html; charset=utf-8")

        elif route == "/api/ping":
            self._send(200, {"ok": True, "dir": BASE_DIR})

        elif route == "/api/config":
            p = os.path.join(BASE_DIR, "config.json")
            if not os.path.exists(p):
                self._send(404, {"error": "找不到 config.json"})
                return
            with open(p, encoding="utf-8") as f:
                self._send(200, {"text": f.read()})

        elif route == "/api/status":
            self._send(200, self._status())

        elif route == "/api/financials":
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            key = (q.get("key") or [""])[0]
            self._send(200, self._read_financials(key))

        elif route == "/api/lookup":
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            self._send(200, self._lookup_code((q.get("code") or [""])[0]))

        elif route == "/api/job":
            self._send(200, JOB.snapshot())

        elif route == "/api/creds":
            self._send(200, self._creds_status())

        elif route == "/api/finstatus":
            # 哪些個股已經有季報資料，讓「追蹤個股」分頁可以標示出來
            result = {}
            try:
                from config_loader import load_jp_stocks
                for s in load_jp_stocks(include_disabled=True):
                    p = self._fin_path(s["key"])
                    n = 0
                    if os.path.exists(p):
                        try:
                            with open(p, encoding="utf-8") as f:
                                n = len(json.load(f).get("fiscal_years") or [])
                        except Exception:
                            n = 0
                    result[s["key"]] = n
            except Exception as e:
                self._send(200, {"error": str(e)})
                return
            self._send(200, {"counts": result})

        elif route == "/report":
            # 優先給測試版，沒有就給正式版
            for rel in ("local_test/index.html", "index.html"):
                p = os.path.join(BASE_DIR, rel)
                if os.path.exists(p):
                    self._serve_file(p, "text/html; charset=utf-8")
                    return
            self._send(404, {"error": "還沒有產生過報告"})

        else:
            self._send(404, {"error": "查無此路徑"})

    def do_POST(self):
        route = urlparse(self.path).path

        if route == "/api/config":
            body = self._read_json()
            text = body.get("text", "")
            try:
                json.loads(text)  # 存檔前先確認是合法 JSON，避免寫壞設定
            except Exception as e:
                self._send(400, {"ok": False, "error": f"內容不是有效的 JSON：{e}"})
                return
            try:
                with open(os.path.join(BASE_DIR, "config.json"), "w", encoding="utf-8") as f:
                    f.write(text)
                self._send(200, {"ok": True})
            except Exception as e:
                self._send(500, {"ok": False, "error": f"寫入失敗：{e}"})

        elif route == "/api/action":
            body = self._read_json()
            action = body.get("action")
            if action == "fetch":
                ok, out = cmd_fetch(include_hidden=bool(body.get("includeHidden")))
            elif action == "report":
                ok, out = cmd_report(local=bool(body.get("local", True)))
            elif action == "publish":
                ok, out = cmd_report(local=False)
            elif action == "update":
                ok, out = cmd_fetch()
                if ok:
                    ok2, out2 = cmd_report(local=bool(body.get("local", True)))
                    ok, out = ok2, out + "\n\n" + out2
            elif action == "earnings":
                ok, out = cmd_earnings()
            elif action == "verify":
                codes = body.get("codes") or []
                if not codes:
                    ok, out = False, "沒有指定要查證的代號"
                else:
                    ok, out = cmd_verify(codes)
            else:
                ok, out = False, f"不認得的動作：{action}"
            self._send(200, {"ok": ok, "output": out, "status": self._status()})

        elif route == "/api/financials":
            ok, msg = self._append_quarter(self._read_json())
            self._send(200, {"ok": ok, "output": msg})

        elif route == "/api/creds":
            body = self._read_json()
            api_key = (body.get("apiKey") or "").strip()
            if not api_key:
                self._send(200, {"ok": False, "error": "請貼上 API 金鑰"})
                return
            path = os.path.join(BASE_DIR, "secrets.json")
            try:
                existing = {}
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as f:
                        existing = json.load(f) or {}
                existing["jquants"] = {"api_key": api_key}
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(existing, f, ensure_ascii=False, indent=2)
                # 順手清掉 config.json 裡的舊帳密，避免不小心推上 GitHub
                cleaned = self._strip_config_creds()
                msg = "金鑰已存到 secrets.json（此檔已列入 .gitignore，不會進版控）"
                if cleaned:
                    msg += "\n同時已從 config.json 移除舊的帳密設定。"
                self._send(200, {"ok": True, "output": msg})
            except Exception as e:
                self._send(200, {"ok": False, "error": f"寫入失敗：{e}"})

        elif route == "/api/buildhistory":
            body = self._read_json()
            key = body.get("key")
            years = body.get("years")
            if not key:
                self._send(200, {"ok": False, "error": "沒有指定個股"})
                return
            if JOB.running:
                self._send(200, {"ok": False, "error": "已經有一個作業在執行中，請等它跑完。"})
                return

            def work(log):
                import build_financial_history as bfh
                bfh.build(key=key, years=years, progress=log)

            JOB.start(f"建立 {key} 的季報歷史", work)
            self._send(200, {"ok": True, "started": True})

        else:
            self._send(404, {"error": "查無此路徑"})

    # ---- 財報資料 ----
    FIELDS = ["revenue_oku_jpy", "business_profit_oku_jpy", "operating_margin_pct",
              "net_income_oku_jpy", "eps_jpy", "bvps_jpy"]

    def _fin_path(self, key):
        return os.path.join(BASE_DIR, "data", f"stock_{key}_quarterly_financials.json")

    def _read_financials(self, key):
        if not key:
            return {"error": "沒有指定個股"}
        p = self._fin_path(key)
        if not os.path.exists(p):
            return {"exists": False, "key": key}
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            return {"exists": True, "error": f"檔案讀取失敗：{e}"}

        n = len(d.get("fiscal_years") or [])
        rows = []
        for i in range(max(0, n - 6), n):   # 只回傳最近 6 季，畫面用得到就好
            row = {"label": d["fiscal_years"][i],
                   "endDate": (d.get("fiscal_year_end_dates") or [None] * n)[i]}
            for f in self.FIELDS:
                arr = d.get(f) or []
                row[f] = arr[i] if i < len(arr) else None
            rows.append(row)

        gaps = {f: sum(1 for v in (d.get(f) or []) if v is None) for f in self.FIELDS}
        return {
            "exists": True, "key": key, "name": d.get("name", key),
            "count": n, "rows": rows, "gaps": gaps,
            "lastLabel": d["fiscal_years"][-1] if n else None,
            "lastEnd": (d.get("fiscal_year_end_dates") or [None])[-1] if n else None,
        }

    def _append_quarter(self, body):
        key = body.get("key")
        if not key:
            return False, "沒有指定個股"
        p = self._fin_path(key)
        if not os.path.exists(p):
            return False, f"找不到 data/stock_{key}_quarterly_financials.json\n新個股需要先建立這個檔案，可以複製現有個股的檔案來改。"

        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            return False, f"檔案讀取失敗：{e}"

        label = (body.get("label") or "").strip()
        end_date = (body.get("endDate") or "").strip()
        if not label or not end_date:
            return False, "季別標籤與期末日都要填"
        if label in (d.get("fiscal_years") or []):
            return False, f"「{label}」已經存在了。如果是要修正數字，請直接編輯資料檔。"
        ends = d.get("fiscal_year_end_dates") or []
        if ends and end_date <= ends[-1]:
            return False, f"期末日 {end_date} 沒有比最後一季 {ends[-1]} 晚，順序會亂掉。"

        rev = body.get("revenue_oku_jpy")
        prof = body.get("business_profit_oku_jpy")
        margin = body.get("operating_margin_pct")
        if margin is None and isinstance(rev, (int, float)) and isinstance(prof, (int, float)) and rev:
            margin = round(prof / rev * 100, 2)

        values = {
            "revenue_oku_jpy": rev,
            "business_profit_oku_jpy": prof,
            "operating_margin_pct": margin,
            "net_income_oku_jpy": body.get("net_income_oku_jpy"),
            "eps_jpy": body.get("eps_jpy"),
            "bvps_jpy": body.get("bvps_jpy"),
        }

        # 六個陣列必須同步成長，長度對不上就是資料錯位，寧可停下來
        n = len(d.get("fiscal_years") or [])
        for f in self.FIELDS:
            if len(d.get(f) or []) != n:
                return False, (f"欄位 {f} 長度({len(d.get(f) or [])})與季數({n})不符，"
                               "資料可能已經錯位，先修好再新增。")

        d["fiscal_years"].append(label)
        d.setdefault("fiscal_year_end_dates", []).append(end_date)
        for f in self.FIELDS:
            d.setdefault(f, []).append(values[f])

        note = (body.get("note") or "").strip()
        if note:
            d["methodology"] = (d.get("methodology", "") + f" 【{label}】{note}").strip()
        d["fetched_at"] = __import__("datetime").date.today().isoformat()

        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return False, f"寫入失敗：{e}"

        # 同步更新快照檔的公布日與最新數字，讓來源標註不會過期
        snap_p = os.path.join(BASE_DIR, "data", f"stock_{key}_financials.json")
        snap_msg = ""
        if os.path.exists(snap_p):
            try:
                with open(snap_p, encoding="utf-8") as f:
                    snap = json.load(f)
                snap["fiscal_period"] = label
                if isinstance(rev, (int, float)):
                    snap["revenue_oku_jpy"] = rev
                if isinstance(values["net_income_oku_jpy"], (int, float)):
                    snap["net_income_oku_jpy"] = values["net_income_oku_jpy"]
                if isinstance(margin, (int, float)):
                    snap["operating_margin_pct"] = margin
                if body.get("disclosureDate"):
                    snap["disclosure_date"] = body["disclosureDate"]
                with open(snap_p, "w", encoding="utf-8") as f:
                    json.dump(snap, f, ensure_ascii=False, indent=2)
                snap_msg = "\n快照檔（來源標註與公布日）也一併更新了。"
            except Exception as e:
                snap_msg = f"\n⚠️ 快照檔更新失敗（不影響報告數字）：{e}"

        margin_msg = f"　營益率 {margin}%（自動計算）" if margin is not None else ""
        return True, (f"已新增 {d.get('name', key)} 的 {label}（期末 {end_date}）"
                      f"{margin_msg}\n目前共 {len(d['fiscal_years'])} 季。{snap_msg}"
                      "\n\n記得回「每日操作」重新產生報告才會看到變化。")

    # ---- J-Quants 認證 ----
    def _creds_status(self):
        """回報目前是否已設定認證，以及是不是放在有風險的位置。密碼本身不回傳。"""
        import os as _os
        env_ok = bool(_os.environ.get("JQUANTS_API_KEY"))

        key_set, key_hint = False, ""
        p = _os.path.join(BASE_DIR, "secrets.json")
        if _os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    j = (json.load(f) or {}).get("jquants") or {}
                k = j.get("api_key") or ""
                if k:
                    key_set = True
                    key_hint = k[:4] + "…" + k[-4:] if len(k) > 10 else "已設定"
            except Exception:
                pass

        cfg_has = False
        try:
            with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
                c = (json.load(f) or {}).get("jquants") or {}
            cfg_has = bool(c.get("mail") or c.get("password") or c.get("refresh_token") or c.get("api_key"))
        except Exception:
            pass

        return {"envConfigured": env_ok, "keySet": key_set, "keyHint": key_hint,
                "configHasCreds": cfg_has,
                "configured": env_ok or key_set or cfg_has}

    def _strip_config_creds(self):
        """把 config.json 裡的 jquants 區塊拿掉，避免帳密隨版控外流。"""
        path = os.path.join(BASE_DIR, "config.json")
        try:
            with open(path, encoding="utf-8") as f:
                c = json.load(f)
            if "jquants" not in c:
                return False
            del c["jquants"]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    # ---- 代號查詢（供新增個股時自動帶出名稱） ----
    def _lookup_code(self, raw):
        try:
            from verify_stock_code import normalize_code, lookup, search_names
        except Exception as e:
            return {"ok": False, "error": f"查詢模組載入失敗：{e}"}

        code = normalize_code(raw)
        if not code:
            return {"ok": False, "error": "沒有輸入代號"}

        # 先問 JPX 官方名冊：那裡有交易所登記的日文公司名，轉成繁體後
        # 最接近使用者習慣的中文寫法。Yahoo 對日股多半只回英文名。
        jpx = {}
        try:
            from build_financial_history import fetch_company_name, _get_cred
            api_key = _get_cred("api_key", "JQUANTS_API_KEY")
            if api_key:
                jpx = fetch_company_name(code, api_key) or {}
        except Exception:
            jpx = {}

        ok, info = lookup(code)
        if not ok:
            # 只要 JPX 查得到，就算 Yahoo 沒回應也還有名稱可用
            names = [n for n in (jpx.get("ja"), jpx.get("en")) if n]
            if names:
                return {"ok": True, "code": code, "names": names,
                        "exchange": "東京証券取引所", "currency": "JPY", "price": None,
                        "suggestedKey": self._suggest_key([jpx.get("en") or ""], code),
                        "note": "名稱取自 JPX 官方名冊（Yahoo 沒有回應股價）"}
            return {"ok": False, "code": code, "error": info}

        # chart API 對日股常只給英文名，再問一次搜尋端點看有沒有漢字名稱
        extra = search_names(code) or {}
        candidates = [jpx.get("ja"), info.get("longName"), info.get("shortName"),
                      extra.get("longName"), extra.get("shortName"), jpx.get("en")]
        candidates = [c for c in candidates if c]

        # 檔名代號要從英文名推導，日文名推不出好念的英文
        key_sources = [c for c in (jpx.get("en"), info.get("longName"), info.get("shortName")) if c]

        from name_utils import pick_name, suggest_key
        return {
            "ok": True,
            "code": code,
            "names": candidates,
            "suggestedName": pick_name(candidates, code),
            "exchange": info.get("exchange"),
            "currency": info.get("currency"),
            "price": info.get("price"),
            "suggestedKey": suggest_key(key_sources or candidates, code),
        }

    @staticmethod
    def _suggest_key(names, code):
        """從英文名稱推一個好記的檔名代號，例如 Shin-Etsu Chemical → shinetsu。
        推不出來就退回用代號，使用者隨時可以自己改。"""
        import re as _re
        drop = {"co", "ltd", "inc", "corp", "corporation", "company", "holdings",
                "holding", "group", "kk", "the", "and", "limited", "plc", "sa", "ag"}
        for n in names:
            if not n or not _re.search(r"[A-Za-z]", n):
                continue  # 不是拉丁字母的名稱（例如漢字）沒辦法直接當檔名
            words = [w for w in _re.split(r"[^A-Za-z0-9]+", n) if w]
            words = [w.lower() for w in words if w.lower() not in drop]
            if not words:
                continue
            key = "".join(words[:2])[:24]
            if key:
                return key
        return "s" + code.replace(".", "").lower()

    # ---- 狀態 ----
    def _status(self):
        def mtime(rel):
            p = os.path.join(BASE_DIR, rel)
            if not os.path.exists(p):
                return None
            import datetime
            return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y/%m/%d %H:%M")

        data_dir = os.path.join(BASE_DIR, "data")
        price_files = fin_files = 0
        if os.path.isdir(data_dir):
            for n in os.listdir(data_dir):
                if not n.endswith(".json"):
                    continue
                if "quarterly_financials" in n or n.endswith("_financials.json"):
                    fin_files += 1
                elif n.startswith("stock_") or n in ("taiex.json", "vix.json", "nikkei.json", "michigan.json", "murata_bb.json"):
                    price_files += 1
        return {
            "priceUpdated": mtime("data/taiex.json"),
            "reportBuilt": mtime("local_test/index.html") or mtime("index.html"),
            "publishedBuilt": mtime("index.html"),
            "priceFiles": price_files,
            "finFiles": fin_files,
        }


def serve(port=DEFAULT_PORT, open_browser=True):
    panel = os.path.join(BASE_DIR, "panel.html")
    if not os.path.exists(panel):
        print("❌ 找不到 panel.html，控制台無法啟動。請確認它跟 run.py 在同一層。")
        return 1

    for attempt in range(12):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), PanelHandler)
            break
        except OSError:
            port += 1
    else:
        print("❌ 連續嘗試多個埠號都被占用，請關掉其他程式再試。")
        return 1

    url = f"http://127.0.0.1:{port}/"
    print("=" * 60)
    print("  監控報告控制台已啟動")
    print("=" * 60)
    print(f"  網址：{url}")
    print("  結束：在這個視窗按 Ctrl+C")
    print()
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n控制台已關閉。")
    finally:
        httpd.server_close()
    return 0


# ---------------------------------------------------------------------------
# 命令列
# ---------------------------------------------------------------------------
def main(argv):
    cmd = argv[1] if len(argv) > 1 else "panel"
    rest = argv[2:]

    if cmd in ("panel", "-h", "--help", "help"):
        if cmd != "panel":
            print(__doc__)
            return 0
        port = DEFAULT_PORT
        no_browser = "--no-browser" in rest
        for i, a in enumerate(rest):
            if a == "--port" and i + 1 < len(rest):
                port = int(rest[i + 1])
        return serve(port, open_browser=not no_browser)

    if cmd == "update":
        ok, out = cmd_fetch()
        print(out)
        if not ok:
            return 1
        ok, out = cmd_report(local=False)
        print(out)
        return 0 if ok else 1

    if cmd == "fetch":
        ok, out = cmd_fetch(include_hidden="--include-hidden" in rest)
        print(out)
        return 0 if ok else 1

    if cmd == "report":
        ok, out = cmd_report(local="--local" in rest)
        print(out)
        return 0 if ok else 1

    if cmd == "earnings":
        ok, out = cmd_earnings()
        print(out)
        return 0 if ok else 1

    if cmd == "verify":
        if not rest:
            print("請指定代號，例如：python run.py verify 4063")
            return 1
        ok, out = cmd_verify(rest)
        print(out)
        return 0 if ok else 1

    print(f"不認得的指令：{cmd}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
