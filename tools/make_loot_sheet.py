#!/usr/bin/env python3
"""Скелет ручной разметки лута: все дропы гильдийных 25-к начиная с даты X.

РЛ решил размечать мейн/офспек руками (авто-парсер не знает намерения). Этот инструмент
собирает ОДНУ строку на каждый реальный дроп из подходящих рейдов, предзаполняет получателя
и авто-догадку спека — дальше РЛ правит колонку award_type (main/off) и, где надо, player.

Фильтр рейда (по решению совета):
  • только 25-ки (size_bucket == 25);
  • «в составе гильдии»: доля согильдийцев среди рейда > --min-guild (по умолч. 0.70);
  • вечер начался не раньше --since (по умолч. дата вступления пачки, 2026-08-13).

Вывод — в формате loot_log.csv (+ справочные колонки boss/ilvl/slot), готов к правке и сборке.
Разметка: award_type = main|off (алиасы к bis|offspec), либо free|shard|de. Пустой player —
дроп никем не подобран авто (впиши получателя вручную или оставь пустым = «не роздан»).

Запуск:  python3 -m tools.make_loot_sheet [--since 2026-08-13] [--min-guild 0.70] [-o path]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.common import Config, REPO_ROOT
from core import normalize as N
from core.items import ItemDB
from core import loot_attrib as LA


def qualifying_nights(kills, cfg, since, min_guild):
    """[(date_str, [kills...], guild_frac)] — гильдийные 25-вечера не раньше since."""
    our = cfg.raw.get("guild_name_api", "")
    k25 = sorted((k for k in kills if k.size_bucket == 25 and k.killed_at),
                 key=lambda k: k.killed_at)
    nights, cur = [], []
    for k in k25:
        if cur and (k.killed_at - cur[-1].killed_at).total_seconds() > 3 * 3600:
            nights.append(cur)
            cur = []
        cur.append(k)
    if cur:
        nights.append(cur)

    out = []
    for g in nights:
        names = {p.name for k in g for p in k.players}
        guildies = {p.name for k in g for p in k.players if p.guild_name == our}
        frac = len(guildies) / len(names) if names else 0.0
        if g[0].killed_at >= since and frac > min_guild:
            out.append((g[0].killed_at.strftime("%Y-%m-%d"), g, frac))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--since", default="2026-08-13", help="YYYY-MM-DD, порог даты вечера")
    ap.add_argument("--min-guild", type=float, default=0.70, help="мин. доля согильдийцев в рейде")
    ap.add_argument("-o", "--out", default="data/manual/loot_log.csv")
    args = ap.parse_args()

    cfg = Config(os.path.join(REPO_ROOT, args.config))
    since = dt.datetime.strptime(args.since, "%Y-%m-%d")
    roster = N.load_roster(cfg)
    kills = N.load_kills(cfg)
    N.augment_roster_with_parses(roster, kills, cfg)
    item_db = ItemDB(cfg)

    nights = qualifying_nights(kills, cfg, since, args.min_guild)
    keep_ids = {k.record_id for _, g, _ in nights for k in g}
    disp = {pid: pl.get("display", pid) for pid, pl in roster.players.items()}

    # авто-атрибуция (получатель + догадка спека) по подходящим килам
    scoped_kills = [k for _, g, _ in nights for k in g]
    auto_rows, _ = LA.attribute(cfg, scoped_kills, roster, item_db)
    auto = {(r["record_id"], r["item_entry"]): r for r in auto_rows}

    min_q = cfg.raw["loot"]["min_quality"]
    denylist = set(cfg.raw["loot"].get("currency_entry_denylist", []))
    recipe_pref = ("выкройка", "схема", "чертеж", "чертёж", "формула", "рецепт", "технология")

    rows = []
    for date, g, frac in nights:
        for k in sorted(g, key=lambda x: x.killed_at):
            seen = set()
            for lo in k.loots:
                if lo.is_currency or lo.entry in denylist or lo.quality < min_q or lo.count != 1:
                    continue
                if lo.entry in seen:
                    continue  # один и тот же entry дважды в киле — один дроп
                seen.add(lo.entry)
                if lo.name.lower().startswith(recipe_pref):
                    continue  # рецепты — не совет распределяет
                ic = item_db.classify(lo.entry, lo.name)
                if 0 < (ic.ilvl or 0) < 100:
                    continue  # квестовые головы и прочий мусор (ilvl < 100)
                a = auto.get((k.record_id, lo.entry))
                player = disp.get(a["player"], a["player"]) if a else ""
                # авто-догадка: main если bis, off если offspec (РЛ перепроверяет)
                spec = {"bis": "main", "offspec": "off"}.get(a["award_type"], "") if a else ""
                if not a:
                    note = "не роздан авто — впиши получателя"
                elif a["award_type"] == "offspec":
                    note = "авто счёл ОФФ — проверь"
                else:
                    note = ""
                rows.append({
                    "date": date,
                    "boss": k.boss_name,
                    "item_name": lo.name,
                    "ilvl": ic.ilvl or "",
                    "slot": ic.slot,
                    "player": player,
                    "award_type": spec,
                    "note": note,
                    "record_id": k.record_id,
                    "item_entry": lo.entry,
                })

    cols = ["date", "boss", "item_name", "ilvl", "slot", "player", "award_type",
            "note", "record_id", "item_entry"]
    out_path = os.path.join(REPO_ROOT, args.out)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    att = sum(1 for r in rows if r["player"])
    print(f"вечеров: {len(nights)}  дропов: {len(rows)}  с получателем (авто): {att}  "
          f"без получателя: {len(rows) - att}")
    for date, g, frac in nights:
        n = sum(1 for r in rows if r["record_id"] in {k.record_id for k in g})
        print(f"  {date}  {g[0].boss_name[:18]:18s}…  дропов: {n:2d}  гильдия {frac*100:.0f}%")
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
