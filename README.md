# Дашборд приоритета лута — гильдия 7868 (Sirus x3)

Публичный статический дашборд для консула (loot council). Отвечает на два вопроса:
**кто заслужил** и **кому эта вещь**. Система — советник, а не судья: готовит и обосновывает
решение, принимает его совет.

Полное ТЗ — [SPEC.md](SPEC.md). Реальная схема API — [docs/api-schema.md](docs/api-schema.md).
Расхождения с ТЗ, СТОП-развилки и открытые вопросы — **[docs/decisions.md](docs/decisions.md)** (читать первым).
Оформление — [docs/design.md](docs/design.md).

## Принципы (нельзя нарушать)

- Сырьё неизменяемо; всё производное пересчитывается с нуля при каждом прогоне.
- LLM не считает числа — весь скоринг детерминированный Python.
- Все веса — в `config/weights.yml`, в коде ни одного магического числа из формул.
- Сбор отделён от пересчёта: поломка формул не останавливает накопление истории.
- Каждое число на дашборде объяснимо одной фразой.

## Как это устроено

```
collector/collect.py     качает килы и складывает сырьё как есть (только stdlib)
tools/fetch_items.py     добирает карточки упавших предметов в кеш
tools/collect_actions.py снимки ленты «Последние действия» (получатели лута)
tools/collect_combatlog.py выжимки логов боя (эффективность: урон/смерти/утилити)
tools/make_loot_issue.py, tools/apply_loot_issue.py   issue раздачи лута (остаток ручного ввода)
tools/recon.py           разведка схемы API (этап 0)
core/
  common.py              загрузчики конфигов, справочники, математика
  normalize.py           сырьё → килы → рейд-вечера → участие (падать может только он)
  items.py               каскад «кому нужен предмет» (раздел 8) по статам карточки
  combat.py              метрики из лога боя: полученный урон, смерти, перебивания/диспелы
  scoring.py             формулы A / P / L / S / Fit / кандидаты (раздел 7)
  loot_attrib.py         автоатрибуция лута по ленте действий (obtaineditem × дроп кила)
  build_dashboard.py     сборка dashboard.json — единственного контракта с фронтом
  loot_intake.py         генерация/разбор issue раздачи лута (остаток ручного ввода)
  narrate.py             текстовые пояснения (этап 5, заглушка)
config/                  config.json, weights.yml, specs.yml
data/raw/                неизменяемое сырьё (килы, лента)
data/items/              кеш карточек предметов (навсегда)
data/manual/             ручной ввод: roster, attendance, loot_log, overrides, adjustments
web/                     Vite + React, читает один dashboard.json
tests/                   тесты формул (unittest)
```

Воркфлоу: `collect.yml` (сбор по расписанию), `build.yml` (пересчёт + сборка + деплой Pages),
`loot-intake.yml` (разбор issue с лутом).

## Запуск локально

```bash
pip install -r requirements.txt

# сбор килов (уважает 1.5с между запросами; на macOS сертификаты подтянет certifi)
python3 collector/collect.py --config config/config.json
python3 tools/fetch_items.py --config config/config.json      # карточки предметов
python3 tools/collect_actions.py --config config/config.json  # получатели лута (автоатрибуция)
python3 tools/collect_combatlog.py --config config/config.json # выжимки логов боя (эффективность)

# пересчёт → data/dist/dashboard.json
python3 -m core.build_dashboard --config config/config.json

# тесты формул
python3 -m unittest discover -s tests

# фронт
cd web && npm install
cp ../data/dist/dashboard.json public/dashboard.json
npm run dev            # или npm run build
```

Разовый добор истории (20 недель через пагинацию API):
`python3 collector/collect.py --config config/config.json --backfill` (перезапускать до «к докачке: 0»).

## Развёртывание

Репозиторий и Pages публичные, секретов нет.

1. `git init` (проект ещё не под git), запушить в публичный репозиторий.
2. `Settings → Actions → General → Workflow permissions` → **Read and write**.
3. `Settings → Pages → Source: GitHub Actions`.
4. Запустить `collect` вручную (Actions → collect → Run), затем `build`.

## Статус по этапам

| Этап | Статус |
|---|---|
| 0 — разведка API | ✅ схема подтверждена вживую, зафиксирована |
| 1 — коллектор | ✅ работает, идемпотентен, +certifi/+backfill |
| 2 — нормализация, посещаемость | ✅ + командо-зависимый знаменатель (два состава) |
| 3 — перформанс | ✅ перцентили внутри спека; **из лога боя**: танки по полученному урону, утилити (перебивания/диспелы), смерти, расходники — под потолком 30% |
| 4 — предметы, лут-борд, ввод | ✅ каскад, лут-борд, **автоатрибуция лута из API** (лента действий); ручной ввод — только остаток |
| 5 — пояснения LLM | заглушка, вне объёма первой версии |

Открытые вопросы к заказчику — в [docs/decisions.md](docs/decisions.md).
