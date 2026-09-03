"""Сборка dashboard.json — единственного контракта между ядром и фронтом (6.5).

Всё производное пересчитывается с нуля из неизменяемого сырья (принцип 1).
Дельта рейтинга «с прошлого рейда» тоже выводится из сырья: считаем скоринг дважды,
с отсечкой по времени до последнего вечера и после, — никакого сохранённого состояния.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import timedelta

from core.common import Config, server_now
from core import normalize as N
from core import scoring as SC
from core import loot_attrib as LA
from core import signups as SU
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


def compute(cfg, all_kills, scope_kills, roster, item_db, cutoff, combat, first_seen, signup_bonus=None):
    """Скоринг: посещаемость — только по РТ (attendance.raid_sizes) из ВСЕХ килов и общая
    для всех скоупов; перформанс/лут/вечера-для-показа — по килам скоупа."""
    ks = [k for k in scope_kills if k.killed_at is not None and k.killed_at <= cutoff]

    att_sizes = set(cfg.raw.get("attendance", {}).get("raid_sizes")
                    or cfg.raw["raid_night"]["count_raid_sizes"])
    att_kills = [k for k in all_kills
                 if k.killed_at is not None and k.killed_at <= cutoff and k.size_bucket in att_sizes]
    att_nights = N.build_nights(att_kills, cfg)
    att = SC.attendance_scores(att_nights, roster, cfg, cutoff, first_seen)

    nights = N.build_nights(ks, cfg)  # вечера скоупа — для экрана «Рейды»
    perf = SC.performance_scores(ks, roster, cfg, combat)

    # лут — только с рейдов loot.raid_sizes (РТ 25), из ВСЕХ килов и одинаково для всех
    # ладдеров: десятки лутом рейтинг не режут (как и посещаемость). Не зависит от скоупа.
    loot_sizes = set(cfg.raw.get("loot", {}).get("raid_sizes") or att_sizes)
    loot_kills = [k for k in all_kills if k.killed_at is not None
                  and k.killed_at <= cutoff and k.size_bucket in loot_sizes]

    manual = [r for r in SC.load_loot_log(cfg) if _row_before(r, cutoff)]
    auto_rows, ambiguous = LA.attribute(cfg, loot_kills, roster, item_db)
    auto_rows = [r for r in auto_rows if _row_before(r, cutoff)]
    loot_log = LA.merge_with_manual(manual, auto_rows)
    loot_records = {k.record_id for k in loot_kills}
    loot_log = [r for r in loot_log
                if str(r.get("record_id")).isdigit() and int(r["record_id"]) in loot_records]
    loot = SC.loot_scores(loot_log, roster, item_db, cfg, cutoff)
    final = SC.final_scores(att, perf, loot, roster, cfg, cutoff, signup_bonus)
    return {"nights": nights, "att": att, "att_nights": att_nights, "perf": perf, "loot": loot,
            "final": final, "loot_log": loot_log, "kills": ks, "loot_kills": loot_kills,
            "auto_count": len(auto_rows), "loot_ambiguous": ambiguous}


def _row_before(row, cutoff):
    from datetime import datetime

    try:
        return datetime.strptime(row["date"], "%Y-%m-%d") <= cutoff
    except Exception:
        return True


SIZE_LABEL = {10: "10-ки", 25: "25-ки"}


def _scope_defs(cfg):
    """Ладдеры по составу. Один размер (сейчас только 25) → один скоуп, без дублей.
    Несколько размеров → совокупность + каждый отдельно."""
    all_sizes = cfg.raw["raid_night"]["count_raid_sizes"]
    if len(all_sizes) == 1:
        s = all_sizes[0]
        return [(str(s), SIZE_LABEL.get(s, f"{s}-ки"), [s])]
    defs = [("all", "10 + 25" if set(all_sizes) == {10, 25} else "все", list(all_sizes))]
    for s in all_sizes:
        defs.append((str(s), SIZE_LABEL.get(s, f"{s}-ки"), [s]))
    return defs


def _scope(cfg, all_kills, roster, item_db, now, sizes, combat, first_seen, signup_bonus):
    counted = [k for k in all_kills if k.size_bucket in set(sizes)]
    cur = compute(cfg, all_kills, counted, roster, item_db, now, combat, first_seen, signup_bonus)
    prev_final = {}
    if len(cur["nights"]) >= 2:
        cutoff_prev = cur["nights"][-1].started_at - timedelta(seconds=1)
        prev_final = compute(cfg, all_kills, counted, roster, item_db, cutoff_prev, combat, first_seen, signup_bonus)["final"]
    return cur, prev_final, counted


def build(config_path="config/config.json"):
    cfg = Config(config_path)
    now = server_now(cfg.raw.get("server_utc_offset_hours", 0))
    roster = N.load_roster(cfg)
    item_db = ItemDB(cfg)
    combat = CombatDB(cfg)
    all_kills = N.load_kills(cfg)
    # 10-ки полностью вон из ВСЕЙ статистики (решение РЛ): фильтруем парсы на входе, дальше
    # весь пайплайн (авто-игроки, first_seen, посещаемость, перформанс, лут) видит только 25-ки.
    stat_sizes = set(cfg.raw["raid_night"]["count_raid_sizes"])
    all_kills = [k for k in all_kills if k.size_bucket in stat_sizes]
    N.augment_roster_with_parses(roster, all_kills, cfg)  # авто-игроки за парсы (сирус знает всех рейдивших)
    first_seen = N.first_seen_by_player(all_kills, roster, cfg)
    signup_bonus, signed_latest, signup_unmatched, signup_events = SU.compute(cfg, roster)

    scopes = []
    all_cur = all_counted = None
    for key, label, sizes in _scope_defs(cfg):
        # записи распространяются только на 25-ки: в ладдере без 25 бонус/✍ не применяются
        has25 = 25 in set(sizes)
        sb = signup_bonus if has25 else {}
        sl = signed_latest if has25 else frozenset()
        cur, prev_final, counted = _scope(cfg, all_kills, roster, item_db, now, sizes, combat, first_seen, sb)
        scopes.append({
            "key": key, "label": label, "sizes": sizes,
            "kills_counted": len(counted), "nights_count": len(cur["nights"]),
            "players": _players(cfg, roster, cur, item_db, prev_final, sl),
            "nights": _nights(cfg, roster, cur["nights"]),
        })
        if key == "all" or all_cur is None:  # источник для meta: 'all' если есть, иначе первый скоуп
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
        "issues": _issues(cfg, roster, all_counted, item_db, all_cur, signup_unmatched),
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
        "loot_raid_sizes": cfg.raw.get("loot", {}).get("raid_sizes", [25]),
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


def _recent_loot_map(roster, cur, item_db, n_kds=2):
    """{pid: [полученные предметы за последние n_kds КД]} с иконками — для наглядности в
    списке (лут на рейтинг не влияет, РЛ смотрит историю выдач глазами). Свежее сверху."""
    nights = sorted(cur["nights"], key=lambda n: n.started_at, reverse=True)
    dates = []
    for ni in nights:
        if ni.date not in dates:
            dates.append(ni.date)
        if len(dates) >= n_kds:
            break
    dateset = set(dates)

    icon_of, boss_of = {}, {}
    for k in cur.get("loot_kills", []):
        boss_of[str(k.record_id)] = k.boss_name
        for lo in k.loots:
            if lo.entry not in icon_of and getattr(lo, "icon", None):
                icon_of[lo.entry] = lo.icon

    disp_to_pid = {}
    for pid, pl in roster.players.items():
        disp_to_pid.setdefault(SC._norm_name(pid), pid)
        disp_to_pid.setdefault(SC._norm_name(pl.get("display", pid)), pid)

    out = defaultdict(list)
    for r in cur["loot_log"]:
        rp = (r.get("player") or "").strip()
        if not rp or r.get("date") not in dateset:
            continue
        pid = rp if rp in roster.players else disp_to_pid.get(SC._norm_name(rp), rp)
        entry = int(r["item_entry"]) if str(r.get("item_entry", "")).isdigit() else None
        ic = item_db.classify(entry, r.get("item_name", "?")) if entry else None
        award = (r.get("award_type") or "").strip().lower()
        if award in ("shard", "de"):
            continue  # распылён — не выдача игроку
        out[pid].append({
            "item": r.get("item_name"), "entry": entry, "icon": icon_of.get(entry),
            "slot": ic.slot if ic else "?", "ilvl": (ic.ilvl if ic else 0),
            "date": r.get("date"), "boss": boss_of.get(str(r.get("record_id")), ""),
        })
    for pid in out:
        out[pid].sort(key=lambda x: (x["date"], x["item"] or ""), reverse=True)
    return dict(out)


def _players(cfg, roster, cur, item_db, prev_final, signed_latest=frozenset()):
    recent_loot = _recent_loot_map(roster, cur, item_db)
    show_dps = cfg.raw["display"]["show_raw_dps"]
    rows = []
    for pid, pl in roster.players.items():
        class_id, spec = SC.player_main_spec(roster, cur["kills"], pid)
        final = cur["final"][pid]
        perf = dict(cur["perf"][pid])
        if not show_dps:  # прячем сырые dps/hps, оставляем перцентили (раздел 11)
            perf["recent"] = [{k: v for k, v in m.items() if k != "metric"} for m in perf.get("recent", [])]
        delta = None
        delta_parts = None
        if pid in prev_final:
            delta = round(final["S"] - prev_final[pid]["S"], 2)
            delta_parts = _delta_breakdown(cfg, final, prev_final[pid], delta)
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
            "delta_parts": delta_parts,
            "base": final["base"],
            "rank_gate": final["rank_gate"],
            "frozen": final["frozen"],
            "perf_measured": final["perf_measured"],
            "signup_bonus": final.get("signup_bonus", 0.0),
            "signed_up": pid in signed_latest,
            "adjustments": final["adjustments"],
            "components": final["components"],
            "attendance": cur["att"][pid],
            "performance": perf,
            "loot": cur["loot"][pid],
            "recent_loot": recent_loot.get(pid, []),
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def _delta_breakdown(cfg, now, prev, total):
    """ΔS → вклады посещаемости / перформанса / лута (последовательно, сумма = ΔS).
    S нелинейна (лут в делителе), поэтому раскладываем путём: меняем компоненты по одному."""
    scale = cfg.w("score", "scale")
    wa = cfg.w("score", "w_attendance")
    wp = cfg.w("score", "w_perf")
    k = cfg.w("score", "loot_penalty_k")
    gate = now.get("rank_gate", 1.0)
    measured = now.get("perf_measured", True)
    sg = now["components"].get("signup", 0.0)  # бонус записи — константа между отсечками

    def S(A, P, L):
        base = (wa * A + wp * P) if (measured and P is not None) else (wa + wp) * A
        return scale * (base + sg) / (1 + k * L) * gate

    cn, cp = now["components"], prev["components"]
    an, pn, ln = cn["A_eff"], cn["P"], cn["L_norm"]
    ap, pp, lp = cp["A_eff"], cp["P"], cp["L_norm"]
    d_att = S(an, pp, lp) - S(ap, pp, lp)
    d_perf = S(an, pn, lp) - S(an, pp, lp)
    d_loot = S(an, pn, ln) - S(an, pn, lp)
    other = total - (d_att + d_perf + d_loot)  # заморозка / ручные правки / смена gate
    return {"attendance": round(d_att, 1), "performance": round(d_perf, 1),
            "loot": round(d_loot, 1), "other": round(other, 1)}


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
    for k in cur["loot_kills"]:  # незакрытые — только по 25-кам (лут-размеры), как и штраф
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


def _issues(cfg, roster, counted, item_db, cur, signup_unmatched=None):
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
        "signup_unmatched": signup_unmatched or [],
    }


def _unclosed_ids(cfg, cur):
    logged = {(str(r.get("record_id")), str(r.get("item_entry")))
              for r in cur["loot_log"] if (r.get("player") or "").strip()}
    ids = []
    for k in cur["loot_kills"]:  # незакрытые — только по 25-кам (лут-размеры)
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
