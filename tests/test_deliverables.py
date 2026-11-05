"""산출물 추출·조회 테스트 (2단계 ④). LLM 호출 없음.

- 저장 형식 변환(to_record): 근거 문장 검증, 고객 사례 건수 보정은 파이썬 규칙
- 조회(lookup): 미리 추출한 파일만 읽는다
"""
import json
import tempfile
import unittest
from pathlib import Path

from src.assessment.deliverables import (DELIVERABLES_PATH, Deliverable, DeliverableList, checklist_text, lookup,
                                         quote_in_text, to_record)
from src.assessment.parser import excel_files

HAS_EXCEL = len(excel_files()) >= 2
TEXT = "Landing Zone\nPartner must present for at least 2 of the customer examples:\n\n• Diagrams with the VPC’s, networking"


def extracted(quote="Diagrams with the VPC's, networking", n=None):
    return DeliverableList(deliverables=[Deliverable(name="VPC diagram", description="d", evidence_quote=quote)],
                           min_customer_examples=n)


class TestRecord(unittest.TestCase):
    def test_quote_verified_ignoring_bullets_and_quotes(self):
        self.assertTrue(quote_in_text("• Diagrams with the VPC's, networking.", TEXT))
        self.assertFalse(quote_in_text("Network diagrams for every region", TEXT))
        self.assertFalse(quote_in_text("", TEXT))

    def test_customer_examples_rules(self):
        req = {"id": "MOB-004", "text": TEXT, "scope": "customer_example"}
        self.assertEqual(to_record(req, extracted(n=2))["customer_examples_required"], 2)
        self.assertEqual(to_record(req, extracted(n=None))["customer_examples_required"], 4)  # 숫자 없으면 4건 모두
        self.assertEqual(to_record(req, extracted(n=9))["customer_examples_required"], 4)     # 범위 밖이면 4건
        company = {"id": "POV-001", "text": TEXT, "scope": "company"}
        self.assertIsNone(to_record(company, extracted(n=2))["customer_examples_required"])  # 회사 차원은 해당 없음

    def test_unverified_quote_is_flagged(self):
        rec = to_record({"id": "X-001", "text": TEXT, "scope": "company"}, extracted(quote="made up sentence"))
        self.assertFalse(rec["deliverables"][0]["verified"])

    def test_null_string_from_model(self):  # 모델이 'null' 문자열을 돌려준 경우 (DOC-001)
        self.assertIsNone(DeliverableList(deliverables=[], min_customer_examples="null").min_customer_examples)

    def test_checklist_text(self):
        self.assertIn("company-level", checklist_text(None))
        self.assertIn("each of the 4", checklist_text(4))
        self.assertIn("at least 2 of the 4", checklist_text(2))


@unittest.skipUnless(HAS_EXCEL, "실제 Assessment Excel이 없어 건너뜀 (data/private/versions/)")
class TestLookup(unittest.TestCase):
    def test_missing_file_message(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("error", lookup(["MOB-004"], path=Path(d) / "none.json"))

    def test_reads_only_stored_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "deliverables.json"
            rec = {"id": "MOB-004", "scope": "customer_example", "customer_examples_required": 2,
                   "deliverables": [{"name": "VPC diagram", "description": "d", "evidence_quote": "q", "verified": True}]}
            path.write_text(json.dumps({"by_text": {"h1": rec}, "versions": {"2026-08": {"MOB-004": "h1"}}}),
                            encoding="utf-8")
            r = lookup(["mob-004", "XYZ-999"], "2026-08", path=path)
            self.assertEqual(r["items"][0]["deliverables"], [{"name": "VPC diagram", "description": "d"}])
            self.assertEqual(r["unknown_ids"], ["XYZ-999"])

    @unittest.skipUnless(DELIVERABLES_PATH.exists(), "산출물 추출 결과가 없어 건너뜀")
    def test_real_store_covers_all_versions(self):
        store = json.loads(DELIVERABLES_PATH.read_text(encoding="utf-8"))
        for label in ("2025-08", "2026-08"):
            self.assertFalse(lookup(version=label)["unknown_ids"], label)
        self.assertTrue(all(d["verified"] for r in store["by_text"].values() for d in r["deliverables"]))


if __name__ == "__main__":
    unittest.main()
