#!/usr/bin/env python3
"""Сгенерировать тело issue с лутом за рейд-вечер (этап 4).

    python3 tools/make_loot_issue.py --date 2026-08-31 > issue_body.md
    python3 tools/make_loot_issue.py --latest --out issue.json   # title+body+labels для gh

Берёт незакрытые дропы и присутствовавших из свежесобранного dashboard.json.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.loot_intake import generate_issue_body  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", default="data/dist/dashboard.json")
    ap.add_argument("--date", help="дата вечера YYYY-MM-DD")
    ap.add_argument("--latest", action="store_true", help="самый свежий вечер")
    ap.add_argument("--out", help="записать JSON {title,body,labels} вместо markdown в stdout")
    args = ap.parse_args()

    from core.common import REPO_ROOT

    dash = json.load(open(os.path.join(REPO_ROOT, args.dashboard), encoding="utf-8"))
    nights = dash["nights"]
    if not nights:
        print("Вечеров нет", file=sys.stderr)
        sys.exit(1)

    date = args.date or (nights[0]["date"] if args.latest else None)
    if not date:
        print("Укажи --date или --latest", file=sys.stderr)
        sys.exit(1)

    night = next((n for n in nights if n["date"] == date), None)
    if night is None:
        print(f"Вечер {date} не найден", file=sys.stderr)
        sys.exit(1)

    drops = [{"item": d["item"], "entry": d["entry"], "record_id": d["record_id"], "boss": d["boss"]}
             for d in dash["unclosed_drops"] if d["date"] == date]
    present = [p["id"] for p in night["present"]] + night.get("bench", [])

    body = generate_issue_body(date, night["size"], drops, present)
    title = f"🎁 Лут {date} ({', '.join(night['bosses'][:2])}{'…' if len(night['bosses'])>2 else ''}, {night['size']})"

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"title": title, "body": body, "labels": ["loot"]}, f, ensure_ascii=False, indent=1)
        print(f"записано: {args.out} ({len(drops)} предметов)", file=sys.stderr)
    else:
        print(body)


if __name__ == "__main__":
    main()
