# -*- coding: utf-8 -*-
"""
專案整理工具
============

部署前把不該進版控的檔案找出來：暫存檔、重複下載的副本、
以及已經不在追蹤名單裡的孤兒資料檔。

預設只列出不刪除，確認清單沒問題再加 --delete。

用法：
    python cleanup.py             只檢查，列出可刪除的東西
    python cleanup.py --delete    實際刪除
"""
import argparse
import json
import os
import re
import shutil

from config_loader import CONFIG_PATH, load_jp_stocks, _setup_console_encoding

_setup_console_encoding()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 這些是舊版留下、現在已經沒有程式在用的檔案
OBSOLETE_FILES = {
    "config_editor.html": "已被 panel.html 取代",
    "generate_report.py": "已被 generate_report_local.py 取代",
    "gitignore": "檔名少了開頭的點，Git 根本沒讀到（見下方說明）",
}
OBSOLETE_DIRS = {
    "__pycache__": "Python 暫存，會自動重建",
    "local_test": "本地測試產物，每次執行都會重生",
}


def human(n):
    return f"{n/1024:.0f} KB" if n < 1024 * 1024 else f"{n/1024/1024:.1f} MB"


def scan():
    items = []          # (路徑, 原因, 大小, 是否為資料夾)

    # 1. 根目錄的舊檔案與暫存資料夾
    for name, why in OBSOLETE_FILES.items():
        p = os.path.join(BASE_DIR, name)
        if os.path.exists(p):
            items.append((p, why, os.path.getsize(p), False))
    for name, why in OBSOLETE_DIRS.items():
        p = os.path.join(BASE_DIR, name)
        if os.path.isdir(p):
            size = sum(os.path.getsize(os.path.join(r, f))
                       for r, _, fs in os.walk(p) for f in fs)
            items.append((p, why, size, True))

    if not os.path.isdir(DATA_DIR):
        return items

    # 2. data/ 裡的暫存與重複副本
    for f in sorted(os.listdir(DATA_DIR)):
        p = os.path.join(DATA_DIR, f)
        if not os.path.isfile(p):
            continue
        if f.endswith(".bak"):
            items.append((p, "備份檔，重建季報時自動產生", os.path.getsize(p), False))
        elif re.search(r"\(\d+\)\.json$", f):
            items.append((p, "重複下載的副本（檔名帶括號數字）", os.path.getsize(p), False))
        elif f.endswith("_annual_financials.json"):
            items.append((p, "舊的年度格式，程式已改讀季度檔", os.path.getsize(p), False))

    # 3. 孤兒資料檔：不在追蹤名單裡的個股
    keys = {s["key"] for s in load_jp_stocks(include_disabled=True)}
    for f in sorted(os.listdir(DATA_DIR)):
        p = os.path.join(DATA_DIR, f)
        if not os.path.isfile(p) or any(p == x[0] for x in items):
            continue
        m = re.match(r"^stock_(.+?)(_quarterly_financials|_financials)?\.json$", f)
        if not m:
            continue
        key = m.group(1)
        if key not in keys:
            items.append((p, f"「{key}」不在追蹤名單裡（孤兒檔）", os.path.getsize(p), False))

    return items


def main():
    ap = argparse.ArgumentParser(description="部署前整理專案檔案")
    ap.add_argument("--delete", action="store_true", help="實際刪除（預設只列出）")
    args = ap.parse_args()

    items = scan()
    print("=" * 68)
    print("專案整理檢查")
    print("=" * 68)

    if not items:
        print("✅ 沒有找到需要清理的檔案。")
    else:
        total = sum(x[2] for x in items)
        print(f"找到 {len(items)} 項，共 {human(total)}：\n")
        for p, why, size, is_dir in items:
            rel = os.path.relpath(p, BASE_DIR)
            kind = "資料夾" if is_dir else "檔案　"
            print(f"  [{kind}] {rel}")
            print(f"           {why}　（{human(size)}）")
        print()
        if args.delete:
            for p, _, _, is_dir in items:
                try:
                    shutil.rmtree(p) if is_dir else os.remove(p)
                    print(f"  已刪除 {os.path.relpath(p, BASE_DIR)}")
                except Exception as e:
                    print(f"  ⚠️ 刪不掉 {os.path.relpath(p, BASE_DIR)}：{e}")
            print(f"\n✅ 清理完成，釋出 {human(total)}")
        else:
            print("以上只是列出。確認沒問題後執行：python cleanup.py --delete")

    # 安全檢查：這兩件事會讓金鑰外洩，一定要提醒
    print()
    print("-" * 68)
    gi = os.path.join(BASE_DIR, ".gitignore")
    if not os.path.exists(gi):
        print("🔴 找不到 .gitignore（注意開頭的點）。")
        print("   沒有它，secrets.json 會被推上 GitHub，等於公開你的 API 金鑰。")
    else:
        with open(gi, encoding="utf-8") as f:
            content = f.read()
        if "secrets.json" in content:
            print("✅ .gitignore 存在且已排除 secrets.json")
        else:
            print("🔴 .gitignore 裡沒有 secrets.json，請補上這一行。")

    sec = os.path.join(BASE_DIR, "secrets.json")
    if os.path.exists(sec):
        print("ℹ️ secrets.json 存在（正常，這是本機用的）。確認它不會被 commit 即可。")
        print("   檢查指令：git check-ignore -v secrets.json")


if __name__ == "__main__":
    main()
