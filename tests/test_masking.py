"""이름 마스킹 테스트 (SERVICE.md S8): staff 답변·trace에 임직원 이름 0건."""
import json
import tempfile
import unittest
from pathlib import Path

from src.guards.masking import mask_name, mask_text
from src.tracer import FileTracer
from src.workforce.certifications import details
from src.workforce.directory import employee_names

NAMES = employee_names()


class TestMasking(unittest.TestCase):
    def test_mask_name(self):
        self.assertEqual(mask_name("김하늘"), "김*늘")
        self.assertEqual(mask_name("남궁하늘"), "남**늘")
        self.assertEqual(mask_name("이준"), "이*")

    def test_all_directory_names_masked(self):
        text = ", ".join(NAMES)
        masked = mask_text(text)
        self.assertFalse([n for n in NAMES if n in masked])

    def test_roster_text_masked(self):
        # 인사팀 명단(이름 포함)을 마스킹하면 이름이 하나도 남지 않아야 한다
        roster = json.dumps(details("hr01"), ensure_ascii=False)
        self.assertTrue(any(n in roster for n in NAMES))
        self.assertFalse(any(n in mask_text(roster) for n in NAMES))

    def test_non_names_untouched(self):
        self.assertEqual(mask_text("AWS Solutions Architect POV-001"), "AWS Solutions Architect POV-001")

    def test_trace_has_no_names(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trace.jsonl"
            t = FileTracer(path=path, user_id="hr01", mask=mask_text)
            t.question(f"{NAMES[0]} 자격 알려줘")
            t.answer(json.dumps(details("hr01"), ensure_ascii=False), 0.1)
            raw = path.read_text(encoding="utf-8")
        self.assertFalse([n for n in NAMES if n in raw])


if __name__ == "__main__":
    unittest.main()
