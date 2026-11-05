"""보고서 저장 테스트 (2단계 ⑤). LLM 호출 없음.

확인 기준(TASKS T17): reports/*_en.md, *_ko.md 생성, 영문본에 내부 메모 없음
"""
import json
import tempfile
import unittest
from pathlib import Path

from src.report import is_report_request, save_report, split_answer, topic_slug, with_appendix

ANSWER = """Customer example checklist [ID: MOB-004]
[내부 메모] MOB-004: 모델이 영문 부분에 잘못 넣은 메모

---

### 한국어 번역
고객 사례 체크리스트 [ID: MOB-004]
[내부 메모] MOB-004: 랜딩 존 다이어그램은 A1팀 보유"""

QUESTION = "고객 사례 4건 준비용 산출물 체크리스트를 요구사항 근거와 함께 보고서로 만들어줘"


class TestReportRules(unittest.TestCase):
    def test_detection(self):
        self.assertTrue(is_report_request(QUESTION))
        self.assertTrue(is_report_request("Make a report on new requirements"))
        self.assertFalse(is_report_request("POV-007 난이도는 어때?"))

    def test_topic_slug(self):
        self.assertEqual(topic_slug(QUESTION), "고객_사례_4건_준비용_산출물_체크리스트_요구사항_근거")
        self.assertEqual(topic_slug("프로젝트 착수 전 MOB-004 준비 보고서"), "프로젝트_착수_전_MOB-004_준비")  # 단어 안의 '로'는 그대로
        self.assertEqual(topic_slug("보고서"), "report")
        self.assertNotRegex(topic_slug('a/b\\c:*?"<>| 보고서'), r'[\\/:*?"<>|]')  # 파일명에 못 쓰는 문자 없음

    def test_split_removes_notes_from_english(self):
        en, ko = split_answer(ANSWER)
        self.assertNotIn("[내부 메모]", en)
        self.assertIn("[ID: MOB-004]", en)
        self.assertFalse(en.endswith("---"))
        self.assertIn("[내부 메모]", ko)


DL = json.dumps({"version": "2026-08", "unknown_ids": [], "items": [
    {"id": "MOB-004", "title": "Landing Zone", "scope": "customer_example", "customer_examples_required": 2,
     "checklist": "prepare for at least 2 of the 4 customer examples",
     "deliverables": [{"name": "Multi-account structure diagrams", "description": "d"}, {"name": "VPC | diagrams", "description": "d"}]},
    {"id": "PS-001", "title": "Technical Solution", "scope": "customer_example", "customer_examples_required": 4,
     "checklist": "prepare for each of the 4 customer examples", "deliverables": [{"name": "Architecture diagram", "description": "d"}]}]})


class TestAppendix(unittest.TestCase):
    def test_tables_from_tool_output(self):
        out = with_appendix(ANSWER, [("search_requirements", "<document>"), ("list_deliverables", DL)])
        en, ko = out.split("### 한국어 번역")
        self.assertIn("| MOB-004 | Landing Zone | prepare for at least 2 of the 4 customer examples |", en)
        self.assertIn("☐ VPC / diagrams", en)  # 표를 깨는 '|'는 바꾼다
        self.assertIn("| MOB-004 | Landing Zone | 고객 사례 4건 중 2건 이상 |", ko)
        self.assertIn("| PS-001 | Technical Solution | 고객 사례 4건 모두 |", ko)
        self.assertEqual(out.count("### 한국어 번역"), 1)

    def test_no_tool_output_unchanged(self):
        self.assertEqual(with_appendix(ANSWER, [("search_requirements", "x")]), ANSWER)
        self.assertEqual(with_appendix(ANSWER, [("list_deliverables", "not json")]), ANSWER)


class TestSaveReport(unittest.TestCase):
    def test_files_written(self):
        with tempfile.TemporaryDirectory() as d:
            paths = save_report(QUESTION, ANSWER, out_dir=Path(d), date="2026-11-05")
            en, ko = Path(paths["en"]), Path(paths["ko"])
            self.assertEqual(en.name, "2026-11-05_고객_사례_4건_준비용_산출물_체크리스트_요구사항_근거_en.md")
            self.assertTrue(ko.name.endswith("_ko.md"))
            self.assertNotIn("[내부 메모]", en.read_text(encoding="utf-8"))
            self.assertIn("[내부 메모]", ko.read_text(encoding="utf-8"))

    def test_same_day_same_topic_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            first = save_report(QUESTION, ANSWER, out_dir=Path(d), date="2026-11-05")
            second = save_report(QUESTION, ANSWER, out_dir=Path(d), date="2026-11-05")
            self.assertNotEqual(first["en"], second["en"])
            self.assertTrue(second["en"].endswith("_en_2.md") and second["ko"].endswith("_ko_2.md"))
            self.assertEqual(len(list(Path(d).iterdir())), 4)


if __name__ == "__main__":
    unittest.main()
