"""HTML 대시보드 테스트 (SERVICE.md S10): 변경 건수가 정답과 같고 임직원 이름이 0건."""
import json
import re
import unittest

from src.assessment.parser import excel_files
from src.dashboard import build_data, render
from src.workforce.directory import employee_names

HAS_EXCEL = len(excel_files()) >= 2


def embedded(html: str) -> dict:
    raw = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
    return json.loads(raw.replace("<\\/", "</"))


@unittest.skipUnless(HAS_EXCEL, "실제 Assessment Excel이 없어 건너뜀 (data/private/versions/)")
class TestDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = render(build_data(), "test")
        cls.data = embedded(cls.html)

    def test_diff_counts_match_answer_table(self):
        c = self.data["versions"]["versions"]["2026-08"]["diff"]["counts"]
        self.assertEqual((c["added"], c["removed"], c["substantive"], c["minor"], c["sheet_notes_changed"]),
                         (8, 0, 2, 2, 1))

    def test_version_dropdown_data(self):
        v = self.data["versions"]
        self.assertEqual(v["labels"][:2], ["2025-08", "2026-08"])
        self.assertIsNone(v["versions"]["2025-08"]["diff"])  # 첫 버전은 비교 대상 없음

    def test_difficulty_section(self):  # 2단계 ③: 55개 모두 판정, 점수 높은 순
        df = self.data["versions"]["versions"]["2026-08"]["difficulty"]
        self.assertEqual(sum(df["counts"].values()), 55)
        self.assertEqual(df["items"][0]["level"], "상")
        self.assertNotIn("난이도 (2단계 ③)", self.data["not_implemented"])

    def test_deliverables_section(self):  # 2단계 ④: 추출 파일이 있으면 55개 항목, 없으면 '데이터 없음'
        dv = self.data["versions"]["versions"]["2026-08"]["deliverables"]
        if "error" in dv:
            self.skipTest("산출물 추출 결과 없음")
        self.assertEqual(len(dv["items"]), 55)
        mob = next(i for i in dv["items"] if i["id"] == "MOB-004")
        self.assertEqual(mob["cases"], "고객 사례 4건 중 2건 이상")

    def test_layout_tabs_filters_and_folded_eval(self):  # 탭 3개, 검색·필터, 평가 결과는 접힌 상태
        for key in ("'changes'", "'prep'", "'all'"):
            self.assertIn(key, self.html)
        self.assertIn('type: \'search\'', self.html)
        self.assertRegex(self.html, r'<details class="sec"><summary id="evalsum">')
        self.assertNotRegex(self.html, r'<details class="sec" open')

    def test_cert_targets_section(self):  # 대상 대비 실적(숫자만)
        t = self.data["certs"]["targets"]
        self.assertEqual((t["total"]["target"], t["total"]["achieved"]), (41, 27))
        self.assertEqual(t["by_person"]["people"], 28)
        self.assertEqual(t["checks"]["duplicate_rows"], 1)

    def test_no_employee_names(self):
        self.assertFalse([n for n in employee_names() if n in self.html])

    def test_self_contained(self):
        self.assertNotRegex(self.html, r'<(script|link)[^>]+(src|href)="https?://')  # 외부 자원 없음


class TestRenderEscaping(unittest.TestCase):
    def test_script_tag_in_data_is_escaped(self):
        html = render({"versions": {"labels": [], "latest": None, "versions": {}}, "certs": None, "eval": None,
                       "not_implemented": ["</script><b>x</b>"]}, "t")
        self.assertEqual(html.count("</script>"), 2)  # 데이터 안의 </script>가 태그를 끊지 않는다
        self.assertEqual(embedded(html)["not_implemented"], ["</script><b>x</b>"])


if __name__ == "__main__":
    unittest.main()
