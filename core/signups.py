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
    """Возвращает (bonus, signed_latest, unmatched, event_respondents, penalized_latest).

    bonus: {pid: суммарная прибавка за записи по окну} — signed/tentative/absence, БЕЗ капа
        (копится за каждый ивент).
    signed_latest: {pid} — статус «приду» на самом свежем ивенте (метка ✍).
    unmatched: [{name, userid, status, event}] — не сопоставлено с ростером.
    event_respondents: [(when, frozenset(pid))] по каждому ивенту окна — для штрафа за незапись
        (за КАЖДЫЙ ивент, где активный игрок не отметился; гейт по посещаемости/дате в build).
    penalized_latest: {pid} — не отметился на самый свежий ивент (метка ⚠️; гейт по посещаемости в build).
    """
    events = load_events(cfg)
    window = cfg.w("signup", "window_events")
    b_signed = cfg.w("signup", "bonus_signed")
    b_tent = cfg.w("signup", "bonus_tentative")
    b_abs = cfg.w("signup", "bonus_absence")
    dmap = _discord_map(roster)
    dchar = _discord_char_map(cfg)  # userid → имя персонажа (ники raid-helper)

    recent = events[-window:]
    counts = defaultdict(lambda: {"signed": 0, "tentative": 0, "absence": 0})
    unmatched, seen_unmatched = [], set()
    latest_signed = set()
    latest_respondents = set()  # кто вообще отметился на последний РТ (любой статус)
    latest_id = recent[-1]["id"] if recent else None
    event_respondents = []  # (when, frozenset(pid)) по каждому ивенту — для per-event штрафа

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
        resp = set()  # кто отметился на ЭТОМ ивенте (любой статус)
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
            resp.add(pid)
            if ev["id"] == latest_id:
                latest_respondents.add(pid)  # отметился (signed/tentative/absence) — не штрафуем
                if st == "signed":
                    latest_signed.add(pid)
        event_respondents.append((ev["when"], frozenset(resp)))

    bonus = {}
    for pid, c in counts.items():
        # без капа: за каждый ивент +весы по статусу (приду > может быть > не приду)
        bonus[pid] = round(c["signed"] * b_signed + c["tentative"] * b_tent + c["absence"] * b_abs, 4)
    # penalized_latest — метка ⚠️ «не отметился на последний РТ». Сам штраф считается per-event
    # в build_dashboard.compute (по event_respondents), гейт по посещаемости/дате вступления.
    penalized_latest = {pid for pid in roster.players if latest_id is not None and pid not in latest_respondents}
    return bonus, latest_signed, unmatched, event_respondents, penalized_latest
