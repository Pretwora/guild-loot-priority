"""Детерминированный скоринг приоритета (раздел 7 SPEC).

LLM здесь не появляется: все числа считает Python (принцип 2). Каждая функция
возвращает не только итог, но и компоненты — они нужны для расшифровки на дашборде
(разделы 6.5, 7.6) и делают систему защитимой в споре.
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict

from core.common import Config, clip, days_between, decay_weight, load_yaml, median


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательное: игрок → основной (class_id, spec), присутствие по вечерам
# ─────────────────────────────────────────────────────────────────────────────


def player_main_spec(roster, kills, pid):
    """Основной (class_id, spec) игрока: из roster (main), иначе самый частый в логах."""
    pl = roster.players.get(pid, {})
    for ch in pl.get("characters", []) or []:
        if ch.get("main"):
            return ch.get("class_id"), ch.get("spec", 0)
    # fallback — самый частый персонаж в логах
    counts = defaultdict(int)
    names = {c["name"] for c in pl.get("characters", []) or []}
    for k in kills:
        for p in k.players:
            if p.name in names:
                counts[(p.class_id, p.spec)] += 1
    if counts:
        return max(counts, key=counts.get)
    return None, None


def night_presence_by_player(night, roster):
    """{player_id: presence 0..1} для вечера (макс по персонажам игрока)."""
    out = {}
    for char_name, pres in night.presence.items():
        pid = roster.player_of(char_name)
        if pid is None:
            continue
        out[pid] = max(out.get(pid, 0.0), pres)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# A — посещаемость (7.1)
# ─────────────────────────────────────────────────────────────────────────────


def select_window_nights(nights, cfg, now):
    """Последние 8 недель ИЛИ последние 12 вечеров — что больше (объединение)."""
    weeks = cfg.w("attendance", "window_weeks")
    n_nights = cfg.w("attendance", "window_nights")
    ordered = sorted(nights, key=lambda x: x.started_at, reverse=True)
    window = []
    for i, ni in enumerate(ordered):
        age_days = days_between(now, ni.started_at)
        if age_days <= weeks * 7 or i < n_nights:
            window.append(ni)
    return sorted(window, key=lambda x: x.started_at)  # хронологически


def _team_activity(window, roster, pres_by_night, cfg):
    """Для каждого вечера — какие команды его сыграли (≥ team_quorum состава)."""
    quorum = cfg.raw["raid_night"].get("team_quorum", 0.5)
    members = defaultdict(set)
    for pid, pl in roster.players.items():
        t = pl.get("team")
        if t:
            members[t].add(pid)
    ran = {}
    for ni in window:
        pres = pres_by_night[ni.date]
        ran[ni.date] = {
            t: (sum(1 for pid in mem if pres.get(pid, 0) > 0) / len(mem)) >= quorum
            for t, mem in members.items() if mem
        }
    return ran


def attendance_scores(nights, roster, cfg, now):
    manual = load_yaml(os.path.join(cfg.paths["manual"], "attendance.yml")) or {}
    window = select_window_nights(nights, cfg, now)

    lam = cfg.w("attendance", "decay_lambda")
    full_th = cfg.w("attendance", "present_full_threshold")
    bench_credit = cfg.w("attendance", "credit_bench")
    max_excused = cfg.w("attendance", "excused_max_consecutive")
    conf_nights = cfg.w("attendance", "confidence_nights")

    # presence по вечерам
    pres_by_night = {ni.date: night_presence_by_player(ni, roster) for ni in window}
    team_ran = _team_activity(window, roster, pres_by_night, cfg)

    per_player = {}
    for pid in roster.players:
        player_team = roster.players[pid].get("team")
        num = den = 0.0
        attended = 0
        excused_run = 0
        detail = []
        for ni in window:
            date = ni.date
            day = manual.get(date, {}) or {}
            bench = set(day.get("bench", []) or [])
            late = set(day.get("late", []) or [])
            excused = set(day.get("excused", []) or [])
            presence = pres_by_night[date].get(pid, 0.0)
            w = decay_weight(lam, days_between(now, ni.started_at))

            if pid in excused:
                excused_run += 1
                if excused_run <= max_excused:
                    detail.append({"date": date, "state": "excused", "credit": None, "weight": round(w, 3)})
                    continue  # вне знаменателя
                credit, state = 0.0, "excused>2"
            else:
                excused_run = 0
                if pid in bench:
                    credit, state = bench_credit, "bench"
                elif pid in late:
                    credit, state = presence, "late"
                elif presence >= full_th:
                    credit, state = 1.0, "full"
                elif presence > 0:
                    credit, state = presence, "partial"
                elif player_team and not team_ran.get(date, {}).get(player_team, True):
                    # вечер играла не его команда — вне знаменателя, не штраф
                    detail.append({"date": date, "state": "team_off", "credit": None, "weight": round(w, 3)})
                    continue
                else:
                    credit, state = 0.0, "absent"

            num += w * credit
            den += w
            if credit > 0:
                attended += 1
            detail.append({"date": date, "state": state, "credit": round(credit, 3), "weight": round(w, 3)})

        A = (num / den) if den > 0 else None
        conf = min(1.0, attended / conf_nights)
        per_player[pid] = {
            "A": A, "conf": conf, "nights_attended": attended,
            "nights_in_window": len(window), "detail": detail,
        }

    # сжатие к медиане гильдии (7.1): A_eff = A*conf + median*(1-conf)
    med = median([v["A"] for v in per_player.values() if v["A"] is not None]) or 0.0
    for v in per_player.values():
        A = v["A"] if v["A"] is not None else med
        v["A_median_guild"] = round(med, 4)
        v["A_eff"] = round(A * v["conf"] + med * (1 - v["conf"]), 4)
        v["A"] = round(A, 4)
    return per_player


# ─────────────────────────────────────────────────────────────────────────────
# P — перформанс (7.2)
# ─────────────────────────────────────────────────────────────────────────────


def _metric_for(line):
    if line.role == "tank":
        return None  # танк — нейтрально, метрики нет
    return line.dps if line.role == "dps" else line.hps


def performance_scores(kills, roster, cfg):
    min_sample = cfg.w("performance", "min_sample")
    neutral = cfg.w("performance", "neutral")
    window_kills = cfg.w("performance", "window_kills")

    # 1) пулы сравнения: (class_id, spec, role, boss) → список метрик
    pools = defaultdict(list)
    for k in kills:
        for p in k.players:
            m = _metric_for(p)
            if m is None:
                continue
            pools[(p.class_id, p.spec, p.role, k.boss_key)].append(m)

    def percentile(pool_key, value):
        pool = pools[pool_key]
        n = len(pool)
        if n < min_sample:
            return neutral, n
        less = sum(1 for v in pool if v < value)
        equal = sum(1 for v in pool if v == value)
        rank = less + (equal - 1) / 2.0  # средний ранг при ничьих
        return clip(rank / (n - 1), 0.0, 1.0) if n > 1 else neutral, n

    # 2) перцентиль на каждую строку игрока
    per_player_points = defaultdict(list)  # pid → [(killed_at, p, meta)]
    for k in kills:
        for p in k.players:
            pid = roster.player_of(p.name)
            if pid is None:
                continue
            if p.role == "tank":
                per_player_points[pid].append((k.killed_at, neutral, {
                    "boss": k.boss_name, "role": "tank", "p": neutral, "n": None, "metric": None}))
                continue
            m = _metric_for(p)
            pk = (p.class_id, p.spec, p.role, k.boss_key)
            pv, n = percentile(pk, m)
            per_player_points[pid].append((k.killed_at, pv, {
                "boss": k.boss_name, "role": p.role, "p": round(pv, 3), "n": n, "metric": m}))

    out = {}
    for pid in roster.players:
        pts = sorted(per_player_points.get(pid, []), key=lambda x: x[0])
        last = pts[-window_kills:]
        P = median([p for _, p, _ in last])
        out[pid] = {
            "P": round(P, 4) if P is not None else neutral,
            "kills_counted": len(last),
            "neutral_fallback": P is None,
            "recent": [m for _, _, m in last],
        }
        if P is None:
            out[pid]["P"] = neutral
    return out


# ─────────────────────────────────────────────────────────────────────────────
# L — полученный лут (7.3)
# ─────────────────────────────────────────────────────────────────────────────


def load_loot_log(cfg):
    path = os.path.join(cfg.paths["manual"], "loot_log.csv")
    from core.common import REPO_ROOT

    full = os.path.join(REPO_ROOT, path)
    if not os.path.exists(full):
        return []
    with open(full, encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if row.get("record_id")]


def loot_scores(loot_log, roster, item_db, cfg, now):
    from core.common import parse_server_time
    from datetime import datetime

    lam = cfg.w("loot", "decay_lambda")
    mults = cfg.w("loot", "award_type_mult")
    slot_w = cfg.w("loot", "slot_weight")
    clip_max = cfg.w("loot", "norm_clip_max")
    eps = cfg.w("loot", "norm_eps")

    raw = defaultdict(float)
    awards = defaultdict(list)
    last_slot_date = defaultdict(dict)  # pid → {slot: date}

    for row in loot_log:
        pid = (row.get("player") or "").strip()
        atype = (row.get("award_type") or "").strip().lower()
        if not pid:
            continue  # шард/никому — учитывается только для «незакрытых», не в L
        mult = mults.get(atype)
        if mult is None:
            continue  # shard/de — не учитывается вообще
        entry = int(row["item_entry"]) if str(row.get("item_entry", "")).isdigit() else None
        ic = item_db.classify(entry, row.get("item_name", "?")) if entry else None
        slot = ic.slot if ic else "unknown"
        weight = slot_w.get(slot, slot_w["unknown"])
        try:
            d = datetime.strptime(row["date"], "%Y-%m-%d")
        except Exception:
            d = now
        days = days_between(now, d)
        contrib = weight * mult * decay_weight(lam, days)
        raw[pid] += contrib
        awards[pid].append({
            "date": row["date"], "item": row.get("item_name"), "entry": entry,
            "slot": slot, "award_type": atype, "weight": weight, "mult": mult,
            "contribution": round(contrib, 3),
            "source": row.get("_source", "manual"),
            "record_id": row.get("record_id"),
        })
        # для slot_gap в Fit: последняя дата выдачи в слот (только реальные выдачи)
        if mult > 0:
            prev = last_slot_date[pid].get(slot)
            if prev is None or d > prev:
                last_slot_date[pid][slot] = d

    ladder_players = list(roster.players.keys())
    med = median([raw.get(pid, 0.0) for pid in ladder_players]) or 0.0

    out = {}
    for pid in ladder_players:
        L = raw.get(pid, 0.0)
        out[pid] = {
            "L": round(L, 4),
            "L_median_guild": round(med, 4),
            "L_norm": round(clip(L / (med + eps), 0.0, clip_max), 4),
            "awards": awards.get(pid, []),
            "last_slot_date": {s: d.strftime("%Y-%m-%d") for s, d in last_slot_date.get(pid, {}).items()},
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# S — итоговый рейтинг (7.4) + adjustments (6.4)
# ─────────────────────────────────────────────────────────────────────────────


def load_adjustments(cfg, now):
    data = load_yaml(os.path.join(cfg.paths["manual"], "adjustments.yml")) or {}
    from datetime import datetime

    active = []
    for a in data.get("adjustments", []) or []:
        exp = a.get("expires")
        if exp:
            try:
                if datetime.strptime(str(exp), "%Y-%m-%d") < now:
                    continue
            except Exception:
                pass
        active.append(a)
    return active


def final_scores(att, perf, loot, roster, cfg, now):
    scale = cfg.w("score", "scale")
    w_att = cfg.w("score", "w_attendance")
    w_perf = cfg.w("score", "w_perf")
    k_loot = cfg.w("score", "loot_penalty_k")
    gates = cfg.w("score", "rank_gate")
    adjustments = load_adjustments(cfg, now)
    adj_by_player = defaultdict(list)
    for a in adjustments:
        adj_by_player[a.get("player")].append(a)

    out = {}
    for pid, pl in roster.players.items():
        A_eff = att[pid]["A_eff"]
        P = perf[pid]["P"]
        L_norm = loot[pid]["L_norm"]
        rank = pl.get("rank", "member")
        gate = gates.get(rank, gates["member"])

        base = w_att * A_eff + w_perf * P
        adj_applied = []
        frozen = None
        for a in adj_by_player.get(pid, []):
            t = a.get("type")
            if t == "boost":
                base += a.get("value", 0)
                adj_applied.append(a)
            elif t == "penalty":
                base -= a.get("value", 0)
                adj_applied.append(a)
            elif t == "freeze":
                frozen = a
                adj_applied.append(a)
        base = clip(base, 0.0, 10.0)  # защита от абсурда после ручных правок совета

        S = scale * base / (1 + k_loot * L_norm) * gate
        if frozen and frozen.get("value") is not None:
            S = frozen["value"]

        out[pid] = {
            "S": round(S, 2),
            "base": round(base, 4),
            "rank": rank, "rank_gate": gate,
            "components": {"A_eff": A_eff, "P": P, "L_norm": L_norm},
            "adjustments": adj_applied,
            "frozen": bool(frozen),
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Fit и кандидаты на предмет (7.5, 7.6)
# ─────────────────────────────────────────────────────────────────────────────


def item_set_count(roster, kills, pid):
    """Текущее число тир-частей у игрока по последнему килу (из API itemset)."""
    names = {c["name"] for c in roster.players.get(pid, {}).get("characters", []) or []}
    best = 0
    latest = None
    for k in kills:
        for p in k.players:
            if p.name in names and (latest is None or k.killed_at > latest):
                latest = k.killed_at
                best = max((s.get("count", 0) for s in p.itemset), default=0)
    return best


def fit(entry, pid, roster, kills, loot, item_db, cfg, now, fallback_name="?"):
    from datetime import datetime

    class_id, spec = player_main_spec(roster, kills, pid)
    if class_id is None:
        return {"F": 0.0, "need": 0.0, "need_label": "none", "slot_gap": 0.0,
                "set_bonus": 1.0, "reason": "нет основного персонажа"}

    need_mult, need_label, need_reason = item_db.need_level(entry, class_id, spec, fallback_name)
    ic = item_db.classify(entry, fallback_name)

    # slot_gap: недель с последней выдачи в слот, насыщение на N недель
    sat = cfg.w("fit", "slot_gap_saturation_weeks")
    never = cfg.w("fit", "slot_gap_never")
    last = loot[pid]["last_slot_date"].get(ic.slot)
    if last is None:
        slot_gap = never
        gap_reason = "в этот слот ещё не получал"
    else:
        weeks = days_between(now, datetime.strptime(last, "%Y-%m-%d")) / 7.0
        slot_gap = clip(weeks / sat, 0.0, 1.0)
        gap_reason = f"с последней выдачи в слот {ic.slot}: {weeks:.0f} нед."

    # set_bonus: токен закрывает 2/4-сет
    set_bonus = cfg.w("fit", "set_bonus_default")
    if ic.tier_token:
        cnt = item_set_count(roster, kills, pid)
        if cnt in (1, 3):
            set_bonus = cfg.w("fit", "set_bonus_completes")

    F = need_mult * slot_gap * set_bonus
    return {
        "F": round(F, 4), "need": need_mult, "need_label": need_label,
        "slot": ic.slot, "slot_gap": round(slot_gap, 3), "set_bonus": set_bonus,
        "reason": f"{need_reason}; {gap_reason}",
    }


def candidates_for_item(entry, roster, kills, scores, loot, item_db, cfg, now, fallback_name="?"):
    """Топ-N кандидатов по S×F с разбивкой (7.6)."""
    top_n = cfg.w("candidates", "top_n")
    rows = []
    for pid in roster.players:
        S = scores[pid]["S"]
        f = fit(entry, pid, roster, kills, loot, item_db, cfg, now, fallback_name)
        if f["need"] <= 0:
            continue  # предмет не подходит игроку — не кандидат
        rows.append({
            "player": pid,
            "display": roster.players[pid].get("display", pid),
            "priority": round(S * f["F"], 3),
            "S": S, "fit": f,
        })
    rows.sort(key=lambda r: r["priority"], reverse=True)
    return rows[:top_n]
