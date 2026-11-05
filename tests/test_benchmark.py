"""파트너 등급 현주소 비교 테스트 (대시보드 '현주소' 시트). 순위·격차·전망은 파이썬 규칙."""
import tempfile
import unittest
from pathlib import Path

from src.benchmark import load, rank_of, status

CRIT = [{"tier": "Select", "level": 1, "competencies": 0, "certified_people": 4, "launches": 1},
        {"tier": "Advanced", "level": 2, "competencies": 1, "certified_people": 20, "launches": 4},
        {"tier": "Premier", "level": 3, "competencies": 5, "certified_people": 300, "launches": 20}]


def co(name, tier, comp, cert, launch, us=False, prog=""):
    level = {"Select": 1, "Advanced": 2, "Premier": 3}[tier]
    return {"company": name, "is_us": us, "tier": tier, "level": level, "competencies": comp,
            "certified_people": cert, "launches": launch, "in_progress": prog}


class TestRules(unittest.TestCase):
    def test_tier_beats_metrics(self):  # 등급이 먼저: Premier가 Competency 수가 적어도 앞선다
        cs = [co("우리", "Advanced", 9, 900, 90, True), co("X", "Premier", 5, 300, 20)]
        self.assertEqual(status(cs, CRIT)["overall_rank"], 2)

    def test_ties_share_rank(self):
        cs = [co("우리", "Advanced", 4, 200, 10, True), co("X", "Advanced", 4, 200, 30), co("Y", "Premier", 6, 400, 30)]
        s = status(cs, CRIT)
        self.assertEqual((s["overall_rank"], s["tied"]), (2, True))
        self.assertEqual([r["rank"] for r in s["table"]], [1, 2, 2])

    def test_gaps(self):
        cs = [co("우리", "Advanced", 4, 260, 22, True), co("X", "Premier", 9, 820, 64), co("Y", "Premier", 5, 450, 37)]
        m = {x["metric"]: x for x in status(cs, CRIT)["metrics"]}
        self.assertEqual((m["competencies"]["gap_to_leader"], m["competencies"]["gap_to_next"]), (5, 1))
        self.assertEqual((m["certified_people"]["gap_to_leader"], m["certified_people"]["gap_to_next"]), (560, 190))

    def test_next_tier_and_top_tier(self):
        nt = status([co("우리", "Advanced", 4, 260, 22, True)], CRIT)["next_tier"]
        self.assertEqual(nt["tier"], "Premier")
        self.assertEqual([(c["metric"], c["gap"], c["met"]) for c in nt["conditions"]],
                         [("competencies", 1, False), ("certified_people", 40, False), ("launches", 0, True)])
        self.assertIsNone(status([co("우리", "Premier", 9, 900, 90, True)], CRIT)["next_tier"])  # 최고 등급

    def test_projection(self):
        cs = [co("우리", "Advanced", 4, 260, 22, True, "M&M"), co("C", "Premier", 5, 450, 37), co("D", "Advanced", 4, 230, 18)]
        p = status(cs, CRIT)["projection"]
        self.assertEqual((p["competencies"], p["competency_rank"], p["competency_tied"]), (5, 1, True))
        self.assertEqual([c["metric"] for c in p["tier_up"]["remaining"]], ["certified_people"])
        self.assertEqual((p["tier_up"]["tier"], p["tier_up"]["same_tier"]), ("Premier", ["C"]))

    def test_no_projection_without_in_progress(self):
        self.assertIsNone(status([co("우리", "Advanced", 4, 260, 22, True)], CRIT)["projection"])

    def test_rank_of_excludes_self(self):
        a = co("A", "Advanced", 1, 1, 1)
        self.assertEqual(rank_of(a, [a], lambda c: c["level"]), 1)


class TestSampleData(unittest.TestCase):
    def test_sample(self):  # 가상 데이터: 6개 사 중 4위, M&M 취득 시 Competency 공동 3위, 남은 조건은 자격 40명
        s = status()
        self.assertEqual((s["companies"], s["overall_rank"], s["us"]["tier"]), (6, 4, "Advanced"))
        p = s["projection"]
        self.assertEqual((p["competency_rank"], p["competency_tied"]), (3, True))
        self.assertEqual([(c["metric"], c["gap"]) for c in p["tier_up"]["remaining"]], [("certified_people", 40)])

    def test_anonymous_names_only(self):  # 실명 대신 익명 표기
        companies, _ = load()
        self.assertEqual(sorted(c["company"] for c in companies if not c["is_us"]), ["A사", "B사", "C사", "D사", "E사"])

    def test_invalid_files(self):
        with tempfile.TemporaryDirectory() as d:
            b, c = Path(d) / "b.csv", Path(d) / "c.csv"
            c.write_text("tier,level,competencies,certified_people,launches\nAdvanced,2,1,20,4\n", encoding="utf-8")
            b.write_text("company,is_us,aws_tier,competencies,certified_people,launches,in_progress\nX,1,Gold,1,1,1,\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load(b, c)  # 기준에 없는 등급
            b.write_text("company,is_us,aws_tier,competencies,certified_people,launches,in_progress\nX,0,Advanced,1,1,1,\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load(b, c)  # 우리 회사 없음


if __name__ == "__main__":
    unittest.main()
