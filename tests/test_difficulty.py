"""난이도 판정 테스트 (SERVICE.md S9): 규칙과 100% 일치.

- 규칙 단위 테스트: 가상 Requirement로 점수 규칙의 모든 조합을 확인한다(Excel 불필요).
- 실제 데이터 테스트: 2026-08 판 + data/sample/readiness.csv로 대표 항목의 정답을 확인한다.
"""
import tempfile
import unittest
from pathlib import Path

from src.assessment.difficulty import assess, level_of, score_requirement
from src.assessment.parser import excel_files
from src.assessment.readiness import (NOT_READY, PARTIAL, READY, cases_to_status, load_readiness,
                                      readiness_of)

HAS_EXCEL = len(excel_files()) >= 2


def req(rid, scope="company"):
    return {"id": rid, "title": "t", "sheet": "s", "scope": scope}


class TestReadinessRules(unittest.TestCase):
    def test_cases_conversion(self):
        self.assertEqual([cases_to_status(n) for n in range(5)], [NOT_READY, PARTIAL, PARTIAL, PARTIAL, READY])

    def test_company_status_used_as_is(self):
        table = {"A-001": {"status": "일부", "cases_met": None}}
        self.assertEqual(readiness_of(req("A-001"), table)["status"], PARTIAL)

    def test_missing_is_not_ready(self):
        self.assertEqual(readiness_of(req("A-002"), {})["status"], NOT_READY)
        self.assertEqual(readiness_of(req("C-002", "customer_example"), {})["status"], NOT_READY)

    def test_invalid_values_raise(self):
        with tempfile.TemporaryDirectory() as d:
            for body in ("A-001,완료,\n", "C-001,,5\n"):
                path = Path(d) / "r.csv"
                path.write_text("requirement_id,status,cases_met\n" + body, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_readiness(path)


class TestScoreRules(unittest.TestCase):
    def test_level_bands(self):
        self.assertEqual([level_of(s) for s in range(5)], ["low", "low", "medium", "high", "high"])

    def test_all_combinations(self):
        """준비 상태 3 × 범위 2 × 신규 여부 2 = 12개 조합 모두 규칙대로."""
        base = {READY: 0, PARTIAL: 1, NOT_READY: 2}
        for status, pts in base.items():
            for scope, extra in (("company", 0), ("customer_example", 1)):
                for is_new in (False, True):
                    r = score_requirement(req("X-001", scope), {"status": status, "basis": "b"}, is_new, "2026-08")
                    expected = pts + extra + int(is_new)
                    with self.subTest(status=status, scope=scope, new=is_new):
                        self.assertEqual(r["score"], expected)
                        self.assertEqual(r["level"], level_of(expected))
                        self.assertEqual(len(r["reasons"]), 1 + extra + int(is_new))  # 점수마다 근거 1줄


@unittest.skipUnless(HAS_EXCEL, "실제 Assessment Excel이 없어 건너뜀 (data/private/versions/)")
class TestRealData(unittest.TestCase):
    # (ID, 점수, 등급): 준비 상태 CSV 값으로 손으로 계산한 정답
    EXPECTED = [
        ("POV-007", 3, "high"),    # 미준비 +2, 신규 +1
        ("PRJ-007", 3, "high"),    # 미준비 +2, 신규 +1
        ("POV-006", 2, "medium"),  # 일부 +1, 신규 +1
        ("POV-001", 0, "low"),     # 준비완료
        ("PRJ-003", 1, "low"),     # 일부 +1
        ("MOB-004", 2, "medium"),  # 3/4건 → 일부 +1, 고객 사례 +1
        ("REL-002", 1, "low"),     # 4/4건 → 준비완료, 고객 사례 +1
        ("COST-001", 3, "high"),   # 0/4건 → 미준비 +2, 고객 사례 +1
        ("OPE-003", 3, "high"),    # 파일에 없음 → 미준비 +2, 고객 사례 +1
    ]

    def test_expected_items(self):
        result = assess([e[0] for e in self.EXPECTED])
        got = [(i["id"], i["score"], i["level"]) for i in result["items"]]
        self.assertEqual(got, self.EXPECTED)

    def test_whole_version(self):
        result = assess()
        self.assertEqual(result["version"], "2026-08")
        self.assertEqual(len(result["items"]), 55)
        self.assertEqual(sum(result["counts"].values()), 55)
        new = {i["id"] for i in result["items"] if any("new in version" in r for r in i["reasons"])}
        self.assertEqual(new, {"POV-006", "POV-007", "POV-008", "PRJ-006", "PRJ-007", "CSN-003", "ARA-001", "ARA-002"})

    def test_first_version_has_no_new_bonus(self):
        result = assess(version="2025-08")
        self.assertFalse(any("new in version" in r for i in result["items"] for r in i["reasons"]))

    def test_unknown_id(self):
        self.assertEqual(assess(["pov-007", "XYZ-999"])["unknown_ids"], ["XYZ-999"])


if __name__ == "__main__":
    unittest.main()
