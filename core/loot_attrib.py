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
    master = cfg.raw["loot"].get("master_looter")  # ГМ/мастер-лутер — транзит, не получатель

    # Присутствие считаем по РЕЙД-ВЕЧЕРУ, а не по конкретному килу: при мастер-луте ГМ
    # раздаёт трейдом любому в рейде (получатель мог быть не на этом боссе). Плюс это
    # отсекает шум чужих рейдов по тому же entry. record_id → имена рейда за вечер.
    line_of = {p.name: p for k in kills for p in k.players}
    night_roster = {}
    dated = sorted((k for k in kills if k.size_bucket in sizes and k.killed_at),
                   key=lambda x: x.killed_at)
    grp = []

    def _flush(g):
        names = {p.name for kk in g for p in kk.players}
        for kk in g:
            night_roster[kk.record_id] = names

    for k in dated:
        if grp and (k.killed_at - grp[-1].killed_at).total_seconds() > 3 * 3600:
            _flush(grp)
            grp = []
        grp.append(k)
    if grp:
        _flush(grp)

    auto_rows, ambiguous = [], []
    for k in kills:
        if k.size_bucket not in sizes or k.killed_at is None:
            continue
        kt_utc = k.killed_at - timedelta(hours=off)
        raid_names = night_roster.get(k.record_id) or {p.name for p in k.players}
        for lo in k.loots:
            if lo.is_currency or lo.quality < min_q or lo.count != 1:
                continue
            receivers = {}  # pid -> (name, latest_obtain_dt)
            for nm in raid_names:
                if master and nm == master:
                    continue  # мастер-лутер получает всё в момент кила — не он получатель
                pid = roster.player_of(nm)
                if not pid:
                    continue
                for entry, dt in obtained.get(nm, []):
                    if entry == lo.entry and (kt_utc - lead) <= dt <= (kt_utc + window):
                        # самое ПОЗДНЕЕ время: финальный держатель после трейда от ГМ
                        if pid not in receivers or dt > receivers[pid][1]:
                            receivers[pid] = (nm, dt)

            if receivers:
                # получатель = с самым поздним временем получения (конец цепочки трейдов)
                pid = max(receivers, key=lambda p: receivers[p][1])
                nm = receivers[pid][0]
                p = line_of.get(nm)
                award = _infer_award(item_db, lo.entry, p.class_id, p.spec, lo.name) if p else "bis"
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
                if len({p for p in receivers}) > 1:  # были и другие держатели — на проверку
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
