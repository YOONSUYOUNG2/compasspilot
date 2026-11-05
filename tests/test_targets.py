"""자격 취득 대상 대비 실적 집계 테스트 (사내 취합 양식 구조 반영). Bedrock 호출 없음."""
import unittest

from src.workforce.directory import employee_names
from src.workforce.targets import target_status

EMP = [{"employee_id": "E1", "division": "A", "team": "A1", "group": "A1-1"},
       {"employee_id": "E2", "division": "A", "team": "A1", "group": "A1-2"},
       {"employee_id": "E3", "division": "B", "team": "B1", "group": "B1-1"}]
CERTS = [{"employee_id": "E1", "vendor": "AWS"}, {"employee_id": "E1", "vendor": "AWS"},  # 같은 벤더 2건 = 취득 1
         {"employee_id": "E2", "vendor": "OpenAI"}, {"employee_id": "E3", "vendor": "Google Cloud"}]
TARGETS = [{"employee_id": "E1", "vendor": "AWS"}, {"employee_id": "E1", "vendor": "Google Cloud"},
           {"employee_id": "E2", "vendor": "AWS"}, {"employee_id": "E3", "vendor": "Google Cloud"},
           {"employee_id": "E3", "vendor": "Google Cloud"},  # 중복 행
           {"employee_id": "E9", "vendor": "AWS"}]           # 조직도에 없는 사번


class TestTargetRules(unittest.TestCase):
    def setUp(self):
        self.s = target_status(TARGETS, CERTS, EMP)

    def test_by_vendor(self):
        self.assertEqual(self.s["by_vendor"]["AWS"], {"target": 2, "achieved": 1, "not_achieved": 1, "rate": 0.5})
        self.assertEqual(self.s["by_vendor"]["Google Cloud"], {"target": 2, "achieved": 1, "not_achieved": 1, "rate": 0.5})
        self.assertEqual(self.s["total"]["target"], 4)

    def test_by_person(self):  # E1 일부(AWS만), E2 미취득, E3 전부
        self.assertEqual(self.s["by_person"], {"people": 3, "all": 1, "partial": 1, "none": 1, "multi_vendor": 1})

    def test_checks(self):  # 오류 행은 집계에서 빠지고 점검 건수로만 보인다
        self.assertEqual(self.s["checks"], {"unknown_employee_ids": 1, "duplicate_rows": 1, "holders_not_target": 1})

    def test_by_org_levels(self):
        self.assertEqual([r["org"] for r in self.s["by_division"]], [["A"], ["B"]])
        a = self.s["by_division"][0]
        self.assertEqual((a["people"], a["target"], a["achieved"]), (2, 3, 1))
        self.assertEqual(len(self.s["by_group"]), 3)


class TestSampleData(unittest.TestCase):
    """data/sample 가상 데이터: 손으로 센 정답과 일치"""

    def test_sample_numbers(self):
        s = target_status()
        self.assertEqual({v: (x["target"], x["achieved"]) for v, x in s["by_vendor"].items()},
                         {"AWS": (28, 23), "Google Cloud": (8, 4), "OpenAI": (5, 0)})
        self.assertEqual(s["by_person"], {"people": 28, "all": 20, "partial": 3, "none": 5, "multi_vendor": 11})
        self.assertEqual(s["checks"], {"unknown_employee_ids": 1, "duplicate_rows": 1, "holders_not_target": 1})

    def test_no_names_in_result(self):
        text = str(target_status())
        self.assertFalse([n for n in employee_names() if n in text])


if __name__ == "__main__":
    unittest.main()
