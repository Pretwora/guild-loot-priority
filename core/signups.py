"""Записи на рейд из raid-helper → небольшой бонус к рейтингу за ответственность.

Сопоставление игрока: сначала по Discord userid (стабильный ключ, если прописан в
roster как discord_id), иначе по имени персонажа из записи (с разбором скобок). Кого не
опознали — в отчёт сборки (с userid), чтобы РЛ один раз прописал discord_id в ростере.
"""

from __future__ import annotations

import glob
import json
import os
import re
from collections import defaultdict
from datetime import datetime

from core.common import REPO_ROOT


def _status(cls):
    if cls == "Absence":
        return "absence"
    if cls == "Tentative":
        return "tentative"
    return "signed"


def name_candidates(raw_name: str):
    """Кандидаты в имя персонажа из строки записи «Персонаж/Имя», «Ник(Перс)» и т.п."""
    cands = []
    main = re.split(r"[\/|]", raw_name)[0].strip()
    cands.append(main)
    cands.append(re.sub(r"\(.*?\)", "", main).strip())  # без хвостовых скобок
    cands += [x.strip() for x in re.findall(r"\(([^)]*)\)", raw_name)]  # содержимое скобок
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def load_events(cfg):
    out = []
    for path in glob.glob(os.path.join(REPO_ROOT, "data/raw/signups", "*.json")):
        d = json.load(open(path, encoding="utf-8"))
        ts = d.get("unixtime")
        when = datetime.utcfromtimestamp(ts) if ts else datetime.min
        out.append({"id": os.path.splitext(os.path.basename(path))[0],
                    "title": d.get("title"), "when": when, "signups": d.get("signups", [])})
    out.sort(key=lambda e: e["when"])
    return out


def _discord_map(roster):
    m = {}
    for pid, pl in roster.players.items():
        did = pl.get("discord_id")
        if did:
            m[str(did)] = pid
    return m


def _discord_char_map(cfg):
    """data/manual/discord_ids.yml: userid → имя персонажа (для ников в raid-helper)."""
    from core.common import load_yaml

    data = load_yaml(os.path.join(cfg.paths["manual"], "discord_ids.yml")) or {}
    return {str(k): v for k, v in data.items() if v}


def compute(cfg, roster):
    """Возвращает (bonus_by_player, signed_latest_set, unmatched, events).

    bonus_by_player: {pid: прибавка к merit}
    signed_latest_set: {pid} — записан на самый свежий ивент (для метки на дашборде)
    unmatched: [{name, userid, status, event}] — не сопоставлено с ростером
    """
    events = load_events(cfg)
    window = cfg.w("signup", "window_events")
    b_signed = cfg.w("signup", "bonus_signed")
    b_tent = cfg.w("signup", "bonus_tentative")
    cap = cfg.w("signup", "cap")
    dmap = _discord_map(roster)
    dchar = _discord_char_map(cfg)  # userid → имя персонажа (ники raid-helper)

    recent = events[-window:]
    counts = defaultdict(lambda: {"signed": 0, "tentative": 0, "absence": 0})
    unmatched, seen_unmatched = [], set()
    latest_signed = set()
    latest_id = recent[-1]["id"] if recent else None

    def resolve(su):
        did = str(su.get("userid") or "")
        if did in dmap:
            return dmap[did]
        if did in dchar:  # userid → персонаж → игрок (ники raid-helper)
            pid = roster.player_of(dchar[did])
            if pid:
                return pid
        for c in name_candidates(su.get("name", "")):
            pid = roster.player_of(c)
            if pid:
                return pid
        return None

    for ev in recent:
        for su in ev["signups"]:
            st = _status(su.get("class"))
            pid = resolve(su)
            if pid is None:
                key = su.get("userid") or su.get("name")
                if key not in seen_unmatched:
                    seen_unmatched.add(key)
                    unmatched.append({"name": su.get("name"), "userid": su.get("userid"),
                                      "status": st, "event": ev["title"]})
                continue
            counts[pid][st] += 1
            if ev["id"] == latest_id and st == "signed":
                latest_signed.add(pid)

    bonus = {}
    for pid, c in counts.items():
        bonus[pid] = round(min(cap, c["signed"] * b_signed + c["tentative"] * b_tent), 4)
    return bonus, latest_signed, unmatched, recent
