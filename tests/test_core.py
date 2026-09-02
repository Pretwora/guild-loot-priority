"""Тесты ядра: формулы разделов 7–8 фиксируются числами.

Запуск:  python3 -m unittest tests.test_core   (из корня репозитория)
Без внешних зависимостей (unittest из stdlib).
"""

import datetime as dt
import unittest

from core.common import Config, clip, decay_weight, median, parse_server_time
from core import scoring as SC
from core.items import ItemDB
from core.normalize import Kill, PlayerLine, RaidNight, Roster, build_nights, size_bucket


def kill(rid, when, players, size=10, boss=(532, 1)):
    return Kill(
        record_id=rid, killed_at=when, map_id=boss[0], map_name="m", boss_name=f"b{boss[1]}",
        encounter_id=boss[1], difficulty=0, player_count=size, size_bucket=size, players=players,
    )


def line(name, cls=3, spec=1, role="dps", dps=1000, hps=0, guid=0):
    return PlayerLine(name=name, guid=guid, class_id=cls, spec=spec, role=role, dps=dps, hps=hps,
                      ilvl=250, guild_name="NoName", itemset=[])


class StubCombat:
    """Мини-combat для тестов: {record_id: {guid: metrics}}."""
    def __init__(self, data, consumable_active=False):
        self.data = data
        self.consumable_active = consumable_active

    def has(self, rid):
        return rid in self.data

    def metrics(self, rid, guid):
        return self.data.get(rid, {}).get(guid)


class TestCommon(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(parse_server_time("2026-08-31 23:50:30"),
                         dt.datetime(2026, 8, 31, 23, 50, 30))
        self.assertIsNone(parse_server_time("мусор"))

    def test_median(self):
        self.assertEqual(median([1, 2, 3]), 2)
        self.assertEqual(median([1, 2, 3, 4]), 2.5)
        self.assertIsNone(median([]))

    def test_clip_decay(self):
        self.assertEqual(clip(5, 0, 2), 2)
        self.assertEqual(clip(-1, 0, 2), 0)
        self.assertAlmostEqual(decay_weight(0.98, 0), 1.0)
        self.assertAlmostEqual(decay_weight(0.5, 2), 0.25)


class TestNights(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_size_bucket(self):
        self.assertEqual(size_bucket(10, self.cfg), 10)
        self.assertEqual(size_bucket(9, self.cfg), 10)
        self.assertEqual(size_bucket(24, self.cfg), 25)
        self.assertIsNone(size_bucket(3, self.cfg))

    def test_gap_splits_nights(self):
        base = dt.datetime(2026, 8, 30, 20, 0, 0)
        kills = [
            kill(1, base, [line("A")]),
            kill(2, base + dt.timedelta(minutes=30), [line("A")]),
            kill(3, base + dt.timedelta(hours=5), [line("A")]),  # >3ч разрыв → новый вечер
        ]
        nights = build_nights(kills, self.cfg)
        self.assertEqual(len(nights), 2)
        self.assertEqual(nights[0].kill_count, 2)
        self.assertEqual(nights[1].kill_count, 1)

    def test_presence_share(self):
        base = dt.datetime(2026, 8, 30, 20, 0, 0)
        kills = [
            kill(1, base, [line("A"), line("B")]),
            kill(2, base + dt.timedelta(minutes=20), [line("A")]),  # B пропустил
        ]
        night = build_nights(kills, self.cfg)[0]
        self.assertEqual(night.presence["A"], 1.0)
        self.assertEqual(night.presence["B"], 0.5)


class TestPerformance(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.roster = Roster(char_to_player={f"P{i}": f"p{i}" for i in range(6)},
                             players={f"p{i}": {"characters": [{"name": f"P{i}"}]} for i in range(6)})

    def test_small_sample_neutral(self):
        base = dt.datetime(2026, 8, 30, 20, 0, 0)
        kills = [kill(1, base, [line("P0", dps=1000), line("P1", dps=2000)])]
        perf = SC.performance_scores(kills, self.roster, self.cfg)
        # <5 записей в пуле → нейтрально 0.5
        self.assertEqual(perf["p0"]["P"], 0.5)
        self.assertEqual(perf["p1"]["P"], 0.5)

    def test_tank_not_measured(self):
        base = dt.datetime(2026, 8, 30, 20, 0, 0)
        players = [line(f"P{i}", role="dps", dps=1000 * (i + 1)) for i in range(5)]
        players.append(line("P5", role="tank", dps=50))
        perf = SC.performance_scores([kill(1, base, players)], self.roster, self.cfg)
        self.assertFalse(perf["p5"]["measured"])  # танк не меряется
        self.assertIsNone(perf["p5"]["P"])
        self.assertTrue(perf["p0"]["measured"])   # ДД меряется

    def test_percentile_orders(self):
        base = dt.datetime(2026, 8, 30, 20, 0, 0)
        # 6 записей одного спека/босса → пул >=5, перцентили осмысленны
        players = [line(f"P{i}", dps=1000 * (i + 1)) for i in range(6)]
        perf = SC.performance_scores([kill(1, base, players)], self.roster, self.cfg)
        self.assertEqual(perf["p0"]["P"], 0.0)   # худший
        self.assertEqual(perf["p5"]["P"], 1.0)   # лучший
        self.assertTrue(0 < perf["p3"]["P"] < 1)


class TestAttendance(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.roster = Roster(char_to_player={"P": "p"},
                             players={"p": {"characters": [{"name": "P"}]}})

    def test_before_join_excluded(self):
        d1 = dt.datetime(2026, 8, 4, 20, 0, 0)   # до вступления игрока
        d2 = dt.datetime(2026, 8, 13, 20, 0, 0)
        d3 = dt.datetime(2026, 8, 20, 20, 0, 0)
        kills = [
            kill(1, d1, [line("X", guid=9)], size=25),   # P нет (ещё не в гильдии)
            kill(2, d2, [line("P", guid=1)], size=25),   # пришёл
            kill(3, d3, [line("P", guid=1)], size=25),
        ]
        nights = build_nights(kills, self.cfg)
        att = SC.attendance_scores(nights, self.roster, self.cfg,
                                   dt.datetime(2026, 8, 21), first_seen={"p": d2})
        states = {x["date"]: x["state"] for x in att["p"]["detail"]}
        self.assertEqual(states["2026-08-04"], "before_join")  # не пропуск — его не было
        self.assertEqual(states["2026-08-13"], "full")
        self.assertEqual(att["p"]["A"], 1.0)  # пришёл на все рейды ПОСЛЕ вступления

    def test_no_eligible_is_no_data(self):
        # все рейды до вступления → зачётных ноль → «нет данных», НЕ медиана
        dates = [dt.datetime(2026, 8, d, 20, 0, 0) for d in (4, 13, 20)]
        kills = [kill(i + 1, d, [line("X", guid=9)], size=25) for i, d in enumerate(dates)]
        nights = build_nights(kills, self.cfg)
        att = SC.attendance_scores(nights, self.roster, self.cfg,
                                   dt.datetime(2026, 8, 25), first_seen={"p": dt.datetime(2026, 8, 30)})
        self.assertTrue(att["p"]["no_raid_data"])
        self.assertEqual(att["p"]["A_eff"], 0.0)  # не медиана
        self.assertIsNone(att["p"]["A"])


class TestCombatPerformance(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.roster = Roster(char_to_player={f"T{i}": f"t{i}" for i in range(6)},
                             players={f"t{i}": {"characters": [{"name": f"T{i}"}]} for i in range(6)})

    def _cm(self, taken_ps=0, deaths=0, utility=0, has_consumable=None):
        return {"taken_ps": taken_ps, "deaths": deaths, "utility": utility,
                "taken": 0, "done": 0, "healing": 0, "interrupts": 0, "dispels": utility,
                "has_consumable": has_consumable}

    def test_tank_not_measured(self):
        base = dt.datetime(2026, 8, 30, 20, 0, 0)
        players = [line(f"T{i}", role="tank", guid=i) for i in range(6)]
        combat = StubCombat({1: {i: self._cm(taken_ps=1000 * (i + 1)) for i in range(6)}})
        perf = SC.performance_scores([kill(1, base, players)], self.roster, self.cfg, combat)
        # танк не меряется — перформанс к нему не применяется
        self.assertFalse(perf["t0"]["measured"])
        self.assertIsNone(perf["t0"]["P"])

    def test_death_penalty_lowers_p(self):
        base = dt.datetime(2026, 8, 30, 20, 0, 0)
        players = [line(f"T{i}", dps=1000 * (i + 1), guid=i) for i in range(6)]
        no_death = StubCombat({1: {i: self._cm() for i in range(6)}})
        with_death = StubCombat({1: {i: self._cm(deaths=1) for i in range(6)}})
        p0 = SC.performance_scores([kill(1, base, players)], self.roster, self.cfg, no_death)
        p1 = SC.performance_scores([kill(1, base, players)], self.roster, self.cfg, with_death)
        self.assertGreater(p0["t3"]["P"], p1["t3"]["P"])  # смерть роняет перформанс

    def test_dps_measured(self):
        base = dt.datetime(2026, 8, 30, 20, 0, 0)
        players = [line(f"T{i}", role="dps", dps=1000 * (i + 1), guid=i) for i in range(6)]
        perf = SC.performance_scores([kill(1, base, players)], self.roster, self.cfg, combat=None)
        self.assertTrue(perf["t0"]["measured"])  # ДД меряется
        self.assertIsNotNone(perf["t0"]["P"])


class TestLootAndScore(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.db = ItemDB(self.cfg)
        self.roster = Roster(char_to_player={}, players={
            "a": {"rank": "member", "characters": []},
            "b": {"rank": "trial", "characters": []},
        })

    def test_award_type_shard_skipped(self):
        now = dt.datetime(2026, 9, 1)
        log = [
            {"date": "2026-09-01", "record_id": "1", "item_entry": "139519",
             "item_name": "шлем", "player": "a", "award_type": "bis", "note": ""},
            {"date": "2026-09-01", "record_id": "1", "item_entry": "139519",
             "item_name": "шлем", "player": "a", "award_type": "shard", "note": ""},
        ]
        loot = SC.loot_scores(log, self.roster, self.db, self.cfg, now)
        # shard не учитывается — только одна запись формирует L
        self.assertEqual(len(loot["a"]["awards"]), 1)
        self.assertGreater(loot["a"]["L"], 0)

    def test_final_formula_exact(self):
        # S = 100 * (0.7*A_eff + 0.3*P) / (1 + 0.35*L_norm) * gate
        att = {"a": {"A_eff": 1.0}, "b": {"A_eff": 1.0}}
        perf = {"a": {"P": 0.5}, "b": {"P": 0.5}}
        loot = {"a": {"L_norm": 0.0}, "b": {"L_norm": 0.0}}
        final = SC.final_scores(att, perf, loot, self.roster, self.cfg, dt.datetime(2026, 9, 1))
        base = 0.7 * 1.0 + 0.3 * 0.5  # 0.85
        self.assertAlmostEqual(final["a"]["S"], 100 * base / 1.0 * 1.0, places=2)
        self.assertAlmostEqual(final["b"]["S"], 100 * base / 1.0 * 0.6, places=2)  # триал gate 0.6

    def test_unmeasured_role_folds_perf_into_attendance(self):
        # танк/хил: перформанс не применяется, его вес уходит в посещаемость
        att = {"a": {"A_eff": 1.0}}
        perf = {"a": {"P": None, "measured": False}}
        r = Roster(char_to_player={}, players={"a": {"rank": "member", "characters": []}})
        final = SC.final_scores(att, perf, {"a": {"L_norm": 0.0}}, r, self.cfg, dt.datetime(2026, 9, 1))
        self.assertAlmostEqual(final["a"]["S"], 100.0, places=1)  # A_eff=1 → максимум без перформанса

    def test_loot_does_not_affect_score(self):
        # Решение РЛ: полученный лут НЕ влияет на рейтинг (loot_penalty_k=0) — показываем
        # выдачи иконками для наглядности, приоритет считаем только по посещаемости+перформансу.
        att = {"a": {"A_eff": 1.0}}
        perf = {"a": {"P": 0.5}}
        r = Roster(char_to_player={}, players={"a": {"rank": "member", "characters": []}})
        s0 = SC.final_scores(att, perf, {"a": {"L_norm": 0.0}}, r, self.cfg, dt.datetime(2026, 9, 1))
        s1 = SC.final_scores(att, perf, {"a": {"L_norm": 2.0}}, r, self.cfg, dt.datetime(2026, 9, 1))
        self.assertEqual(s0["a"]["S"], s1["a"]["S"])  # лут не меняет рейтинг


class TestItems(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.db = ItemDB(self.cfg)

    def test_plate_gated_to_plate_classes(self):
        ic = self.db.classify(139519)  # латный шлем, сила, танк-маркеры
        self.assertEqual(ic.slot, "head")
        self.assertEqual(ic.armor_type, "plate")
        self.assertTrue(set(ic.eligible_classes).issubset({1, 2, 6}))  # воин/пал/рыцарь

    def test_cloth_int_excludes_plate(self):
        ic = self.db.classify(139547)  # тканевые плечи, интеллект
        self.assertEqual(ic.armor_type, "cloth")
        self.assertNotIn(1, ic.eligible_classes)  # воин ткань не носит

    def test_need_none_for_wrong_class(self):
        mult, label, _ = self.db.need_level(139519, class_id=8, spec_idx=0)  # маг на латы
        self.assertEqual(label, "none")
        self.assertEqual(mult, self.cfg.w("fit", "need_none"))


class TestLootAttrib(unittest.TestCase):
    def test_manual_overrides_auto(self):
        from core.loot_attrib import merge_with_manual

        manual = [{"record_id": 1, "item_entry": 100, "player": "a", "award_type": "bis"}]
        auto = [
            {"record_id": 1, "item_entry": 100, "player": "b", "award_type": "bis", "_source": "auto"},
            {"record_id": 1, "item_entry": 200, "player": "c", "award_type": "bis", "_source": "auto"},
        ]
        merged = merge_with_manual(manual, auto)
        # ручная запись по (1,100) перекрывает авто; авто по (1,200) добавляется
        keys = {(r["record_id"], r["item_entry"], r["player"]) for r in merged}
        self.assertIn((1, 100, "a"), keys)
        self.assertNotIn((1, 100, "b"), keys)
        self.assertIn((1, 200, "c"), keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
