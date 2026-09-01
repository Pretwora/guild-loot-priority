#!/usr/bin/env python3
"""
Этап 0 — разведка API Sirus.

Что делает:
  1. Подбирает рабочий идентификатор реалма (слаг 'x3' или числовой id).
  2. Дёргает ленту последних килов гильдии.
  3. Дёргает детали свежайшего кила.
  4. Печатает РЕАЛЬНУЮ структуру полей и складывает образцы в ./recon_out/

Запуск:
    python3 recon.py --guild 7868
    python3 recon.py --guild 7868 --realm 22        # если автоподбор не сработал

Зависимостей нет, нужен только Python 3.9+.
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

API_BASE = "https://sirus.su/api/base"
OUT_DIR = "recon_out"

# Кандидаты на идентификатор реалма. Слаг из ссылки идёт первым,
# числовые id взяты из открытых сторонних ботов:
#   9 = Scourge x2, 22 = Neverest x3, 42 = Soulseeker x1, 57 = Sirus x5
REALM_CANDIDATES = ["x3", "22", "9", "42", "57"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


def get_json(url, timeout=20):
    """GET с человеческими заголовками. Возвращает (status, data|None, error|None)."""
    req = urllib.request.Request(url, headers=HEADERS)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body), None
            except json.JSONDecodeError:
                return resp.status, None, f"не JSON, первые 200 символов: {body[:200]!r}"
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 — на разведке нас устраивает любая диагностика
        return None, None, f"{type(e).__name__}: {e}"


def describe(obj, indent=0, path="", max_depth=4, max_items=3):
    """Печатает схему JSON: какие ключи, какие типы, пример значения."""
    pad = "  " * indent
    if indent > max_depth:
        print(f"{pad}...")
        return

    if isinstance(obj, dict):
        for key, value in obj.items():
            kind = type(value).__name__
            if isinstance(value, (dict, list)):
                size = len(value)
                print(f"{pad}{key}: {kind}[{size}]")
                describe(value, indent + 1, f"{path}.{key}", max_depth, max_items)
            else:
                preview = repr(value)
                if len(preview) > 70:
                    preview = preview[:70] + "..."
                print(f"{pad}{key}: {kind} = {preview}")
    elif isinstance(obj, list):
        if not obj:
            print(f"{pad}(пусто)")
            return
        print(f"{pad}[0] из {len(obj)}:")
        describe(obj[0], indent + 1, f"{path}[0]", max_depth, max_items)


def save(name, data):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  → сохранено: {path}")


def find_records(payload):
    """Лента может лежать в 'data', в 'records' или быть голым списком."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "records", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for inner in ("records", "data", "items"):
                    if isinstance(value.get(inner), list):
                        return value[inner]
    return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--guild", required=True, help="ID гильдии, например 7868")
    parser.add_argument("--realm", help="Реалм: слаг или число. Без него — автоподбор")
    args = parser.parse_args()

    realms = [args.realm] if args.realm else REALM_CANDIDATES

    print("=" * 70)
    print("ШАГ 1. Ищем рабочий реалм и ленту килов")
    print("=" * 70)

    working_realm = None
    index_payload = None

    for realm in realms:
        url = f"{API_BASE}/{realm}/progression/pve/latest-boss-kills?guild={args.guild}&lang=ru"
        print(f"\n  пробуем realm={realm}")
        print(f"  {url}")
        status, data, err = get_json(url)
        if err:
            print(f"  ✗ {err}")
            time.sleep(1.5)
            continue

        records = find_records(data)
        print(f"  ✓ HTTP {status}, записей в ленте: {len(records)}")
        if records:
            working_realm = realm
            index_payload = data
            break
        print("  ⚠ ответ пустой — возможно, не тот реалм или у гильдии нет килов")
        time.sleep(1.5)

    if not working_realm:
        print("\n✗ Рабочий реалм не найден. Открой ссылку на гильдию в браузере,")
        print("  включи DevTools → Network → XHR и посмотри, какой URL дёргает сайт.")
        sys.exit(1)

    print(f"\n>>> РАБОЧИЙ РЕАЛМ: {working_realm}")
    save("index.json", index_payload)

    print("\n" + "=" * 70)
    print("ШАГ 2. Структура ленты килов")
    print("=" * 70)
    describe(index_payload)

    records = find_records(index_payload)
    first = records[0]
    record_id = first.get("id") or first.get("record_id")
    if not record_id:
        print("\n✗ В записи нет поля id — смотри структуру выше и подставь вручную")
        sys.exit(1)

    print("\n" + "=" * 70)
    print(f"ШАГ 3. Детали кила #{record_id}")
    print("=" * 70)

    time.sleep(1.5)
    url = f"{API_BASE}/{working_realm}/details/bossfight/{record_id}?lang=ru"
    print(f"  {url}")
    status, detail, err = get_json(url)
    if err:
        print(f"  ✗ {err}")
        sys.exit(1)
    print(f"  ✓ HTTP {status}")
    save(f"bossfight_{record_id}.json", detail)

    body = detail.get("data", detail) if isinstance(detail, dict) else detail
    describe(body)

    print("\n" + "=" * 70)
    print("ШАГ 4. Что нас интересует в первую очередь")
    print("=" * 70)

    players = body.get("players") if isinstance(body, dict) else None
    if isinstance(players, list) and players:
        print(f"\nИгроков в киле: {len(players)}")
        print("Поля одного игрока:")
        describe(players[0], indent=1)
    else:
        print("\n⚠ players не найден — приоритет считать не из чего, смотри структуру выше")

    loots = body.get("loots") if isinstance(body, dict) else None
    if isinstance(loots, list):
        print(f"\nПредметов в дропе: {len(loots)}")
        if loots:
            print("Поля одного предмета:")
            describe(loots[0], indent=1)
            print("\n!!! Проверь главное: есть ли где-то поле с ПОЛУЧАТЕЛЕМ")
            print("    (owner, character, player, winner). Если есть — ручной ввод не нужен.")
    else:
        print("\n⚠ loots не найден")

    print("\n" + "=" * 70)
    print("Готово. Пришли содержимое папки recon_out/ — зафиксируем схему.")
    print("=" * 70)


if __name__ == "__main__":
    main()
