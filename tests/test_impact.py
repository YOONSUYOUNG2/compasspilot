"""변경 영향 분석 테스트 (SERVICE.md 3절 기준표).

- 규칙 단위 테스트: 변경 종류 × 준비 상태 모든 조합(Excel 불필요).
- 가상 비교 결과로 analyze 전체 흐름(삭제 항목은 이전 버전 Requirement로 판정).
- 실제 데이터 테스트: 2025-08 → 2026-08 + data/sample/readiness.csv 정답.
"""
import unittest

from src.assessment import diff
from src.assessment.impact import (RETIRE, REWORK, START, WORDING, analyze, categorize, impact)
from src.assessment.parser import excel_files
from src.assessment.readiness import NOT_READY, PARTIAL, READY

HAS_EXCEL = len(excel_files()) >= 2


class TestCategorize(unittest.TestCase):
    def test_all_combinations(self):
        expected = {
            "added": (START, START, START),
            "removed": (RETIRE, RETIRE, None),
            diff.SUBSTANTIVE: (REWORK, REWORK, START),
            diff.MINOR_NOTATION: (WORDING, WORDING, WORDING),
            diff.MINOR_TYPO: (WORDING, WORDING, WORDING),
            diff.UNCHANGED: (None, None, None),
        }
        for change, cats in expected.items():
            for status, cat in zip((READY, PARTIAL, NOT_READY), cats):
                with self.subTest(change=change, status=status):
                    self.assertEqual(categorize(change, status), cat)


def req(rid, scope="company"):
    return {"id": rid, "title": "t " + rid, "sheet": "s", "scope": scope}


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.old = [req("A-001"), req("A-002"), req("A-003"), req("D-001"), req("D-002")]
        self.new = [req("A-001"), req("A-002"), req("A-003"), req("N-001", "customer_example")]
        chg = lambda rid, kind: {"id": rid, "change_type": kind, "changes": [], "old_text": "o", "new_text": "n"}
        self.diff = {"from_version": "2025-08", "to_version": "2026-08",
                     "counts": {"unchanged": 7},
                     "added": [{"id": "N-001"}], "removed": [{"id": "D-001"}, {"id": "D-002"}],
                     "changed": [chg("A-001", diff.SUBSTANTIVE), chg("A-002", diff.SUBSTANTIVE),
                                 chg("A-003", diff.MINOR_TYPO)],
                     "sheet_notes_changed": [{"sheet": "s", "change_type": diff.SUBSTANTIVE}]}
        self.table = {"A-001": {"status": "준비완료", "cases_met": None},
                      "D-001": {"status": "일부", "cases_met": None}}  # A-002·D-002는 파일에 없음 → 미준비

    def test_flow(self):
        r = analyze(self.diff, self.old, self.new, self.table)
        got = {i["id"]: i["category"] for i in r["items"]}
        self.assertEqual(got, {"A-001": REWORK, "A-002": START, "A-003": WORDING, "N-001": START, "D-001": RETIRE})
        self.assertEqual(r["counts"], {REWORK: 1, START: 2, WORDING: 1, RETIRE: 1, "unchanged": 7, "sheet_notes": 1})
        self.assertEqual([i["category"] for i in r["items"]], [REWORK, START, START, WORDING, RETIRE])  # 구분 순서로 정렬
        rework = r["items"][0]
        self.assertEqual((rework["old_text"], rework["new_text"]), ("o", "n"))  # 원문 비교용


@unittest.skipUnless(HAS_EXCEL, "실제 Assessment Excel 없음")
class TestRealData(unittest.TestCase):
    def test_answer(self):
        r = impact()
        self.assertEqual((r["from_version"], r["to_version"]), ("2025-08", "2026-08"))
        by = lambda c: sorted(i["id"] for i in r["items"] if i["category"] == c)
        self.assertEqual(by(REWORK), ["POV-001", "PS-001"])
        self.assertEqual(by(WORDING), ["PS-004", "REL-002"])
        self.assertEqual(by(START), ["ARA-001", "ARA-002", "CSN-003", "POV-006", "POV-007", "POV-008",
                                     "PRJ-006", "PRJ-007"])
        self.assertEqual(r["counts"][RETIRE], 0)
        self.assertEqual(r["counts"]["sheet_notes"], 1)


if __name__ == "__main__":
    unittest.main()
