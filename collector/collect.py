#!/usr/bin/env python3
"""
Этап 1 — коллектор.

Единственная задача: забрать данные с API и положить на диск КАК ЕСТЬ.
Никакой интерпретации, никакой нормализации. Схема API может измениться,
формулы приоритета точно будут меняться — а сырьё должно пережить и то, и другое.

Раскладка:
    data/raw/index/{realm}/2026-09-01T20-30Z.json   снимок ленты (каждый запуск)
    data/raw/bossfight/{realm}/4821553.json          детали кила (качается один раз)

Файлы деталей неизменяемы: если файл есть — запрос не делается.
Так мы и щадим их API, и получаем воспроизводимость.

Запуск:
    python3 collect.py --config config.json
"""

import argparse
import json
import os
import random
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://sirus.su/api/base"


def make_ssl_context():
    """Дефолтный контекст плюс запасной путь через certifi.

    На части macOS системный Python не находит корневые сертификаты и любой
    HTTPS падает с CERTIFICATE_VERIFY_FAILED. В GitHub Actions такого нет.
    Если установлен certifi — используем его CA-бандл; иначе обычный контекст.
    Проверку сертификата НЕ отключаем.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — certifi просто может быть не установлен
        return ssl.create_default_context()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

DEFAULTS = {
    "realm": "x3",
    "guild_id": "7868",
    "data_dir": "data/raw",
    "min_interval_sec": 1.5,   # пауза между запросами
    "max_retries": 4,
    "max_details_per_run": 40,  # предохранитель на первом прогоне
}


def log(msg):
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


class Client:
    """HTTP-клиент с паузами между запросами и экспоненциальным бэкоффом."""

    def __init__(self, min_interval, max_retries):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_call = 0.0
        self._ctx = make_ssl_context()

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()

    def get_json(self, url):
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(url, headers=HEADERS)
            try:
                with urllib.request.urlopen(req, timeout=25, context=self._ctx) as resp:
                    return json.loads(resp.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as e:
                retryable = e.code == 429 or e.code >= 500
                log(f"  HTTP {e.code} на попытке {attempt}")
                if not retryable or attempt == self.max_retries:
                    return None
            except Exception as e:  # noqa: BLE001
                log(f"  {type(e).__name__}: {e} (попытка {attempt})")
                if attempt == self.max_retries:
                    return None

            backoff = min(60, 2 ** attempt) + random.uniform(0, 2)
            log(f"  повтор через {backoff:.1f}с")
            time.sleep(backoff)
        return None


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


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


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--realm", help="переопределить реалм из конфига")
    parser.add_argument("--guild-id", help="переопределить гильдию из конфига")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "разовый добор истории: пройти все страницы ленты (?page=N), а не только "
            "текущую неделю. Плановый прогон это НЕ использует. Резюмируемо: докачка "
            "деталей ограничена max_details_per_run, перезапускай до 'к докачке: 0'."
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=25,
        help="предохранитель на бэкофилл: сколько страниц ленты максимум пройти",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    realm = args.realm or cfg["realm"]
    guild_id = args.guild_id or cfg["guild_id"]
    data_dir = cfg["data_dir"]

    client = Client(cfg["min_interval_sec"], cfg["max_retries"])

    log(f"Реалм {realm}, гильдия {guild_id}" + (" [BACKFILL]" if args.backfill else ""))

    # --- 1. Снимок(и) ленты килов ---
    base_url = (
        f"{API_BASE}/{realm}/progression/pve/latest-boss-kills?guild={guild_id}&lang=ru"
    )

    def fetch_page(page):
        url = base_url if page == 1 else f"{base_url}&page={page}"
        return client.get_json(url)

    payload = fetch_page(1)
    if payload is None:
        log("✗ Лента недоступна, выходим без изменений")
        sys.exit(1)

    records = list(find_records(payload))
    log(f"В ленте (стр. 1) записей: {len(records)}")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%MZ")
    index_path = os.path.join(data_dir, "index", realm, f"{stamp}.json")
    write_json(index_path, payload)
    log(f"Снимок ленты: {index_path}")

    if args.backfill:
        last_page = 1
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if isinstance(meta, dict) and isinstance(meta.get("last_page"), int):
            last_page = min(meta["last_page"], args.max_pages)
        log(f"Бэкофилл: страниц к обходу ~{last_page}")
        for page in range(2, last_page + 1):
            extra = fetch_page(page)
            if extra is None:
                log(f"  страница {page} недоступна — прерываем добор")
                break
            page_records = find_records(extra)
            if not page_records:
                log(f"  страница {page} пустая — конец истории")
                break
            page_path = os.path.join(
                data_dir, "index", realm, f"{stamp}-p{page:02d}.json"
            )
            write_json(page_path, extra)
            records.extend(page_records)
            log(f"  страница {page}: +{len(page_records)} записей")

    log(f"Всего записей к рассмотрению: {len(records)}")
    if not records:
        log("Лента пустая — сохранять нечего")
        return

    # --- 2. Детали каждого нового кила ---
    detail_dir = os.path.join(data_dir, "bossfight", realm)
    os.makedirs(detail_dir, exist_ok=True)

    pending = []
    for rec in records:
        record_id = rec.get("id") or rec.get("record_id")
        if record_id is None:
            continue
        target = os.path.join(detail_dir, f"{record_id}.json")
        if not os.path.exists(target):
            pending.append((record_id, target))

    log(f"Новых килов к докачке: {len(pending)}")

    limit = cfg["max_details_per_run"]
    if len(pending) > limit:
        log(f"Ограничиваем прогон до {limit}, остальное доберётся в следующий запуск")
        pending = pending[:limit]

    saved = 0
    for record_id, target in pending:
        url = f"{API_BASE}/{realm}/details/bossfight/{record_id}?lang=ru"
        detail = client.get_json(url)
        if detail is None:
            log(f"  ✗ кил {record_id} не забрался, попробуем в следующий раз")
            continue
        write_json(target, detail)
        saved += 1
        log(f"  ✓ {record_id}")

    log(f"Готово. Сохранено новых килов: {saved}")


if __name__ == "__main__":
    main()
