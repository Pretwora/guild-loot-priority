#!/usr/bin/env python3
"""Разобрать заполненное тело issue и дописать loot_log.csv (этап 4).

    python3 tools/apply_loot_issue.py --body issue_body.md

Валидация обязательна: строка сверяется с loots[] соответствующего кила. Ошибки
печатаются в stderr и в файл errors.md (для комментария в issue), но не роняют
разбор остальных строк.
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.common import REPO_ROOT, load_json  # noqa: E402
from core.loot_intake import parse_issue_body, rows_to_csv_append  # noqa: E402


def build_loots_index(cfg):
    realm = cfg["realm"]
    root = os.path.join(REPO_ROOT, cfg["paths"]["raw"], "bossfight", realm)
    idx = {}
    for path in glob.glob(os.path.join(root, "*.json")):
        raw = load_json(path)
        body = raw.get("data", raw)
        rid = int(os.path.splitext(os.path.basename(path))[0])
        date = (body.get("killed_at") or "")[:10]
        per = {}
        for lo in body.get("loots", []) or []:
            it = lo.get("item", {}) or {}
            entry = it.get("entry") or lo.get("entry")
            per[entry] = {"name": it.get("name", "?"), "date": date}
        idx[rid] = per
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--body", required=True, help="файл с телом issue")
    ap.add_argument("--errors-out", default="loot_errors.md")
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(REPO_ROOT, args.config), encoding="utf-8"))
    text = open(args.body, encoding="utf-8").read()
    idx = build_loots_index(cfg)

    rows, errors = parse_issue_body(text, idx)

    log_path = os.path.join(REPO_ROOT, cfg["paths"]["manual"], "loot_log.csv")
    if rows:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(rows_to_csv_append(rows))
    print(f"Добавлено строк: {len(rows)}; ошибок: {len(errors)}", file=sys.stderr)

    with open(args.errors_out, "w", encoding="utf-8") as f:
        if errors:
            f.write("### ⚠️ Проблемы разбора лута\n\n")
            for e in errors:
                f.write(f"- {e}\n")
            f.write(f"\nУспешно добавлено строк: **{len(rows)}**.\n")
        else:
            f.write(f"✅ Разобрано без ошибок, добавлено строк: **{len(rows)}**.\n")

    # ненулевой код, если были ошибки — воркфлоу оставит issue открытым/прокомментирует
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
