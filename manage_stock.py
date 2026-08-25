# -*- coding: utf-8 -*-
"""
追蹤名單管理（命令列）
======================

控制台（run.py）只能在自己的電腦上跑。這支程式讓同樣的操作可以用命令列完成，
所以能被 GitHub Actions 呼叫——你在手機上按一下按鈕，雲端就幫你做完。

用法：
    python manage_stock.py add 4063                    新增個股（自動帶出名稱與檔名）
    python manage_stock.py add 4063 --price-buy 6000   順便設股價布局線
    python manage_stock.py add 4063 --build            新增後直接建立季報歷史
    python manage_stock.py remove shinetsu             從名單移除（資料檔保留）
    python manage_stock.py hide shinetsu               暫時隱藏
    python manage_stock.py show shinetsu               恢復顯示
    python manage_stock.py list                        列出目前名單
"""
import argparse
import json
import os
import sys

from config_loader import CONFIG_PATH, load_jp_stocks, _setup_console_encoding
from name_utils import normalize_code, pick_name, suggest_key

_setup_console_encoding()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _write_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _lookup(code):
    """查代號對應的公司。JPX 官方名冊優先（有日文漢字名），Yahoo 補股價。"""
    names, price, currency = [], None, ""
    try:
        from build_financial_history import fetch_company_name, _get_cred
        api_key = _get_cred("api_key", "JQUANTS_API_KEY")
        if api_key:
            jpx = fetch_company_name(code, api_key) or {}
            names += [n for n in (jpx.get("ja"), jpx.get("en")) if n]
    except Exception:
        pass
    try:
        from verify_stock_code import lookup
        ok, info = lookup(code)
        if ok:
            names += [n for n in (info.get("longName"), info.get("shortName")) if n]
            price, currency = info.get("price"), info.get("currency", "")
    except Exception:
        pass
    return names, price, currency


def cmd_add(args):
    code = normalize_code(args.code)
    if not code:
        print("❌ 請提供股票代號，例如 4063")
        return 1

    cfg = _read_config()
    stocks = cfg.setdefault("jp_stocks", [])
    if any(s.get("code", "").upper() == code for s in stocks):
        print(f"⚠️ {code} 已經在名單裡了，沒有變動。")
        return 0

    print(f"查詢 {code} …")
    names, price, currency = _lookup(code)
    if not names and not args.name:
        print(f"❌ 查不到 {code} 的公司資料。請確認代號，或用 --name 自行指定名稱。")
        return 1

    name = args.name or pick_name(names, code)
    key = args.key or suggest_key(names, code)
    if any(s.get("key") == key for s in stocks):
        key = key + code_suffix(code)

    entry = {
        "key": key, "code": code, "name": name, "enabled": True,
        "price_buy": args.price_buy, "per_buy": args.per_buy,
    }
    stocks.append(entry)
    _write_config(cfg)

    price_txt = f"　最新價 {price:,.0f} {currency}" if isinstance(price, (int, float)) else ""
    print(f"✅ 已加入「{name}」（{code}）　檔名代號 {key}{price_txt}")
    if names:
        print(f"   來源名稱：{names[0]}")

    if args.build:
        print()
        print("開始建立季報歷史…")
        try:
            from build_financial_history import build
            build(key=key, years=args.years)
        except Exception as e:
            print(f"⚠️ 季報建立失敗：{e}")
            print("   個股本身已加入，之後可再單獨建立季報。")
            return 0
    else:
        print("   提醒：這檔目前只有股價，季報要另外建立（加 --build 可一次完成）。")
    return 0


def code_suffix(code):
    from name_utils import code_digits
    return code_digits(code).lower()


def _find(cfg, key):
    for s in cfg.get("jp_stocks", []):
        if s.get("key") == key or s.get("code", "").upper() == normalize_code(key):
            return s
    return None


def cmd_remove(args):
    cfg = _read_config()
    s = _find(cfg, args.key)
    if not s:
        print(f"❌ 名單裡找不到「{args.key}」")
        return 1
    cfg["jp_stocks"] = [x for x in cfg["jp_stocks"] if x is not s]
    _write_config(cfg)
    print(f"✅ 已從名單移除「{s.get('name')}」（data/ 底下的資料檔保留，之後想加回來還在）")
    return 0


def cmd_toggle(args, enabled):
    cfg = _read_config()
    s = _find(cfg, args.key)
    if not s:
        print(f"❌ 名單裡找不到「{args.key}」")
        return 1
    s["enabled"] = enabled
    _write_config(cfg)
    print(f"✅ 「{s.get('name')}」已{'恢復顯示' if enabled else '隱藏'}")
    return 0


def cmd_list(_args):
    stocks = load_jp_stocks(include_disabled=True)
    if not stocks:
        print("名單是空的。")
        return 0
    print(f"目前 {len(stocks)} 檔：")
    for i, s in enumerate(stocks, 1):
        mark = " " if s["enabled"] else "×"
        fin = os.path.join(BASE_DIR, "data", f"stock_{s['key']}_quarterly_financials.json")
        n = 0
        if os.path.exists(fin):
            try:
                with open(fin, encoding="utf-8") as f:
                    n = len(json.load(f).get("fiscal_years") or [])
            except Exception:
                pass
        q = f"季報 {n} 季" if n else "無季報"
        print(f" {mark}{i:2d}. {s['name']:<22s} {s['code']:<9s} {s['key']:<20s} {q}")
    return 0


def cmd_build(args):
    from build_financial_history import build
    s = _find(_read_config(), args.key)
    if not s:
        print(f"❌ 名單裡找不到「{args.key}」")
        return 1
    build(key=s["key"], years=args.years)
    return 0


def main():
    ap = argparse.ArgumentParser(description="追蹤名單管理（可由 GitHub Actions 呼叫）")
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="新增個股")
    a.add_argument("code", help="股票代號，例如 4063")
    a.add_argument("--name", help="自訂顯示名稱（預設自動帶出）")
    a.add_argument("--key", help="自訂檔名代號（預設自動產生）")
    a.add_argument("--price-buy", type=float, default=None, help="股價布局參考線")
    a.add_argument("--per-buy", type=float, default=None, help="本益比布局參考線")
    a.add_argument("--build", action="store_true", help="順便建立季報歷史")
    a.add_argument("--years", type=int, default=2, help="季報回溯年數")

    for name, helptext in [("remove", "從名單移除"), ("hide", "暫時隱藏"), ("show", "恢復顯示")]:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("key", help="檔名代號或股票代號")

    b = sub.add_parser("build", help="建立／重建季報歷史")
    b.add_argument("key", help="檔名代號或股票代號")
    b.add_argument("--years", type=int, default=2)

    sub.add_parser("list", help="列出目前名單")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1

    try:
        if args.cmd == "add":
            return cmd_add(args)
        if args.cmd == "remove":
            return cmd_remove(args)
        if args.cmd == "hide":
            return cmd_toggle(args, False)
        if args.cmd == "show":
            return cmd_toggle(args, True)
        if args.cmd == "build":
            return cmd_build(args)
        if args.cmd == "list":
            return cmd_list(args)
    except Exception as e:
        print(f"❌ 執行失敗：{e}")
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
