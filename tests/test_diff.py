"""버전 비교 테스트.

- 판정 규칙 테스트: 파일 없이 classify()의 4단계 규칙을 검증한다.
- 정답표 테스트(S2): 실제 Excel이 있을 때 SERVICE.md 5.1 정답과 100% 일치하는지 검증한다.
"""
import unittest

from src.assessment import diff
from src.assessment.parser import excel_files

HAS_EXCEL = len(excel_files()) >= 2


class TestClassify(unittest.TestCase):
    def test_unchanged(self):
        self.assertEqual(diff.classify("Same text.", "Same text."), diff.UNCHANGED)

    def test_notation_case_and_punctuation(self):
        self.assertEqual(diff.classify("Provide the plan.", "provide the Plan"), diff.MINOR_NOTATION)
        self.assertEqual(diff.classify("A  plan,\nnow", "A plan now"), diff.MINOR_NOTATION)

    def test_typo(self):
        self.assertEqual(diff.classify("Recommend Recoverty Time", "Recommend Recovery Time"), diff.MINOR_TYPO)

    def test_word_added_is_substantive(self):
        self.assertEqual(diff.classify("Explain the design", "Explain the design and region"), diff.SUBSTANTIVE)

    def test_different_word_is_substantive(self):
        # 철자가 전혀 다른 단어로 바뀌면 의미가 바뀐 것으로 본다
        self.assertEqual(diff.classify("oral presentation", "written presentation"), diff.SUBSTANTIVE)

    def test_compare_structure(self):
        old = {"version": {"label": "v1"}, "sheet_notes": {"S": "guide"},
               "requirements": [{"id": "A-001", "title": "t", "sheet": "S", "text": "Keep."},
                                {"id": "A-002", "title": "t", "sheet": "S", "text": "Gone."}]}
        new = {"version": {"label": "v2"}, "sheet_notes": {"S": "guide changed a lot"},
               "requirements": [{"id": "A-001", "title": "t", "sheet": "S", "text": "keep"},
                                {"id": "A-003", "title": "t", "sheet": "S", "text": "New."}]}
        r = diff.compare(old, new)
        self.assertEqual([a["id"] for a in r["added"]], ["A-003"])
        self.assertEqual([x["id"] for x in r["removed"]], ["A-002"])
        self.assertEqual(r["changed"][0]["change_type"], diff.MINOR_NOTATION)
        self.assertEqual(r["sheet_notes_changed"][0]["change_type"], diff.SUBSTANTIVE)


@unittest.skipUnless(HAS_EXCEL, "실제 Assessment Excel이 없어 건너뜀 (data/private/versions/)")
class TestAnswerTable(unittest.TestCase):
    """SERVICE.md 5.1 버전 비교 정답 (2025-08 → 2026-08)."""

    @classmethod
    def setUpClass(cls):
        cls.r = diff.diff_versions("2025-08", "2026-08")
        cls.by_type = {}
        for c in cls.r["changed"]:
            cls.by_type.setdefault(c["change_type"], set()).add(c["id"])

    def test_default_is_previous_vs_latest(self):
        default = diff.diff_versions()
        self.assertEqual((default["from_version"], default["to_version"]), ("2025-08", "2026-08"))

    def test_totals(self):
        self.assertEqual(self.r["counts"]["old_total"], 47)
        self.assertEqual(self.r["counts"]["new_total"], 55)

    def test_added(self):
        self.assertEqual({a["id"] for a in self.r["added"]},
                         {"POV-006", "POV-007", "POV-008", "PRJ-006", "PRJ-007", "CSN-003", "ARA-001", "ARA-002"})

    def test_removed(self):
        self.assertEqual(self.r["removed"], [])

    def test_substantive(self):
        self.assertEqual(self.by_type.get(diff.SUBSTANTIVE), {"POV-001", "PS-001"})

    def test_minor(self):
        self.assertEqual(self.by_type.get(diff.MINOR_NOTATION), {"PS-004"})
        self.assertEqual(self.by_type.get(diff.MINOR_TYPO), {"REL-002"})

    def test_sheet_note(self):
        notes = self.r["sheet_notes_changed"]
        self.assertEqual([n["sheet"] for n in notes], ["Common Cust Example Reqs"])
        self.assertEqual(notes[0]["change_type"], diff.SUBSTANTIVE)

    def test_internal_note_attached(self):
        pov001 = next(c for c in self.r["changed"] if c["id"] == "POV-001")
        self.assertIn("15", pov001["internal_note"])


if __name__ == "__main__":
    unittest.main()
