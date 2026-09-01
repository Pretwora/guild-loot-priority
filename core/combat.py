"""Метрики эффективности из компактной выжимки лога боя (этап 3+).

Даёт покилово на игрока: полученный урон/сек (танки), смерти, перебивания, диспелы,
факт боевого расходника. Перебивания/диспелы/расходники опознаются по config/combat.yml
детерминированно — каталог правится без перекачки логов. Что не опознано — не учитывается.
"""

from __future__ import annotations

import glob
import json
import os

from core.common import REPO_ROOT


class CombatDB:
    def __init__(self, cfg):
        self.cfg = cfg
        self.by_record = _load(cfg)
        cat = _load_catalog()
        self._int_names = [s.lower() for s in cat["interrupts"].get("name_contains", [])]
        self._int_ids = {str(x) for x in cat["interrupts"].get("spell_ids", [])}
        self._dis_names = [s.lower() for s in cat["dispels"].get("name_contains", [])]
        self._dis_ids = {str(x) for x in cat["dispels"].get("spell_ids", [])}
        self._cons_ids = {str(x) for x in (cat.get("consumables") or {}).get("aura_ids", [])}
        self._consumable_active = self._compute_consumable_coverage()

    def has(self, record_id) -> bool:
        return int(record_id) in self.by_record

    def metrics(self, record_id, guid):
        rec = self.by_record.get(int(record_id))
        if not rec:
            return None
        p = (rec.get("players") or {}).get(str(guid))
        if not p:
            return None
        duration = rec.get("duration") or 0
        names = rec.get("spell_names", {})
        casts = p.get("casts", {}) or {}
        interrupts = _count(casts, names, self._int_ids, self._int_names)
        dispels = _count(casts, names, self._dis_ids, self._dis_names)
        auras = p.get("auras", {}) or {}
        has_cons = any(sid in self._cons_ids for sid in auras) if self._cons_ids else None
        taken = p.get("taken", 0) or 0
        return {
            "taken": taken,
            "taken_ps": (taken / duration) if duration else 0.0,
            "done": p.get("done", 0) or 0,
            "healing": p.get("healing", 0) or 0,
            "deaths": p.get("deaths", 0) or 0,
            "interrupts": interrupts,
            "dispels": dispels,
            "utility": interrupts + dispels,
            "has_consumable": has_cons,
        }

    @property
    def consumable_active(self):
        return self._consumable_active

    def _compute_consumable_coverage(self):
        """Safety-valve: если расходники опознаны у слишком малой доли — каталог не совпал."""
        if not self._cons_ids:
            return False
        seen = total = 0
        for rec in self.by_record.values():
            for guid, p in (rec.get("players") or {}).items():
                total += 1
                if any(sid in self._cons_ids for sid in (p.get("auras") or {})):
                    seen += 1
        if total == 0:
            return False
        coverage = seen / total
        return coverage >= self.cfg.w("performance", "consumable_min_coverage")


def _count(casts, names, ids, name_subs):
    total = 0
    for sid, cnt in casts.items():
        nm = (names.get(sid) or "").lower()
        if sid in ids or any(sub in nm for sub in name_subs):
            total += cnt
    return total


def _load(cfg):
    realm = cfg.raw["realm"]
    root = os.path.join(REPO_ROOT, cfg.paths["raw"], "combat", realm)
    out = {}
    for path in glob.glob(os.path.join(root, "*.json")):
        try:
            d = json.load(open(path, encoding="utf-8"))
            out[int(d.get("record_id") or os.path.splitext(os.path.basename(path))[0])] = d
        except Exception:
            continue
    return out


def _load_catalog():
    from core.common import load_yaml

    cat = load_yaml("config/combat.yml") or {}
    cat.setdefault("interrupts", {})
    cat.setdefault("dispels", {})
    cat.setdefault("consumables", {})
    return cat
