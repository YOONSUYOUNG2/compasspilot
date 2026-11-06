"""2023 심사 사례 재활용 매트릭스 테스트 (SERVICE.md 3절).

- 규칙 단위 테스트: 칸 판정, 대응표 값 검사, 헤더 이름으로 사례 열 찾기(가상 행, Excel 불필요).
- 실제 파일 테스트: data/private/cases/에 제출본이 있을 때만(git 제외라 다른 환경에서는 skip).
"""
import tempfile
import unittest
from pathlib import Path

from src.assessment import cases
from src.assessment.cases import ADAPT, NEW, REUSE, _case_columns, cell, evidence_count, load_mapping, matrix

HAS_FILE = cases.case_file() is not None and cases.MAPPING_CSV.exists()


def sub(*met_lists, scope="customer_example"):
    """가상 제출본: X-001, X-002 ... 항목별 사례 4건 Met 여부."""
    return {"version": "v", "items": {f"X-00{i}": {"title": "t", "scope": scope,
                                                   "cases": [{"met": m, "evidence": 2} for m in mets]}
                                      for i, mets in enumerate(met_lists, 1)}}


class TestCellRule(unittest.TestCase):
    def test_levels(self):
        items = sub([True] * 4, [True, False, True, True])["items"]
        self.assertEqual(cell("same", ["X-001"], items, 0), {"status": REUSE, "evidence": 2})
        self.assertEqual(cell("partial", ["X-001"], items, 0)["status"], ADAPT)
        self.assertEqual(cell("none", [], items, 0), {"status": NEW, "evidence": 0})

    def test_any_not_met_means_new(self):
        items = sub([True] * 4, [True, False, True, True])["items"]
        self.assertEqual([cell("same", ["X-001", "X-002"], items, k)["status"] for k in range(4)],
                         [REUSE, NEW, REUSE, REUSE])

    def test_missing_2023_id_means_new(self):
        self.assertEqual(cell("same", ["X-009"], sub([True] * 4)["items"], 0)["status"], NEW)


class TestMappingAndMatrix(unittest.TestCase):
    def write(self, body):
        d = tempfile.mkdtemp()
        path = Path(d) / "m.csv"
        path.write_text("id_2026,level,ids_2023,basis\n" + body, encoding="utf-8")
        return path

    def test_invalid_mapping_raises(self):
        for body in ("A-001,maybe,X-001,b\n", "A-001,none,X-001,b\n", "A-001,same,,b\n"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                load_mapping(self.write(body))

    def test_matrix_counts_and_checks(self):
        mapping = load_mapping(self.write("X-001,same,X-002,b\nA-001,none,,b\n"))
        reqs = [{"id": "X-001", "title": "t", "scope": "customer_example"},
                {"id": "A-001", "title": "t", "scope": "company"}]
        r = matrix(reqs, sub([True] * 4, [True] * 4), mapping)
        self.assertEqual(r["counts"], {"same": 1, "partial": 0, "none": 1})
        self.assertEqual(r["by_case"][0], {REUSE: 1, ADAPT: 0, NEW: 1})
        self.assertEqual(r["submission"]["unused_2023"], ["X-001"])
        self.assertEqual(r["same_id_diff"], [{"id": "X-001", "ids_2023": ["X-002"]}])  # ID만 같고 다른 항목
        with self.assertRaises(ValueError):  # 대응표에 없는 2026 항목
            matrix(reqs + [{"id": "B-001", "title": "t", "scope": "company"}], sub([True] * 4), mapping)


class TestHeaderAndEvidence(unittest.TestCase):
    def test_columns_found_by_name(self):
        rows = [(1, {1: "안내문"}),
                (2, {1: "ID", 2: "Requirement Description", 5: "Customer Reference #1", 8: "Customer Reference #2"}),
                (3, {5: "Met?", 6: "Partner Response", 7: "Evidence", 8: "Met?", 9: "Partner Response", 10: "Evidence"})]
        self.assertEqual(_case_columns(rows), (1, 1, [(5, 7), (8, 10)]))

    def test_evidence_count(self):
        self.assertEqual(evidence_count("(A-001) 1 plan.pptx\n(A-001) 2 wbs.xlsx\n* 중복 사용"), 2)
        self.assertEqual(evidence_count(""), 0)


@unittest.skipUnless(HAS_FILE, "2023 심사 제출본 없음 (data/private/cases/, git 제외)")
class TestRealSubmission(unittest.TestCase):
    def test_submission_and_matrix(self):
        r = cases.build()
        s = r["submission"]
        self.assertEqual((s["items"], s["customer_items"], s["met_cells"]), (35, 22, 88))
        self.assertEqual(len(r["rows"]), 55)  # 2026-08 판 전 항목이 대응표에 있다
        self.assertEqual(sum(r["counts"].values()), 55)
        self.assertEqual(r["same_id_diff"][0]["id"], "POV-006")  # Public Content ↔ PRM
        mob = next(x for x in r["rows"] if x["id"] == "MOB-001")
        self.assertEqual(mob["ids_2023"], ["MOB-002"])  # ID로 맞추지 않는다


if __name__ == "__main__":
    unittest.main()
