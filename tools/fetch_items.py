#!/usr/bin/env python3
"""Добор карточек предметов в кеш data/items/{realm}/{entry}.json.

Качает ТОЛЬКО те entry, что реально упали в логах (quality>=min, не валюта) и
которых ещё нет в кеше. По одному, с паузой 1.5с. Карточки неизменяемы: есть файл —
запроса нет. Массово сайт не парсим (раздел 8 SPEC).

    python3 tools/fetch_items.py --config config/config.json
"""

import argparse
import glob
import json
import os
import random
import ssl
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_BASE = "https://sirus.su/api/base"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


def make_ctx():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--limit", type=int, default=200, help="предохранитель на прогон")
    args = ap.parse_args()

    from core.common import REPO_ROOT

    cfg = json.load(open(os.path.join(REPO_ROOT, args.config), encoding="utf-8"))
    realm = cfg["realm"]
    loot_cfg = cfg["loot"]
    raw_dir = os.path.join(REPO_ROOT, cfg["paths"]["raw"], "bossfight", realm)
    items_dir = os.path.join(REPO_ROOT, cfg["paths"]["items"], realm)
    os.makedirs(items_dir, exist_ok=True)

    # собрать нужные entry из дропа
    wanted = {}
    for p in sorted(glob.glob(os.path.join(raw_dir, "*.json"))):
        body = json.load(open(p, encoding="utf-8")).get("data", {})
        for lo in body.get("loots", []) or []:
            it = lo.get("item", {}) or {}
            entry = it.get("entry") or lo.get("entry")
            name = it.get("name", "")
            if it.get("quality", 0) < loot_cfg["min_quality"]:
                continue
            if entry in loot_cfg["currency_entry_denylist"]:
                continue
            if any(m in name for m in loot_cfg["currency_name_markers"]):
                continue
            wanted[entry] = name

    todo = [(e, n) for e, n in wanted.items()
            if not os.path.exists(os.path.join(items_dir, f"{e}.json"))]
    print(f"Предметов в дропе (годных): {len(wanted)}, к докачке: {len(todo)}")
    todo = todo[: args.limit]

    ctx = make_ctx()
    saved = 0
    for entry, name in todo:
        data = None
        for base in ("https://sirus.su/api/base", "https://sirus.org/api/base"):  # su падает → зеркало
            url = f"{base}/{realm}/tooltip/item/{entry}?lang=ru"
            for attempt in range(1, 5):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=25, context=ctx) as r:
                        data = json.loads(r.read().decode("utf-8", "replace"))
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 and e.code < 500:
                        break
                except Exception:
                    break  # сеть/DNS — к зеркалу
                time.sleep(min(60, 2 ** attempt) + random.uniform(0, 1.5))
            if data:
                break
        item = (data or {}).get("item")
        if not item:
            print(f"  ✗ {entry} ({name}) — не забрался")
            time.sleep(1.5)
            continue
        with open(os.path.join(items_dir, f"{entry}.json"), "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=1, sort_keys=True)
        saved += 1
        print(f"  ✓ {entry}  {name}")
        time.sleep(1.5)

    print(f"Готово. Новых карточек: {saved}")


if __name__ == "__main__":
    main()
