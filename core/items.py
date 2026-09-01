"""Правила «кому нужен предмет» (раздел 8 SPEC) на полях карточки предмета.

Слота и статов в дропе нет — карточки кешируются в data/items/{entry}.json
(качает tools/fetch_items.py по одному, навсегда). Каскад детерминированный;
что не развелось однозначно — помечается ambiguous и уходит в item_overrides.yml.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from core.common import Config

# ── Протокольные enum WoW (не тюнятся, поэтому в коде, а не в weights.yml) ──

INVENTORY_TYPE_SLOT = {
    1: "head", 2: "neck", 3: "shoulder", 5: "chest", 20: "chest",
    6: "waist", 7: "legs", 8: "feet", 9: "wrist", 10: "hands",
    11: "finger", 12: "trinket",
    13: "one_hand", 21: "one_hand", 22: "one_hand", 14: "one_hand", 23: "one_hand",
    15: "ranged", 26: "ranged", 25: "ranged", 28: "ranged",
    16: "back", 17: "two_hand",
}
# Слоты, к которым применяется отсечение по типу брони (раздел 8, шаг 1).
ARMOR_GATED_SLOTS = {"head", "shoulder", "chest", "wrist", "hands", "waist", "legs", "feet"}
ARMOR_SUBCLASS = {1: "cloth", 2: "leather", 3: "mail", 4: "plate"}

# stat_type enum
STAT_AGILITY, STAT_STRENGTH, STAT_INTELLECT, STAT_SPIRIT = 3, 4, 5, 6
STAT_DEFENSE, STAT_DODGE, STAT_PARRY, STAT_BLOCK = 12, 13, 14, 15
STAT_HIT, STAT_HASTE, STAT_EXPERTISE = 31, 36, 37
STAT_ATTACK_POWER, STAT_ARMOR_PEN, STAT_SPELL_POWER, STAT_MP5 = 38, 44, 45, 43

PRIMARY_BY_STAT = {STAT_STRENGTH: "strength", STAT_AGILITY: "agility", STAT_INTELLECT: "intellect"}


@dataclass
class ItemClass:
    entry: int
    name: str
    slot: str
    is_gear: bool            # инвентарный предмет (не валюта/расходник)
    armor_type: str | None
    primary_stat: str | None
    markers: list            # вторичные маркеры: heal|tank|melee|caster
    eligible_classes: list   # class_id, кому предмет в принципе подходит
    tier_token: bool
    ambiguous: bool          # не развёлся однозначно → нужна ручная разметка
    reason: str              # одной фразой, для дашборда
    stats: dict = field(default_factory=dict)  # stat_type → value
    ilvl: int = 0            # item_level из карточки: порог «топ-шмота» для веса лута


class ItemDB:
    """Кеш карточек + справочники, выведенные из specs.yml."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        from core.common import REPO_ROOT

        self.cache_dir = os.path.join(REPO_ROOT, cfg.paths["items"], cfg.raw["realm"])
        self.overrides = _load_overrides(cfg)
        self.armor_classes = cfg.specs.get("armor_classes", {})
        self._stat_classes = self._derive_stat_classes()
        self._classified: dict[int, ItemClass] = {}

    def _derive_stat_classes(self) -> dict:
        """Из specs.yml: какие классы используют силу / ловкость / интеллект."""
        out = {"strength": set(), "agility": set(), "intellect": set()}
        for cid, info in (self.cfg.specs.get("classes") or {}).items():
            for _, sp in (info.get("specs") or {}).items():
                stat = sp.get("stat")
                if stat in out:
                    out[stat].add(cid)
        return {k: sorted(v) for k, v in out.items()}

    def card(self, entry: int) -> dict | None:
        path = os.path.join(self.cache_dir, f"{entry}.json")
        if not os.path.exists(path):
            return None
        from core.common import load_json

        raw = load_json(path)
        return raw.get("item", raw) if isinstance(raw, dict) else None

    def classify(self, entry: int, fallback_name: str = "?") -> ItemClass:
        if entry in self._classified:
            return self._classified[entry]
        ic = self._classify(entry, fallback_name)
        self._classified[entry] = ic
        return ic

    def _classify(self, entry: int, fallback_name: str) -> ItemClass:
        override = self.overrides.get(entry) or self.overrides.get(str(entry)) or {}
        card = self.card(entry)
        name = (card or {}).get("name") or override.get("name") or fallback_name

        if card is None and not override:
            return ItemClass(entry, name, "unknown", True, None, None, [], [], False,
                             True, "Карточка не в кеше — добери tools/fetch_items.py и размечай")

        stats = _extract_stats(card) if card else {}
        inv = (card or {}).get("inventory_type", 0)

        # слот
        slot = override.get("slot") or INVENTORY_TYPE_SLOT.get(inv)
        is_gear = True
        if slot is None:
            if inv == 0:
                slot, is_gear = "unknown", False  # валюта/расходник/квестовое
            else:
                slot = "unknown"

        # тип брони
        armor_type = None
        if (card or {}).get("class") == 4:
            armor_type = ARMOR_SUBCLASS.get((card or {}).get("subclass"))

        # базовый набор классов
        if override.get("classes") is not None:
            base = list(override["classes"])
        elif slot in ARMOR_GATED_SLOTS and armor_type:
            base = list(self.armor_classes.get(armor_type, []))
        else:
            base = list((self.cfg.specs.get("classes") or {}).keys())

        # первичный стат
        primary = None
        for st, label in PRIMARY_BY_STAT.items():
            if stats.get(st):
                if primary is None or stats[st] > stats.get(_stat_of(primary), 0):
                    primary = label
        if primary:
            base = [c for c in base if c in self._stat_classes.get(primary, [])] or base

        # required_class (битовая маска, если задана)
        req = (card or {}).get("required_class", -1)
        if isinstance(req, int) and req > 0:
            allowed = [cid for cid in range(1, 12) if req & (1 << (cid - 1))]
            if allowed:
                base = [c for c in base if c in allowed] or allowed

        markers = _markers(stats)
        tier_token = bool(override.get("tier_token")) or _looks_like_token(name)

        ambiguous = bool(override.get("ambiguous")) or (slot == "unknown" and is_gear) or (
            is_gear and not base
        )

        reason = _reason(slot, armor_type, primary, markers, base, self.cfg, is_gear)
        ilvl = int((card or {}).get("item_level") or 0)
        return ItemClass(entry, name, slot, is_gear, armor_type, primary, markers,
                         sorted(base), tier_token, ambiguous, reason, stats, ilvl)

    # ── Fit: соответствие предмета конкретному спеку игрока (раздел 7.5, need) ──
    def need_level(self, entry: int, class_id: int, spec_idx: int, fallback_name="?"):
        """Возвращает (need_multiplier, 'main'|'offspec'|'none', reason)."""
        ic = self.classify(entry, fallback_name)
        w = self.cfg.w("fit", "need_main"), self.cfg.w("fit", "need_offspec"), self.cfg.w("fit", "need_none")
        if not ic.is_gear:
            return w[2], "none", "не экипировка"
        if class_id not in ic.eligible_classes:
            return w[2], "none", f"{self.cfg.class_name(class_id)} не носит этот предмет"

        if self._fits_spec(ic, class_id, spec_idx):
            return w[0], "main", "подходит основному спеку"
        # другой спек того же класса?
        other = self._other_matching_spec(ic, class_id, spec_idx)
        if other is not None:
            return w[1], "offspec", f"подходит запасному спеку ({self.cfg.spec_name(class_id, other)})"
        return w[2], "none", "класс носит, но статы не под спек"

    def _fits_spec(self, ic: ItemClass, class_id: int, spec_idx: int) -> bool:
        sp = self.cfg.spec_info(class_id, spec_idx)
        if not sp:
            return False
        stat_ok = (ic.primary_stat is None) or (ic.primary_stat == sp.get("stat"))
        role = sp.get("role")
        if not stat_ok:
            return False
        # маркеры не должны противоречить роли
        if "tank" in ic.markers and role != "tank":
            return False
        if "heal" in ic.markers and role != "heal":
            return False
        if "caster" in ic.markers and role not in ("heal",) and sp.get("stat") != "intellect":
            return False
        if "melee" in ic.markers and role == "heal":
            return False
        return True

    def _other_matching_spec(self, ic: ItemClass, class_id: int, spec_idx: int):
        info = self.cfg.class_info(class_id)
        if not info:
            return None
        for other_idx in (info.get("specs") or {}):
            if other_idx == spec_idx:
                continue
            if self._fits_spec(ic, class_id, other_idx):
                return other_idx
        return None


# ── помощники ──

def _stat_of(label):
    return {"strength": STAT_STRENGTH, "agility": STAT_AGILITY, "intellect": STAT_INTELLECT}[label]


def _extract_stats(card: dict) -> dict:
    out = {}
    for i in range(1, 11):
        st = card.get(f"stat_type{i}")
        val = card.get(f"stat_value{i}")
        if st and val:
            out[st] = out.get(st, 0) + val
    return out


def _markers(stats: dict) -> list:
    m = []
    if stats.get(STAT_SPIRIT) or stats.get(STAT_MP5):
        m.append("heal")
    if any(stats.get(s) for s in (STAT_DEFENSE, STAT_DODGE, STAT_PARRY, STAT_BLOCK)):
        m.append("tank")
    if stats.get(STAT_HIT) and stats.get(STAT_EXPERTISE):
        m.append("melee")
    if stats.get(STAT_SPELL_POWER):
        m.append("caster")
    if stats.get(STAT_ARMOR_PEN):
        m.append("armorpen")
    return m


def _looks_like_token(name: str) -> bool:
    markers = ("Символ", "Знак ", "Эмблема Тир", "Трофей ")
    return any(mk in (name or "") for mk in markers)


def _reason(slot, armor_type, primary, markers, base, cfg: Config, is_gear) -> str:
    if not is_gear:
        return "не экипировка (валюта/расходник)"
    if slot == "unknown":
        return "слот не определён — нужна ручная разметка"
    parts = [slot]
    if armor_type:
        parts.append(armor_type)
    if primary:
        parts.append(primary)
    if markers:
        parts.append("/".join(markers))
    who = ", ".join(cfg.class_name(c) for c in base[:6]) if base else "никто"
    return f"{' · '.join(parts)} → {who}"


def _load_overrides(cfg: Config) -> dict:
    from core.common import load_yaml

    data = load_yaml(os.path.join(cfg.paths["manual"], "item_overrides.yml")) or {}
    ov = data.get("overrides") or {}
    return {int(k) if str(k).isdigit() else k: v for k, v in ov.items()}
