#!/usr/bin/env python3
"""Забрать записи на рейд из raid-helper и сложить как сырьё.

    python3 tools/collect_signups.py --url https://raid-helper.xyz/event/1542622271326134357
    python3 tools/collect_signups.py --event 1542622271326134357

Эндпоинт: https://raid-helper.xyz/api/event/{id} → {title, date, unixtime, signups[...]}.
Каждая запись: name («Персонаж/Имя»), class (реальный класс или Absence/Tentative),
userid (Discord id, стабильный ключ). Сырьё складывается в data/raw/signups/{id}.json,
неизменяемо (перезапись только свежее — запись живёт до рейда и правится игроками).
"""

import argparse
import json
import os
import re
import ssl
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API = "https://raid-helper.xyz/api/event/"


def make_ctx():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def event_id(s):
    m = re.search(r"(\d{6,})", s)
    return m.group(1) if m else s


def main():
    from core.common import REPO_ROOT

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="ссылка на ивент raid-helper")
    ap.add_argument("--event", help="id ивента")
    ap.add_argument("--config", default="config/config.json")
    args = ap.parse_args()

    if not args.url and not args.event:
        sys.exit("нужен --url или --event")
    eid = event_id(args.event or args.url)

    H = {"User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/140.0 Safari/537.36",
         "Accept": "application/json"}
    ctx = make_ctx()
    with urllib.request.urlopen(urllib.request.Request(API + eid, headers=H), timeout=25, context=ctx) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))

    signups = data.get("signups", [])
    out_dir = os.path.join(REPO_ROOT, "data/raw/signups")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{eid}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)

    import collections
    by = collections.Counter(
        "absence" if s.get("class") == "Absence" else
        "tentative" if s.get("class") == "Tentative" else "signed"
        for s in signups
    )
    print(f"Ивент {eid}: «{data.get('title')}» {data.get('date')}")
    print(f"Записей: {len(signups)} — {dict(by)}")
    print(f"Сохранено: {path}")


if __name__ == "__main__":
    main()
