"""Текстовые пояснения приоритета (этап 5 SPEC) — опционально, вне объёма первой версии.

Здесь LLM допустима, но ТОЛЬКО для формулировки словами уже посчитанных чисел
(принцип 2): она не считает и не меняет ни одного значения. Пока — детерминированный
генератор фраз без LLM, чтобы страница расшифровки работала оффлайн. Подключение
языковой модели — отдельная задача с ревью результата человеком.
"""

from __future__ import annotations


def explain_priority(candidate: dict) -> str:
    """Одна фраза, почему игрок в этой позиции по предмету (детерминированно)."""
    f = candidate["fit"]
    bits = []
    if f["need_label"] == "main":
        bits.append("основной спек")
    elif f["need_label"] == "offspec":
        bits.append("запасной спек")
    if f["slot_gap"] >= 0.99:
        bits.append("в этот слот ещё не получал")
    elif f["slot_gap"] <= 0.2:
        bits.append("недавно закрывал слот")
    if f.get("set_bonus", 1.0) > 1.0:
        bits.append("закрывает сет-бонус")
    tail = ", ".join(bits) if bits else "подходит по статам"
    return f"{candidate['display']}: приоритет {candidate['priority']} — {tail}."


def summarize_night(night: dict) -> str:
    """Короткое саммари рейд-вечера из уже посчитанных полей."""
    size = night.get("size")
    return (f"{night['date']}: состав {size}, боссов {len(night.get('bosses', []))}, "
            f"присутствовало {len(night.get('present', []))}.")
