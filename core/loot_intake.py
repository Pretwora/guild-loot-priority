"""Этап 4: генерация issue с лутом и разбор заполненного issue в loot_log.csv.

Эргономика важнее полноты (заполняют после рейда в час ночи, раздел 4 SPEC):
рейд-лидер правит только колонки «игрок» и «тип», остальное предзаполнено.
Валидация обязательна: строка сверяется с loots[] соответствующего кила — предмет,
которого не было в дропе, это ошибка ввода, а не новая запись (раздел 4 SPEC).
"""

from __future__ import annotations

import csv
import io

AWARD_TYPES = {"bis", "offspec", "free", "shard", "de", "trade"}

TABLE_HEADER = "| игрок | тип | предмет | record_id | entry |"
TABLE_SEP = "|---|---|---|---|---|"


def generate_issue_body(date: str, size, drops: list, present: list) -> str:
    """drops: [{item, entry, record_id, boss}], present: [player_id]."""
    lines = []
    lines.append(f"## Раздача лута — {date} (состав {size})")
    lines.append("")
    lines.append("**Получатель и тип уже проставлены автоматически** (по ленте действий). "
                 "Пробегись глазами и **поправь тип** где надо, получателя — если распознан "
                 "неверно. Пусто в «игрок» → предмет незакрыт (подсветится на дашборде). "
                 "Закрой issue — бот впишет в `loot_log.csv`.")
    lines.append("")
    lines.append("**Типы:** `bis` осн. спек (мейнспек) · `offspec` запас · `free` никому не нужен · "
                 "`shard`/`de` в осколки · `trade` передан позже (дату в примечании).")
    lines.append("")
    lines.append("**Присутствовали:** " + ", ".join(f"`{p}`" for p in present))
    lines.append("")
    lines.append(TABLE_HEADER)
    lines.append(TABLE_SEP)
    for d in drops:
        player = (d.get("player") or "").strip()
        atype = (d.get("award_type") or "bis").strip()
        mark = " ✳️" if d.get("auto") else ""  # ✳️ = проставлено авто, проверь
        lines.append(f"| {player} | {atype} | {d['item']}{mark} | {d['record_id']} | {d['entry']} |")
    lines.append("")
    lines.append("<!-- loot-intake: не меняй столбцы предмет/record_id/entry. ✳️ = авто, проверь. -->")
    return "\n".join(lines) + "\n"


def parse_issue_body(text: str, loots_by_record: dict):
    """Разбирает тело issue. loots_by_record: {record_id: {entry: {name, date}}}.

    Возвращает (rows, errors). rows — dict для DictWriter loot_log.csv.
    """
    rows, errors = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        player, atype, name, record_id, entry = cells[:5]
        if player in ("игрок", "") and name in ("предмет", ""):
            continue  # заголовок/разделитель
        if record_id in ("record_id", "---") or not record_id.isdigit():
            continue
        record_id = int(record_id)
        if not entry.isdigit():
            errors.append(f"entry не число в строке: {line}")
            continue
        entry = int(entry)

        if not player:
            continue  # незакрытый — не пишем строку с получателем

        atype = (atype or "bis").lower()
        if atype not in AWARD_TYPES:
            errors.append(f"неизвестный тип выдачи '{atype}' (предмет {name})")
            continue

        rec = loots_by_record.get(record_id)
        if rec is None:
            errors.append(f"кила {record_id} нет в сырье — строка отклонена ({name})")
            continue
        if entry not in rec:
            errors.append(f"предмета {entry} ({name}) не было в дропе кила {record_id} — "
                          f"ошибка ввода, отклонено")
            continue

        rows.append({
            "date": rec[entry]["date"],
            "record_id": record_id,
            "item_entry": entry,
            "item_name": rec[entry]["name"],
            "player": player,
            "award_type": atype,
            "note": "",
        })
    return rows, errors


def rows_to_csv_append(rows: list) -> str:
    """Возвращает строки CSV (без заголовка) для дописывания в loot_log.csv."""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=["date", "record_id", "item_entry", "item_name", "player", "award_type", "note"]
    )
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()
