#!/usr/bin/env python3
"""Логи боя → компактная выжимка эффективности (этап 3+, combatlog).

Сырой лог ~1 МБ/бой — в репозиторий НЕ кладём. Извлекаем компактную выжимку (~13 КБ):
на игрока полученный/нанесённый урон, лечение, смерти, счётчики прожатых заклинаний и
ауры. Перебивания/диспелы/расходники доопределяются из config/combat.yml при сборке —
поэтому каталог можно править без перекачки. Выжимка неизменяема: есть файл — не качаем.

    python3 tools/collect_combatlog.py --config config/config.json
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
from collections import Counter, defaultdict

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
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=40, context=ctx) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                return None
        except Exception:
            pass
        time.sleep(min(30, 2 ** attempt) + random.uniform(0, 1))
    return None


def _sum_block(block):
    if not isinstance(block, dict):
        return 0
    return sum(hit[0] for v in block.values() for hit in v[0])


def extract(log, duration):
    compact = {"players": {}, "spell_names": {}, "duration": duration}
    for guid, p in (log.get("players") or {}).items():
        compact["players"][guid] = {
            "taken": _sum_block(p.get("taken", {})),
            "done": _sum_block(p.get("dps", {})),
            "healing": _sum_block(p.get("hps", {})),
            "deaths": len(p.get("deaths", []) or []),
            "casts": {},
            "auras": {sid: v[0] for sid, v in (p.get("auras") or {}).items()},
        }
    casts = defaultdict(Counter)
    for c in log.get("casts", []) or []:
        g = str(c.get("sourceGuid"))
        casts[g][c["spellId"]] += 1
        compact["spell_names"][str(c["spellId"])] = c.get("spellName")
    for g, cnt in casts.items():
        if g in compact["players"]:
            compact["players"][g]["casts"] = {str(k): v for k, v in cnt.items()}
    return compact


def main():
    global REPO_ROOT
    from core.common import REPO_ROOT

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--min-interval", type=float, default=1.5)
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(REPO_ROOT, args.config), encoding="utf-8"))
    realm = cfg["realm"]
    bf_dir = os.path.join(REPO_ROOT, cfg["paths"]["raw"], "bossfight", realm)
    out_dir = os.path.join(REPO_ROOT, cfg["paths"]["raw"], "combat", realm)
    os.makedirs(out_dir, exist_ok=True)
    ctx = make_ctx()

    todo = []
    for path in sorted(glob.glob(os.path.join(bf_dir, "*.json"))):
        rid = os.path.splitext(os.path.basename(path))[0]
        if not os.path.exists(os.path.join(out_dir, f"{rid}.json")):
            todo.append((rid, path))
    print(f"Килов без выжимки лога: {len(todo)}")
    todo = todo[: args.limit]

    saved = 0
    for rid, bf_path in todo:
        duration = (json.load(open(bf_path, encoding="utf-8")).get("data", {}) or {}).get("duration")
        log = get_json(f"{API_BASE}/{realm}/details/bossfight/{rid}/combatlog", ctx)
        time.sleep(args.min_interval)
        if not isinstance(log, dict) or not log.get("players"):
            print(f"  ✗ {rid} — лога нет")
            continue
        compact = extract(log, duration)
        compact["record_id"] = int(rid)
        with open(os.path.join(out_dir, f"{rid}.json"), "w", encoding="utf-8") as f:
            json.dump(compact, f, ensure_ascii=False, indent=1, sort_keys=True)
        saved += 1
        print(f"  ✓ {rid}: {len(compact['players'])} игроков")

    print(f"Готово. Новых выжимок: {saved}")


if __name__ == "__main__":
    main()
