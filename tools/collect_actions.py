#!/usr/bin/env python3
"""Снимки ленты «Последние действия» игроков (этап 4, автоатрибуция лута).

Эндпоинт statistics/{name}/latest-actions отдаёт события персонажа с абсолютным
временем, в т.ч. obtaineditem (получил предмет: entry + время). Это стабильный
источник получателя лута — обновляется сразу после выдачи, не зависит от того,
надел игрок вещь или нет.

Снимок — неизменяемое сырьё, пишется только когда появились новые события (по id).
30-минутный прогон ловит каждое событие, пока оно в окне ленты.

    python3 tools/collect_actions.py --config config/config.json
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
import urllib.parse
import urllib.request
from datetime import datetime, timezone

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


def get_json(url, ctx):
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=25, context=ctx) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                return None
        except Exception:
            pass
        time.sleep(min(30, 2 ** attempt) + random.uniform(0, 1))
    return None


def our_characters(cfg):
    realm = cfg["realm"]
    our = cfg.get("guild_name_api", "")
    root = os.path.join(REPO_ROOT, cfg["paths"]["raw"], "bossfight", realm)
    names = set()
    for p in glob.glob(os.path.join(root, "*.json")):
        body = json.load(open(p, encoding="utf-8")).get("data", {})
        for pl in body.get("players", []) or []:
            if (pl.get("guild") or {}).get("name") == our:
                names.add(pl["name"])
    return sorted(names)


def known_event_ids(char_dir):
    ids = set()
    for path in glob.glob(os.path.join(char_dir, "*.json")):
        for e in json.load(open(path, encoding="utf-8")).get("events", []):
            if e.get("id") is not None:
                ids.add(e["id"])
    return ids


def main():
    global REPO_ROOT
    from core.common import REPO_ROOT

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--min-interval", type=float, default=1.5)
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(REPO_ROOT, args.config), encoding="utf-8"))
    realm = cfg["realm"]
    root = os.path.join(REPO_ROOT, cfg["paths"]["raw"], "actions", realm)
    ctx = make_ctx()

    names = our_characters(cfg)
    print(f"Персонажей к опросу: {len(names)}")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%MZ")
    saved = 0

    for name in names:
        # без profile=true лента отдаёт до 200 событий (недели истории), а не 10 —
        # это ловит раздачи лута прошлых рейдов (obtaineditem за несколько недель).
        url = f"{API_BASE}/{realm}/statistics/{urllib.parse.quote(name)}/latest-actions"
        feed = get_json(url, ctx)
        time.sleep(args.min_interval)
        if not isinstance(feed, list):
            print(f"  ✗ {name}")
            continue
        char_dir = os.path.join(root, urllib.parse.quote(name, safe=""))
        known = known_event_ids(char_dir)
        new_ids = {e.get("id") for e in feed if e.get("id") is not None} - known
        if not new_ids:
            continue
        guid = next((e.get("guid") for e in feed if e.get("guid")), None)
        os.makedirs(char_dir, exist_ok=True)
        out = {"ts": stamp, "name": name, "guid": guid, "events": feed}
        with open(os.path.join(char_dir, f"{stamp}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
        saved += 1
        got = sum(1 for e in feed if e.get("type") == "obtaineditem")
        print(f"  ✓ {name}: +{len(new_ids)} событий (получений в ленте: {got})")

    print(f"Готово. Новых снимков: {saved}")


if __name__ == "__main__":
    main()
