"""RAG 문서 변환·출력 형식 테스트 (Bedrock 호출 없음).

검색 정확도(S3)는 Bedrock 임베딩이 필요해서 `python -m src.rag.search`와 평가(run_eval)로 확인한다.
"""
import unittest

from src.rag.index import to_document
from src.rag.search import format_results

REQ = {"id": "POV-001", "title": "Customer Presentation", "text": "Customer Presentation\nBody.",
       "sheet": "Common Practice Requirements", "scope": "company", "area": "Overview",
       "version": "2026-08", "internal_note": "증빙 요건 변경"}


class TestRagFormat(unittest.TestCase):
    def test_internal_note_not_in_chunk(self):
        doc = to_document(REQ)
        self.assertNotIn("증빙", doc.page_content)
        self.assertNotIn("internal_note", doc.metadata)

    def test_metadata(self):
        md = to_document(REQ).metadata
        self.assertEqual((md["id"], md["version"], md["sheet"]), ("POV-001", "2026-08", "Common Practice Requirements"))

    def test_format_has_source_and_document_tag(self):
        out = format_results([{"id": "POV-001", "version": "2026-08", "sheet": "S", "area": "", "content": "x"}])
        self.assertIn("[ID: POV-001]", out)
        self.assertTrue(out.startswith("<document") and out.endswith("</document>"))

    def test_empty(self):
        self.assertEqual(format_results([]), "No matching requirement found.")


if __name__ == "__main__":
    unittest.main()
