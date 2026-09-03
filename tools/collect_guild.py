#!/usr/bin/env python3
"""Снимок серверного ростера гильдии: GET /api/base/{realm}/guild/{id}.

Зачем: в парсах у игрока нет ДАТЫ ВСТУПЛЕНИЯ — first_seen сейчас берётся по первому
появлению в логах 25-к, из-за чего основатели (Bloodycat) для ранних рейдов помечаются
«до вступления». Серверный ростер может отдавать реальную дату вступления — забираем её.

Что делает: качает эндпоинт гильдии, кладёт сырьё в data/raw/guild/{realm}/{id}.json,
печатает структуру members (ключи + пример) и подсвечивает поля, похожие на дату вступления,
с примером по каждому члену. По найденному полю строит data/manual/guild_joined.auto.yml
(имя_персонажа: дата) — его читает нормализатор как источник joined.

Запуск (нужна сеть до sirus.su):  python3 tools/collect_guild.py --config config/config.json
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.common import Config, REPO_ROOT

API_BASE = "https://sirus.su/api/base"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}
DATE_HINTS = ("join", "since", "created", "enter", "member_since", "date", "added", "time")


def make_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def get_json(url, timeout=25):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=make_ssl_context()) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _find_members(obj, path=""):
    """Ищет список членов гильдии где угодно в ответе → (path, list)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("members", "roster", "characters") and isinstance(v, list) and v \
                    and isinstance(v[0], dict):
                return path + "." + k, v
        for k, v in obj.items():
            r = _find_members(v, path + "." + k)
            if r:
                return r
    if isinstance(obj, list) and obj and isinstance(obj[0], dict) \
            and any(key in obj[0] for key in ("name", "character", "player")):
        return path or "(root)", obj
    return None


def _member_name(m):
    for k in ("name", "character_name", "characterName"):
        if isinstance(m.get(k), str):
            return m[k]
    for k in ("character", "player"):
        v = m.get(k)
        if isinstance(v, dict) and isinstance(v.get("name"), str):
            return v["name"]
        if isinstance(v, str):
            return v
    return None


def _date_fields(m):
    """Поля члена, чьё имя намекает на дату (для подсветки)."""
    out = {}
    for k, v in m.items():
        if any(h in k.lower() for h in DATE_HINTS) and isinstance(v, (str, int, float)):
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    args = ap.parse_args()
    cfg = Config(os.path.join(REPO_ROOT, args.config))
    realm, gid = cfg.raw["realm"], cfg.raw["guild_id"]

    url = f"{API_BASE}/{realm}/guild/{gid}?lang=ru"
    print(f"GET {url}")
    try:
        data = get_json(url)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} — эндпоинт недоступен/сменился."); return 1
    except Exception as e:  # noqa: BLE001
        print(f"Сеть недоступна: {type(e).__name__}: {e}"); return 1

    raw_dir = os.path.join(REPO_ROOT, cfg.paths["raw"], "guild", realm)
    os.makedirs(raw_dir, exist_ok=True)
    raw_path = os.path.join(raw_dir, f"{gid}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"сырьё → {os.path.relpath(raw_path, REPO_ROOT)} ({len(json.dumps(data))} байт)")
    print("верхние ключи:", list(data.keys()) if isinstance(data, dict) else type(data).__name__)

    found = _find_members(data)
    if not found:
        print("⚠ список members не найден — структура иная, см. сырьё."); return 0
    path, members = found
    print(f"members по пути {path}: {len(members)} чел")
    m0 = members[0]
    print("ключи члена:", list(m0.keys()))
    print("пример члена:", json.dumps(m0, ensure_ascii=False)[:500])

    # какие поля вообще похожи на дату — по всем членам (объединение)
    date_keys = set()
    for m in members:
        date_keys |= set(_date_fields(m).keys())
    print("\nполя-кандидаты на дату вступления:", sorted(date_keys) or "— НЕТ (API не отдаёт дату)")
    if date_keys:
        # покажем по 5 членов с их дата-полями, включая Bloodycat
        print("примеры (имя → дата-поля):")
        shown = 0
        for m in members:
            nm = _member_name(m)
            df = _date_fields(m)
            if nm and (shown < 6 or (nm or "").lower() == "bloodycat"):
                print(f"   {nm}: {df}")
                shown += 1
        # если поле однозначно одно — сгенерим авто-yml (имя: дата)
        best = sorted(date_keys, key=lambda k: (0 if "join" in k else 1, k))[0]
        pairs = {}
        for m in members:
            nm, df = _member_name(m), _date_fields(m)
            if nm and best in df:
                pairs[nm] = df[best]
        if pairs:
            out = os.path.join(raw_dir, "joined.yml")  # в data/raw → коммитится сборщиком
            with open(out, "w", encoding="utf-8") as f:
                f.write(f"# Автоснимок дат вступления из API (поле '{best}'). Имя персонажа → дата.\n")
                f.write("# Не редактировать руками — перезаписывается tools/collect_guild.py.\n")
                f.write("# Явный joined в roster.yml перекрывает это (ручной приоритет).\n")
                for nm in sorted(pairs):
                    f.write(f'"{nm}": "{pairs[nm]}"\n')
            print(f"\n→ {os.path.relpath(out, REPO_ROOT)}: {len(pairs)} дат по полю '{best}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
