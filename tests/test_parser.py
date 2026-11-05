"""Assessment 파서 테스트.

- 가상 xlsx 테스트: 실제 파일 없이 '헤더 이름으로 컬럼 찾기'와 메모 분리를 검증한다.
- 실제 Excel 테스트: 파일이 있을 때만 실행한다(skipUnless).
"""
import tempfile
import unittest
import zipfile
from pathlib import Path

from src import config
from src.assessment.parser import HANGUL, build_all, excel_files, parse_assessment

HAS_EXCEL = len(excel_files()) >= 2


def _cell(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(rows: dict[int, dict[str, str]]) -> str:
    body = "".join(
        f'<row r="{r}">' + "".join(_cell(f"{col}{r}", v) for col, v in cells.items()) + "</row>"
        for r, cells in rows.items())
    return ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{body}</sheetData></worksheet>")


def make_xlsx(path: Path, sheets: dict[str, dict[int, dict[str, str]]]) -> None:
    """테스트용 최소 xlsx를 만든다(인라인 문자열만 사용)."""
    names = list(sheets)
    wb = ('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1))
          + "</sheets></workbook>")
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" '
                      'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
                      for i in range(1, len(names) + 1))
            + "</Relationships>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        for i, n in enumerate(names, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheets[n]))


class TestParserSynthetic(unittest.TestCase):
    """가상 파일: 컬럼이 밀려 있어도 헤더 이름으로 찾는지 확인한다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = Path(cls.tmp.name) / "sample.xlsx"
        make_xlsx(path, {
            "Introduction": {1: {"A": "Checklist\nValidity Period: August 2026-February 2027 \nmore"}},
            "Common Practice Requirements": {
                1: {"A": "Common AWS Partner Practice Requirements \nguide"},
                2: {"A": "ID", "B": "Requirement Description", "C": "Met?", "D": "Partner Response", "E": "비고"},
                3: {"A": "Practice Overview"},
                5: {"A": "POV-001", "B": "Customer Presentation\nBody text.", "C": "Yes", "E": "증빙 요건 변경"},
                6: {"A": "POV-002", "B": "Maintaining Expertise\nBody.", "D": "Partner wrote English answer"},
            },
            "Common Cust Example Reqs": {
                1: {"A": "Common Customer Example Requirements \nAll four examples"},
                # NEW 4번째 시트처럼 헤더 없는 C열이 끼어 응답 컬럼이 한 칸 밀린 경우
                2: {"A": "ID", "B": "Requirement Description", "D": "Customer Reference #1"},
                3: {"D": "Met?", "E": "Partner Response"},
                4: {"A": "Partner Solution"},
                5: {"A": "Validate domain expertise."},
                7: {"A": "PS-001", "B": "Technical Solution\nBody.", "C": "region 근거 필요", "D": "Yes"},
                8: {"A": "Not an id row"},
                9: {"A": "PS-002", "B": "Solution Optimality\nBody."},
            },
        })
        cls.data = parse_assessment(path)
        cls.by_id = {r["id"]: r for r in cls.data["requirements"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_version(self):
        self.assertEqual(self.data["version"]["label"], "2026-08")

    def test_ids_and_titles(self):
        self.assertEqual(list(self.by_id), ["POV-001", "POV-002", "PS-001", "PS-002"])
        self.assertEqual(self.by_id["POV-001"]["title"], "Customer Presentation")
        self.assertEqual(self.by_id["POV-001"]["scope"], "company")
        self.assertEqual(self.by_id["PS-001"]["scope"], "customer_example")

    def test_internal_note_split(self):
        self.assertEqual(self.by_id["POV-001"]["internal_note"], "증빙 요건 변경")
        self.assertEqual(self.by_id["PS-001"]["internal_note"], "region 근거 필요")  # 헤더 없는 칸
        self.assertIsNone(self.by_id["POV-002"]["internal_note"])  # 영문 응답은 메모가 아님

    def test_area(self):
        self.assertEqual(self.by_id["PS-001"]["area"], "Partner Solution")
        self.assertEqual(self.by_id["PS-001"]["area_description"], "Validate domain expertise.")
        self.assertEqual(self.by_id["PS-002"]["area"], "Not an id row")  # 떨어진 비-ID 행은 새 영역

    def test_sheet_notes(self):
        self.assertIn("All four examples", self.data["sheet_notes"]["Common Cust Example Reqs"])


class TestVersionRegistry(unittest.TestCase):
    """버전 등록: 같은 버전의 파일이 두 개면 오류로 알린다."""

    def test_duplicate_version_rejected(self):
        sheet = {1: {"A": "Validity Period: August 2026-February 2027"}}
        req = {"Common Practice Requirements": {
            1: {"A": "guide"}, 2: {"A": "ID", "B": "Requirement Description"},
            3: {"A": "POV-001", "B": "Title\nBody"}}}
        with tempfile.TemporaryDirectory() as d:
            for name in ("a.xlsx", "b.xlsx"):
                make_xlsx(Path(d) / name, {"Introduction": sheet, **req})
            with self.assertRaises(ValueError):
                build_all(Path(d))


@unittest.skipUnless(HAS_EXCEL, "실제 Assessment Excel이 없어 건너뜀 (data/private/versions/)")
class TestParserRealFiles(unittest.TestCase):
    """실제 OLD·NEW 파일: SERVICE.md에 적힌 개수와 버전이 맞는지 확인한다."""

    @classmethod
    def setUpClass(cls):
        parsed = {d["version"]["label"]: d for d in map(parse_assessment, excel_files())}
        cls.labels = sorted(parsed)
        cls.old = parsed["2025-08"]
        cls.new = parsed["2026-08"]

    def _count(self, data, sheet):
        return sum(1 for r in data["requirements"] if r["sheet"] == sheet)

    def test_counts(self):
        self.assertEqual(len(self.old["requirements"]), 47)
        self.assertEqual(len(self.new["requirements"]), 55)
        self.assertEqual(self._count(self.new, "Common Practice Requirements"), 20)
        self.assertEqual(self._count(self.new, "Migration and Modernization Req"), 13)
        self.assertEqual(self._count(self.new, "Common Cust Example Reqs"), 22)

    def test_unique_ids(self):
        for data in (self.old, self.new):
            ids = [r["id"] for r in data["requirements"]]
            self.assertEqual(len(ids), len(set(ids)))

    def test_versions(self):
        self.assertEqual(self.labels[:2], ["2025-08", "2026-08"])  # 파일명이 아니라 Validity Period로 구분
        self.assertEqual(self.old["version"]["label"], "2025-08")
        self.assertEqual(self.new["version"]["label"], "2026-08")
        self.assertEqual(self.new["version"]["validity_period"], "August 2026 - February 2027")

    def test_internal_notes(self):
        noted = {r["id"] for r in self.new["requirements"] if r["internal_note"]}
        expected = {"POV-001", "POV-006", "POV-007", "POV-008", "PRJ-006", "PRJ-007",
                    "CSN-003", "ARA-001", "ARA-002", "PS-001"}
        self.assertEqual(noted, expected)
        self.assertFalse(any(r["internal_note"] for r in self.old["requirements"]))

    def test_no_korean_in_aws_text(self):
        # 메모가 분리되었으면 AWS 원문(제목·본문)에는 한글이 없어야 한다
        for r in self.new["requirements"]:
            self.assertIsNone(HANGUL.search(r["text"]), r["id"])

    def test_sheet_notes_and_areas(self):
        self.assertEqual(len(self.new["sheet_notes"]), 3)
        ucr = next(r for r in self.new["requirements"] if r["id"] == "UCR-001")
        self.assertEqual(ucr["area"], "Use Case Relevance")
        self.assertEqual(ucr["title"], "About the Customer")


if __name__ == "__main__":
    unittest.main()
