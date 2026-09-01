"""Общие загрузчики, справочники и математические помощники ядра.

Ядро зависит только от стандартной библиотеки и pyyaml (pandas сознательно не берём:
объём данных крошечный, агрегации простые, а каждое число обязано оставаться
аудируемым — векторизация pandas это скорее прячет).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import yaml

# ─────────────────────────────────────────────────────────────────────────────
# Загрузка конфигов
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _abs(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)


def load_json(path: str):
    with open(_abs(path), encoding="utf-8") as f:
        return json.load(f)


def load_yaml(path: str):
    full = _abs(path)
    if not os.path.exists(full):
        return None
    with open(full, encoding="utf-8") as f:
        return yaml.safe_load(f)


class Config:
    """Собирает config.json, weights.yml и specs.yml в один объект."""

    def __init__(self, config_path="config/config.json"):
        self.raw = load_json(config_path)
        self.weights = load_yaml("config/weights.yml")
        self.specs = load_yaml("config/specs.yml")
        self.paths = self.raw["paths"]

    # --- удобные доступы ---
    def w(self, *keys):
        """Достаёт вложенную константу из weights.yml, падая с внятной ошибкой."""
        node = self.weights
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                raise KeyError(f"weights.yml: нет ключа {'/'.join(keys)}")
            node = node[k]
        return node

    # --- справочник классов/спеков ---
    def class_info(self, class_id):
        return (self.specs.get("classes") or {}).get(class_id)

    def class_name(self, class_id):
        info = self.class_info(class_id)
        return info["name"] if info else f"class{class_id}"

    def class_color(self, class_id):
        info = self.class_info(class_id)
        return info["color"] if info else "808080"

    def class_armor(self, class_id):
        info = self.class_info(class_id)
        return info["armor"] if info else "unknown"

    def spec_info(self, class_id, spec_idx):
        info = self.class_info(class_id)
        if not info:
            return None
        return (info.get("specs") or {}).get(spec_idx)

    def spec_name(self, class_id, spec_idx):
        s = self.spec_info(class_id, spec_idx)
        return s["name"] if s else f"spec{spec_idx}"

    def role_from_api(self, role_int):
        return (self.specs.get("role_map") or {}).get(role_int, "dps")


# ─────────────────────────────────────────────────────────────────────────────
# Время: серверное локальное, наивное
# ─────────────────────────────────────────────────────────────────────────────

SERVER_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def parse_server_time(s: str) -> datetime | None:
    """'2026-08-31 23:50:30' → наивный datetime в серверном локальном времени."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), SERVER_TIME_FMT)
    except ValueError:
        return None


def server_now(offset_hours: int) -> datetime:
    """Текущее серверное локальное время (UTC + смещение), наивное."""
    return datetime.utcnow() + timedelta(hours=offset_hours)


def days_between(later: datetime, earlier: datetime) -> float:
    """Сколько дней прошло (может быть дробным, не отрицательным)."""
    delta = (later - earlier).total_seconds() / 86400.0
    return max(0.0, delta)


# ─────────────────────────────────────────────────────────────────────────────
# Математика
# ─────────────────────────────────────────────────────────────────────────────


def clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def median(values):
    """Медиана списка. Пустой список → None."""
    xs = sorted(v for v in values if v is not None)
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    if n % 2 == 1:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2.0


def decay_weight(lam: float, days_ago: float) -> float:
    """λ^days_ago — экспоненциальный распад по возрасту."""
    return lam ** days_ago
