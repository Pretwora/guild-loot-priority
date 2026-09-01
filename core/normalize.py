"""Сырьё → рейд-вечера, участие, метрики (этап 2 SPEC).

Единственный модуль, которому разрешено падать при смене схемы API: сырьё лежит
неизменяемым, всё производное пересчитывается отсюда с нуля (принципы 1 и 4 SPEC).
"""

from __future__ import annotations

import datetime as _dt
import glob
import os
from dataclasses import dataclass, field

from core.common import Config, parse_server_time


# ─────────────────────────────────────────────────────────────────────────────
# Нормализованные структуры
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PlayerLine:
    name: str
    guid: int
    class_id: int
    spec: int
    role: str  # tank | heal | dps (замаплено из API role 1/2/3)
    dps: int
    hps: int
    ilvl: int
    guild_name: str
    itemset: list  # [{id, name, count}] — текущий тир-сет игрока


@dataclass
class LootDrop:
    entry: int
    name: str
    quality: int
    count: int
    icon: str
    is_currency: bool


@dataclass
class Kill:
    record_id: int
    killed_at: object  # datetime, серверное локальное
    map_id: int
    map_name: str
    boss_name: str
    encounter_id: int
    difficulty: int
    player_count: int
    size_bucket: int | None  # 10 | 25 | None (вне бакетов)
    players: list = field(default_factory=list)
    loots: list = field(default_factory=list)

    @property
    def boss_key(self):
        # Ключ босса для перформанса: инстанс + энкаунтер (стабильно, из ленты и деталей).
        return (self.map_id, self.encounter_id)


@dataclass
class RaidNight:
    date: str  # YYYY-MM-DD, серверная локальная дата первого кила
    started_at: object
    ended_at: object
    size_bucket: int | None
    kills: list = field(default_factory=list)  # list[Kill]
    # presence[name] = доля килов вечера, в которых персонаж присутствовал (0..1)
    presence: dict = field(default_factory=dict)

    @property
    def kill_count(self):
        return len(self.kills)


# ─────────────────────────────────────────────────────────────────────────────
# Классификация
# ─────────────────────────────────────────────────────────────────────────────


def size_bucket(player_count: int, cfg: Config) -> int | None:
    for b in cfg.raw["raid_night"]["size_buckets"]:
        if b["min"] <= player_count <= b["max"]:
            return b["size"]
    return None


def _is_currency(item: dict, name: str, cfg: Config) -> bool:
    loot_cfg = cfg.raw["loot"]
    if item.get("entry") in loot_cfg["currency_entry_denylist"]:
        return True
    return any(marker in name for marker in loot_cfg["currency_name_markers"])


# ─────────────────────────────────────────────────────────────────────────────
# Загрузка сырья
# ─────────────────────────────────────────────────────────────────────────────


def load_kills(cfg: Config, realm: str | None = None) -> list[Kill]:
    """Читает все data/raw/bossfight/{realm}/*.json в нормализованные Kill."""
    from core.common import REPO_ROOT

    realm = realm or cfg.raw["realm"]
    root = os.path.join(REPO_ROOT, cfg.paths["raw"], "bossfight", realm)
    kills = [_parse_kill(p, cfg) for p in sorted(glob.glob(os.path.join(root, "*.json")))]
    kills = [k for k in kills if k is not None]
    kills.sort(key=lambda k: (k.killed_at or _dt.datetime.min))
    return kills


def _parse_kill(path: str, cfg: Config) -> Kill | None:
    from core.common import load_json

    raw = load_json(path)
    body = raw.get("data", raw) if isinstance(raw, dict) else None
    if not isinstance(body, dict):
        return None

    record_id = int(os.path.splitext(os.path.basename(path))[0])
    killed_at = parse_server_time(body.get("killed_at"))

    players = []
    for p in body.get("players", []) or []:
        players.append(
            PlayerLine(
                name=p.get("name", "?"),
                guid=p.get("guid", 0),
                class_id=p.get("class_id", 0),
                spec=p.get("spec", 0),
                role=cfg.role_from_api(p.get("role")),
                dps=p.get("dps", 0) or 0,
                hps=p.get("hps", 0) or 0,
                ilvl=p.get("ilvl", 0) or 0,
                guild_name=(p.get("guild") or {}).get("name", ""),
                itemset=p.get("itemset", []) or [],
            )
        )

    loots = []
    for lo in body.get("loots", []) or []:
        item = lo.get("item", {}) or {}
        name = item.get("name", "?")
        loots.append(
            LootDrop(
                entry=item.get("entry") or lo.get("entry"),
                name=name,
                quality=item.get("quality", 0) or 0,
                count=lo.get("count", 1) or 1,
                icon=item.get("icon", ""),
                is_currency=_is_currency(item, name, cfg),
            )
        )

    pc = body.get("player_count")
    if pc is None:
        pc = len(players)

    return Kill(
        record_id=record_id,
        killed_at=killed_at,
        map_id=body.get("map_id") or body.get("mapId") or 0,
        map_name=body.get("map_name", "?"),
        boss_name=body.get("boss_name", "?"),
        encounter_id=raw.get("encounter", body.get("encounter_id", 0)) or 0,
        difficulty=body.get("difficulty", 0) or 0,
        player_count=pc,
        size_bucket=size_bucket(pc, cfg),
        players=players,
        loots=loots,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Рейд-вечера
# ─────────────────────────────────────────────────────────────────────────────


def build_nights(kills: list[Kill], cfg: Config) -> list[RaidNight]:
    """Группирует килы в вечера: разрыв > gap_hours (серверное время) — новый вечер."""
    gap_hours = cfg.w("raid_night", "gap_hours")
    dated = [k for k in kills if k.killed_at is not None]
    dated.sort(key=lambda k: k.killed_at)

    nights: list[RaidNight] = []
    current: list[Kill] = []
    for k in dated:
        if current and (k.killed_at - current[-1].killed_at).total_seconds() > gap_hours * 3600:
            nights.append(_finish_night(current))
            current = []
        current.append(k)
    if current:
        nights.append(_finish_night(current))
    return nights


def _finish_night(kills: list[Kill]) -> RaidNight:
    kills = sorted(kills, key=lambda k: k.killed_at)
    start, end = kills[0].killed_at, kills[-1].killed_at

    # presence: доля килов вечера, в которых персонаж встречается
    present_counts: dict[str, int] = {}
    for k in kills:
        seen = {p.name for p in k.players}
        for name in seen:
            present_counts[name] = present_counts.get(name, 0) + 1
    n = len(kills)
    presence = {name: c / n for name, c in present_counts.items()}

    # размер вечера — доминирующий бакет по килам
    buckets = [k.size_bucket for k in kills if k.size_bucket is not None]
    dominant = max(set(buckets), key=buckets.count) if buckets else None

    return RaidNight(
        date=start.strftime("%Y-%m-%d"),
        started_at=start,
        ended_at=end,
        size_bucket=dominant,
        kills=kills,
        presence=presence,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Ростер: персонаж → игрок, отчёт о неизвестных
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Roster:
    char_to_player: dict  # имя персонажа → player_id
    players: dict  # player_id → метаданные игрока (display, rank, characters, ...)

    def player_of(self, char_name: str):
        return self.char_to_player.get(char_name)


def load_roster(cfg: Config) -> Roster:
    from core.common import load_yaml

    data = load_yaml(os.path.join(cfg.paths["manual"], "roster.yml")) or {}
    char_to_player, players = {}, {}
    for pl in data.get("players", []) or []:
        pid = pl["id"]
        players[pid] = pl
        for ch in pl.get("characters", []) or []:
            char_to_player[ch["name"]] = pid
    return Roster(char_to_player=char_to_player, players=players)


def first_seen_by_player(kills: list[Kill], roster: Roster) -> dict:
    """{player_id: самый ранний killed_at, где встречен любой его персонаж}.

    Прокси даты вступления в гильдию: рейды до этого — «не пока мы в гильдии»,
    в знаменатель посещаемости не идут. roster joined (если задан) имеет приоритет.
    """
    import datetime as _dt

    out: dict = {}
    for k in sorted(kills, key=lambda x: x.killed_at or _dt.datetime.max):
        if k.killed_at is None:
            continue
        for p in k.players:
            pid = roster.player_of(p.name)
            if pid and pid not in out:
                out[pid] = k.killed_at
    # приоритет — явный joined из ростера
    for pid, pl in roster.players.items():
        joined = pl.get("joined")
        if joined:
            try:
                jd = _dt.datetime.strptime(str(joined), "%Y-%m-%d")
                out[pid] = jd  # ростер авторитетнее прокси
            except ValueError:
                pass
    return out


def unknown_characters(kills: list[Kill], roster: Roster, cfg: Config) -> list[dict]:
    """Персонажи из логов, которых нет в ростере. Разделяем наших и пугов по гильдии."""
    our_guild = cfg.raw.get("guild_name_api", "")
    seen: dict[str, dict] = {}
    for k in kills:
        for p in k.players:
            if roster.player_of(p.name):
                continue
            rec = seen.setdefault(
                p.name,
                {
                    "name": p.name,
                    "class_id": p.class_id,
                    "class_name": cfg.class_name(p.class_id),
                    "guild": p.guild_name,
                    "is_pug": p.guild_name != our_guild,
                    "kills": 0,
                },
            )
            rec["kills"] += 1
    # сначала наши (не пуги), по числу килов
    return sorted(seen.values(), key=lambda r: (r["is_pug"], -r["kills"]))
