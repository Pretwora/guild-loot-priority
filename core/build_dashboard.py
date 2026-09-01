"""Сборка dashboard.json — единственного контракта между ядром и фронтом (6.5).

Всё производное пересчитывается с нуля из неизменяемого сырья (принцип 1).
Дельта рейтинга «с прошлого рейда» тоже выводится из сырья: считаем скоринг дважды,
с отсечкой по времени до последнего вечера и после, — никакого сохранённого состояния.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import timedelta

from core.common import Config, server_now
from core import normalize as N
from core import scoring as SC
from core import loot_attrib as LA
from core.combat import CombatDB
from core.items import ItemDB

# Порядок слотов для лут-борда (раздел 9.1, экран 2)
SLOT_ORDER = [
    "head", "neck", "shoulder", "back", "chest", "wrist", "hands",
    "waist", "legs", "feet", "finger", "trinket",
    "one_hand", "two_hand", "ranged",
]


def _counted(kills, cfg):
    sizes = set(cfg.raw["raid_night"]["count_raid_sizes"])
    return [k for k in kills if k.size_bucket in sizes]


def compute(cfg, kills, roster, item_db, cutoff, combat=None):
    """Полный скоринг по килам с killed_at <= cutoff."""
    ks = [k for k in kills if k.killed_at is not None and k.killed_at <= cutoff]
    nights = N.build_nights(ks, cfg)
    att = SC.attendance_scores(nights, roster, cfg, cutoff)
    perf = SC.performance_scores(ks, roster, cfg, combat)

    manual = [r for r in SC.load_loot_log(cfg) if _row_before(r, cutoff)]
    auto_rows, ambiguous = LA.attribute(cfg, ks, roster, item_db)
    auto_rows = [r for r in auto_rows if _row_before(r, cutoff)]
    loot_log = LA.merge_with_manual(manual, auto_rows)
    loot = SC.loot_scores(loot_log, roster, item_db, cfg, cutoff)
    final = SC.final_scores(att, perf, loot, roster, cfg, cutoff)
    return {"nights": nights, "att": att, "perf": perf, "loot": loot,
            "final": final, "loot_log": loot_log, "kills": ks,
            "auto_count": len(auto_rows), "loot_ambiguous": ambiguous}


def _row_before(row, cutoff):
    from datetime import datetime

    try:
        return datetime.strptime(row["date"], "%Y-%m-%d") <= cutoff
    except Exception:
        return True


SIZE_LABEL = {10: "10-ки", 25: "25-ки"}


def _scope_defs(cfg):
    """Ладдеры: совокупность и каждый размер отдельно (запрос РЛ — видеть активность
    по 10-кам, по 25-кам и суммарно)."""
    all_sizes = cfg.raw["raid_night"]["count_raid_sizes"]
    defs = [("all", "10 + 25" if set(all_sizes) == {10, 25} else "все", list(all_sizes))]
    for s in all_sizes:
        defs.append((str(s), SIZE_LABEL.get(s, f"{s}-ки"), [s]))
    return defs


def _scope(cfg, all_kills, roster, item_db, now, sizes, combat):
    counted = [k for k in all_kills if k.size_bucket in set(sizes)]
    cur = compute(cfg, counted, roster, item_db, now, combat)
    prev_final = {}
    if len(cur["nights"]) >= 2:
        cutoff_prev = cur["nights"][-1].started_at - timedelta(seconds=1)
        prev_final = compute(cfg, counted, roster, item_db, cutoff_prev, combat)["final"]
    return cur, prev_final, counted


def build(config_path="config/config.json"):
    cfg = Config(config_path)
    now = server_now(cfg.raw.get("server_utc_offset_hours", 0))
    roster = N.load_roster(cfg)
    item_db = ItemDB(cfg)
    combat = CombatDB(cfg)
    all_kills = N.load_kills(cfg)

    scopes = []
    all_cur = all_counted = None
    for key, label, sizes in _scope_defs(cfg):
        cur, prev_final, counted = _scope(cfg, all_kills, roster, item_db, now, sizes, combat)
        scopes.append({
            "key": key, "label": label, "sizes": sizes,
            "kills_counted": len(counted), "nights_count": len(cur["nights"]),
            "players": _players(cfg, roster, cur, prev_final),
            "nights": _nights(cfg, roster, cur["nights"]),
        })
        if key == "all":
            all_cur, all_counted = cur, counted

    dash = {
        "schema_version": cfg.raw.get("schema_version", 1),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S") + " (server local)",
        "meta": _meta(cfg, all_kills, all_counted, all_cur["nights"], combat),
        "scopes": scopes,
        # верхнеуровневые players/nights = совокупность (совместимость и дефолт)
        "players": scopes[0]["players"],
        "nights": scopes[0]["nights"],
        "lootboard": _lootboard(cfg, roster, all_cur),
        "unclosed_drops": _unclosed(cfg, roster, all_cur, item_db, now),
        "issues": _issues(cfg, roster, all_counted, item_db, all_cur),
        "formula": _formula(cfg),
    }

    out_path = os.path.join(_repo(), cfg.paths["dashboard"])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dash, f, ensure_ascii=False, indent=1)
    return dash, out_path


def _repo():
    from core.common import REPO_ROOT

    return REPO_ROOT


# ── секции dashboard.json ──


def _meta(cfg, all_kills, counted, nights, combat):
    combat_kills = sum(1 for k in counted if combat.has(k.record_id))
    return {
        "realm": cfg.raw["realm"],
        "guild_id": cfg.raw["guild_id"],
        "tier": cfg.raw["tier"]["name"],
        "kills_total": len(all_kills),
        "kills_counted": len(counted),
        "nights_count": len(nights),
        "count_raid_sizes": cfg.raw["raid_night"]["count_raid_sizes"],
        "window": {"weeks": cfg.w("attendance", "window_weeks"),
                   "nights": cfg.w("attendance", "window_nights")},
        "show_raw_dps": cfg.raw["display"]["show_raw_dps"],
        "tier_start": cfg.raw["tier"]["start"],
        "combat": {
            "kills_with_log": combat_kills,
            "kills_counted": len(counted),
            "consumable_tracking": combat.consumable_active,
        },
    }


def _players(cfg, roster, cur, prev_final):
    show_dps = cfg.raw["display"]["show_raw_dps"]
    rows = []
    for pid, pl in roster.players.items():
        class_id, spec = SC.player_main_spec(roster, cur["kills"], pid)
        final = cur["final"][pid]
        perf = dict(cur["perf"][pid])
        if not show_dps:  # прячем сырые dps/hps, оставляем перцентили (раздел 11)
            perf["recent"] = [{k: v for k, v in m.items() if k != "metric"} for m in perf.get("recent", [])]
        delta = None
        if pid in prev_final:
            delta = round(final["S"] - prev_final[pid]["S"], 2)
        rows.append({
            "id": pid,
            "display": pl.get("display", pid),
            "rank": pl.get("rank", "member"),
            "class_id": class_id,
            "class_name": cfg.class_name(class_id) if class_id else "?",
            "class_color": cfg.class_color(class_id) if class_id else "808080",
            "spec": spec,
            "spec_name": cfg.spec_name(class_id, spec) if class_id is not None else "?",
            "score": final["S"],
            "delta": delta,
            "base": final["base"],
            "rank_gate": final["rank_gate"],
            "frozen": final["frozen"],
            "adjustments": final["adjustments"],
            "components": final["components"],
            "attendance": cur["att"][pid],
            "performance": perf,
            "loot": cur["loot"][pid],
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def _nights(cfg, roster, nights):
    out = []
    manual = _manual_attendance(cfg)
    for ni in sorted(nights, key=lambda x: x.started_at, reverse=True):
        pres = SC.night_presence_by_player(ni, roster)
        day = manual.get(ni.date, {}) or {}
        bench, late, excused = set(day.get("bench", []) or []), set(day.get("late", []) or []), set(day.get("excused", []) or [])
        present = [{"id": pid, "display": roster.players[pid].get("display", pid),
                    "class_color": _color(cfg, roster, pid), "presence": round(v, 2)}
                   for pid, v in sorted(pres.items(), key=lambda x: -x[1])]
        present_ids = set(pres.keys())
        absent = [pid for pid in roster.players
                  if pid not in present_ids and pid not in bench and pid not in excused]
        bosses = []
        seen = set()
        for k in ni.kills:
            if k.boss_name not in seen:
                seen.add(k.boss_name)
                bosses.append(k.boss_name)
        out.append({
            "date": ni.date,
            "started_at": ni.started_at.strftime("%H:%M"),
            "ended_at": ni.ended_at.strftime("%H:%M"),
            "size": ni.size_bucket,
            "kill_count": ni.kill_count,
            "bosses": bosses,
            "present": present,
            "bench": sorted(bench), "late": sorted(late), "excused": sorted(excused),
            "absent": absent,
        })
    return out


def _lootboard(cfg, roster, cur):
    """Матрица слот × игрок: дата последней выдачи в слот (или пусто = нужно)."""
    players = []
    for pid, pl in roster.players.items():
        last = cur["loot"][pid]["last_slot_date"]
        players.append({
            "id": pid, "display": pl.get("display", pid),
            "class_color": _color(cfg, roster, pid),
            "rank": pl.get("rank", "member"),
            "score": cur["final"][pid]["S"],
            "per_slot": {slot: last.get(slot) for slot in SLOT_ORDER},
        })
    players.sort(key=lambda r: r["score"], reverse=True)
    return {"slots": SLOT_ORDER, "players": players}


def _unclosed(cfg, roster, cur, item_db, now):
    """Дропы качества 4+ (шмот, не валюта) в зачётных килах без записи в loot_log."""
    logged = set()
    for r in cur["loot_log"]:
        rid = str(r.get("record_id"))
        entry = str(r.get("item_entry"))
        if (r.get("player") or "").strip():
            logged.add((rid, entry))
    min_q = cfg.raw["loot"]["min_quality"]
    out = []
    for k in cur["kills"]:
        for lo in k.loots:
            if lo.is_currency or lo.quality < min_q or lo.count != 1:
                continue
            if (str(k.record_id), str(lo.entry)) in logged:
                continue
            cands = SC.candidates_for_item(lo.entry, roster, cur["kills"], cur["final"],
                                           cur["loot"], item_db, cfg, now, lo.name)
            ic = item_db.classify(lo.entry, lo.name)
            out.append({
                "record_id": k.record_id, "date": k.killed_at.strftime("%Y-%m-%d"),
                "boss": k.boss_name, "entry": lo.entry, "item": lo.name,
                "quality": lo.quality, "icon": lo.icon, "slot": ic.slot,
                "ambiguous": ic.ambiguous, "candidates": cands,
            })
    # свежие сверху
    out.sort(key=lambda d: d["date"], reverse=True)
    return out


def _issues(cfg, roster, counted, item_db, cur):
    unknown = N.unknown_characters(counted, roster, cfg)
    # неразмеченные предметы среди упавших
    seen, unmarked = set(), []
    for k in counted:
        for lo in k.loots:
            if lo.is_currency or lo.quality < cfg.raw["loot"]["min_quality"] or lo.count != 1:
                continue
            if lo.entry in seen:
                continue
            seen.add(lo.entry)
            ic = item_db.classify(lo.entry, lo.name)
            if ic.ambiguous:
                unmarked.append({"entry": lo.entry, "name": lo.name, "reason": ic.reason})
    return {
        "unknown_characters": unknown,
        "unmarked_items": unmarked,
        "unclosed_count": len(_unclosed_ids(cfg, cur)),
        "loot_auto_count": cur.get("auto_count", 0),
        "loot_ambiguous": cur.get("loot_ambiguous", []),
    }


def _unclosed_ids(cfg, cur):
    logged = {(str(r.get("record_id")), str(r.get("item_entry")))
              for r in cur["loot_log"] if (r.get("player") or "").strip()}
    ids = []
    for k in cur["kills"]:
        for lo in k.loots:
            if lo.is_currency or lo.quality < cfg.raw["loot"]["min_quality"] or lo.count != 1:
                continue
            if (str(k.record_id), str(lo.entry)) not in logged:
                ids.append((k.record_id, lo.entry))
    return ids


def _formula(cfg):
    """Данные для страницы «Как это считается» — из weights.yml, не из кода."""
    return {
        "weights": cfg.weights,
        "classes": {str(cid): {"name": info["name"], "color": info["color"]}
                    for cid, info in (cfg.specs.get("classes") or {}).items()},
        "note": "Веса заморожены на тир. Меняются только через PR с обоснованием (принцип 6).",
    }


def _manual_attendance(cfg):
    from core.common import load_yaml

    return load_yaml(os.path.join(cfg.paths["manual"], "attendance.yml")) or {}


def _color(cfg, roster, pid):
    class_id, _ = SC.player_main_spec(roster, [], pid)
    if class_id is None:
        for ch in roster.players.get(pid, {}).get("characters", []) or []:
            class_id = ch.get("class_id")
            break
    return cfg.class_color(class_id) if class_id else "808080"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    args = ap.parse_args()
    dash, path = build(args.config)
    print(f"dashboard.json: {path}")
    print(f"  игроков: {len(dash['players'])}, вечеров: {len(dash['nights'])}, "
          f"незакрытых дропов: {len(dash['unclosed_drops'])}")
    print(f"  неизвестных персонажей: {len(dash['issues']['unknown_characters'])}, "
          f"неразмеченных предметов: {len(dash['issues']['unmarked_items'])}")


if __name__ == "__main__":
    main()
