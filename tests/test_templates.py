"""산출물 양식 연결 테스트 (사용자 요청 추가). 연결은 파이썬 규칙, LLM 호출 없음."""
import base64
import tempfile
import unittest
from pathlib import Path

from src.assessment.templates import embedded, load_templates, match
from src.workforce.directory import employee_names

T = [{"id": "arch", "keywords": ["architecture diagram"], "requirement_ids": ["PS-001", "DOC-001"], "missing": False},
     {"id": "any_sop", "keywords": ["sop"], "requirement_ids": [], "missing": False},
     {"id": "gone", "keywords": ["runbook"], "requirement_ids": [], "missing": True}]


class TestMatchRules(unittest.TestCase):
    def test_keyword_and_requirement(self):
        self.assertEqual(match("PS-001", "Architecture diagram", T), "arch")
        self.assertIsNone(match("MOB-004", "Architecture diagram", T))  # 요구사항 ID가 목록에 없으면 연결 안 함

    def test_empty_requirement_ids_means_any(self):
        self.assertEqual(match("ACCT-001", "Security engagement SOPs document", T), "any_sop")

    def test_missing_file_is_skipped(self):
        self.assertIsNone(match("OPE-002", "Standardized runbook", T))

    def test_first_match_wins(self):
        both = [{"id": "a", "keywords": ["plan"], "requirement_ids": [], "missing": False},
                {"id": "b", "keywords": ["plan"], "requirement_ids": [], "missing": False}]
        self.assertEqual(match("X-001", "Project plan", both), "a")


class TestSampleTemplates(unittest.TestCase):
    def test_all_listed_files_exist(self):
        t = load_templates()
        self.assertEqual(len(t), 15)
        self.assertFalse([x["file"] for x in t if x["missing"]])

    def test_embedded_roundtrip_and_no_names(self):
        e = embedded(load_templates())
        md = base64.b64decode(e["architecture"]["b64"]).decode("utf-8")
        self.assertTrue(md.startswith("# 아키텍처 다이어그램"))
        self.assertTrue(e["raci"]["mime"].startswith("text/csv"))
        text = "".join(base64.b64decode(x["b64"]).decode("utf-8-sig") for x in e.values())
        self.assertFalse([n for n in employee_names() if n in text])  # 가상 양식에 임직원 이름 없음

    def test_missing_index_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_templates(Path(d)), [])


if __name__ == "__main__":
    unittest.main()
