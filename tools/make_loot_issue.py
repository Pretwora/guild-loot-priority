#!/usr/bin/env python3
"""Сгенерировать тело issue раздачи лута за рейд-вечер, ПРЕДЗАПОЛНЕННОЕ авто-раздачей.

Получатель и тип берутся из авто-атрибуции (лента действий × дроп кила). Рейд-лидер в
issue только правит тип/получателя где надо и закрывает — loot-intake.yml пишет loot_log.csv.

    python3 tools/make_loot_issue.py --date 2026-08-27 --out issue.json
    python3 tools/make_loot_issue.py --latest --sizes 25 --out issue.json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.common import Config  # noqa: E402
from core import normalize as N  # noqa: E402
from core import scoring as SC  # noqa: E402
from core import loot_attrib as LA  # noqa: E402
from core.items import ItemDB  # noqa: E402
from core.loot_intake import generate_issue_body  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--date", help="дата рейд-вечера YYYY-MM-DD")
    ap.add_argument("--latest", action="store_true", help="самый свежий вечер нужного размера")
    ap.add_argument("--sizes", default="25", help="размеры рейда через запятую (напр. 25 или 10,25)")
    ap.add_argument("--out", help="записать JSON {title,body,labels} для gh issue create")
    args = ap.parse_args()

    cfg = Config(args.config)
    roster = N.load_roster(cfg)
    item_db = ItemDB(cfg)
    kills = N.load_kills(cfg)

    sizes = {int(s) for s in args.sizes.split(",") if s.strip()}
    subset = [k for k in kills if k.size_bucket in sizes]
    nights = N.build_nights(subset, cfg)
    if not nights:
        sys.exit("Нет вечеров нужного размера")

    if args.latest and not args.date:
        night = nights[-1]
    else:
        night = next((n for n in nights if n.date == args.date), None)
        if night is None:
            sys.exit(f"Вечер {args.date} не найден (есть: {', '.join(n.date for n in nights)})")

    # авто-раздача и уже вписанное вручную
    auto_rows, _ = LA.attribute(cfg, subset, roster, item_db)
    auto_by = {(r["record_id"], int(r["item_entry"])): r for r in auto_rows}
    logged = {(int(r["record_id"]), int(r["item_entry"]))
              for r in SC.load_loot_log(cfg) if (r.get("player") or "").strip()}

    min_q = cfg.raw["loot"]["min_quality"]
    present, drops, seen = set(), [], set()
    for k in night.kills:
        for p in k.players:
            pid = roster.player_of(p.name)
            if pid:
                present.add(pid)
        for lo in k.loots:
            if lo.is_currency or lo.quality < min_q or lo.count != 1:
                continue
            if (k.record_id, lo.entry) in logged or (k.record_id, lo.entry) in seen:
                continue
            seen.add((k.record_id, lo.entry))
            auto = auto_by.get((k.record_id, lo.entry))
            drops.append({
                "item": lo.name, "entry": lo.entry, "record_id": k.record_id, "boss": k.boss_name,
                "player": auto["player"] if auto else "",
                "award_type": auto["award_type"] if auto else "bis",
                "auto": bool(auto),
            })

    body = generate_issue_body(night.date, night.size_bucket, drops, sorted(present))
    auto_n = sum(1 for d in drops if d["auto"])
    title = f"🎁 Лут {night.date} ({night.size_bucket}-ка, предметов {len(drops)}, авто {auto_n})"

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"title": title, "body": body, "labels": ["loot"]}, f, ensure_ascii=False, indent=1)
        print(f"записано: {args.out} — вечер {night.date}, предметов {len(drops)}, авто {auto_n}", file=sys.stderr)
    else:
        print(body)


if __name__ == "__main__":
    main()
