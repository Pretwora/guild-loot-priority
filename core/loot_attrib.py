"""Автоатрибуция лута по ленте «Последние действия» (этап 4, ответ на запрос РЛ).

API не отдаёт получателя в дропе кила, но лента действий персонажа отдаёт событие
obtaineditem (получил предмет: entry + абсолютное время). Стабильный сигнал —
обновляется сразу после выдачи, не зависит от того, надел ли игрок вещь.

Событие срабатывает на ЛЮБОЙ полученный предмет (крафт, значки, не только рейд), поэтому
считаем получателем рейдового дропа только если игрок был на киле И получил именно этот
entry в окне после кила. Всё производное: пересчитывается из неизменяемых снимков.
Ручной loot_log.csv перекрывает авто по паре (record_id, entry).
"""

from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

from core.common import REPO_ROOT


def load_obtained(cfg):
    """{имя_персонажа: [(entry, dt_utc_наивный)]} из всех снимков ленты действий (union по id)."""
    realm = cfg.raw["realm"]
    root = os.path.join(REPO_ROOT, cfg.paths["raw"], "actions", realm)
    by_char = defaultdict(dict)  # name -> {event_id: (entry, dt)}
    for char_dir in glob.glob(os.path.join(root, "*")):
        for path in glob.glob(os.path.join(char_dir, "*.json")):
            snap = json.load(open(path, encoding="utf-8"))
            name = snap.get("name")
            for e in snap.get("events", []):
                if e.get("type") != "obtaineditem":
                    continue
                dt = _parse_utc(e.get("datetime"))
                entry = (e.get("action") or {}).get("entry")
                if dt is None or entry is None:
                    continue
                by_char[name][e.get("id")] = (entry, dt)
    return {name: list(ev.values()) for name, ev in by_char.items()}


def _parse_utc(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")  # наивный UTC
    except Exception:
        return None


def attribute(cfg, kills, roster, item_db):
    """Возвращает (auto_rows, ambiguous). auto_rows — в формате строк loot_log."""
    obtained = load_obtained(cfg)
    off = cfg.raw.get("server_utc_offset_hours", 0)
    window = timedelta(hours=cfg.raw["loot"].get("attrib_window_hours", 6))
    lead = timedelta(minutes=10)  # выдать могли за пару минут до отметки кила
    min_q = cfg.raw["loot"]["min_quality"]
    sizes = set(cfg.raw["raid_night"]["count_raid_sizes"])

    auto_rows, ambiguous = [], []
    for k in kills:
        if k.size_bucket not in sizes or k.killed_at is None:
            continue
        kt_utc = k.killed_at - timedelta(hours=off)
        present = {p.name: p for p in k.players}
        for lo in k.loots:
            if lo.is_currency or lo.quality < min_q or lo.count != 1:
                continue
            receivers = {}  # pid -> (name, obtain_dt)
            for nm, p in present.items():
                pid = roster.player_of(nm)
                if not pid:
                    continue
                for entry, dt in obtained.get(nm, []):
                    if entry == lo.entry and (kt_utc - lead) <= dt <= (kt_utc + window):
                        if pid not in receivers or dt < receivers[pid][1]:
                            receivers[pid] = (nm, dt)

            if len(receivers) == 1:
                pid, (nm, dt) = next(iter(receivers.items()))
                p = present[nm]
                award = _infer_award(item_db, lo.entry, p.class_id, p.spec, lo.name)
                auto_rows.append({
                    "date": k.killed_at.strftime("%Y-%m-%d"),
                    "record_id": k.record_id,
                    "item_entry": lo.entry,
                    "item_name": lo.name,
                    "player": pid,
                    "award_type": award,
                    "note": "auto:actions",
                    "_source": "auto",
                })
            elif len(receivers) > 1:
                ambiguous.append({"record_id": k.record_id, "entry": lo.entry,
                                  "item": lo.name, "players": sorted(receivers)})
    return auto_rows, ambiguous


def _infer_award(item_db, entry, class_id, spec, name):
    """Получил — значит взял: основной спек → bis, запасной → offspec, иначе всё равно bis."""
    _, label, _ = item_db.need_level(entry, class_id, spec, name)
    return {"main": "bis", "offspec": "offspec"}.get(label, "bis")


def merge_with_manual(manual_rows, auto_rows):
    """Ручной лог перекрывает авто по (record_id, entry). Возвращает объединённый список."""
    manual_keys = {(str(r.get("record_id")), str(r.get("item_entry")))
                   for r in manual_rows if (r.get("player") or "").strip()}
    merged = list(manual_rows)
    for r in auto_rows:
        if (str(r["record_id"]), str(r["item_entry"])) not in manual_keys:
            merged.append(r)
    return merged
