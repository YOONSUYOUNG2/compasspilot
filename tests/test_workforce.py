"""권한·소속별 명단 조회 테스트 (SERVICE.md S7). 가상 데이터 기준, Bedrock 호출 없음."""
import json
import unittest

from src import config
from src.workforce.certifications import (count, count_certifications, details,
                                          get_certification_details, load_certifications)

ALL = load_certifications()


def names(rows):
    return {r["name"] for r in rows}


def expected(pred):
    return names(r for r in ALL if pred(r))


class TestScopes(unittest.TestCase):
    """역할별 명단 범위가 정답(데이터에서 직접 거른 결과)과 100% 일치하는지."""

    def check(self, user_id, pred, **kw):
        r = details(user_id, **kw)
        self.assertIsInstance(r, dict, r)
        self.assertEqual(names(r["holders"]), expected(pred))
        self.assertEqual(r["count"], sum(1 for x in ALL if pred(x)))

    def test_hr_company_wide(self):
        self.check("hr01", lambda r: True)

    def test_division_head(self):
        self.check("divA", lambda r: r["division"] == "A사업부")
        self.check("divB", lambda r: r["division"] == "B사업부")

    def test_team_leader(self):
        self.check("tlA1", lambda r: r["team"] == "A1팀")

    def test_group_leader(self):
        self.check("glA11", lambda r: r["group"] == "A1-1그룹")

    def test_narrowing_inside_scope(self):
        self.check("divA", lambda r: r["team"] == "A1팀" and r["vendor"] == "AWS", team="A1팀", vendor="AWS")
        self.check("hr01", lambda r: r["division"] == "B사업부", division="B사업부")


class TestRefusals(unittest.TestCase):
    """범위 밖 요청과 일반 권한은 고정 거절 문구."""

    def refused(self, user_id, **kw):
        self.assertEqual(details(user_id, **kw), config.PERMISSION_REFUSAL)

    def test_staff_and_unknown(self):
        self.refused("staff01")
        self.refused("nobody")       # 미등록 사용자 = staff
        self.refused(None)

    def test_other_division(self):     # 평가 25번
        self.refused("divA", division="B사업부")

    def test_other_team(self):         # 평가 26번
        self.refused("tlA1", team="A2팀")
        self.refused("tlA1", group="A2-1그룹")   # 다른 팀의 그룹만 지정해도 거절
        self.refused("tlA1", division="A사업부")  # 팀장이 사업부 전체 요청

    def test_other_group(self):        # 평가 27번
        self.refused("glA11", group="A1-2그룹")
        self.refused("glA11", team="A1팀")       # 그룹장이 팀 전체 요청

    def test_other_than_mine(self):
        # 이름 없이 "다른 ○○"을 물은 경우: 사용자 소속이 그 계층에서 정해져 있으면 범위 밖
        self.refused("glA11", other_than_mine="group")     # 평가 27번
        self.refused("tlA1", other_than_mine="team")       # 평가 26번
        self.refused("divA", other_than_mine="division")
        # 팀장의 '다른 그룹'은 같은 팀 안이라 범위 안 → 명단 반환
        self.assertIsInstance(details("tlA1", other_than_mine="group"), dict)
        self.assertIsInstance(details("hr01", other_than_mine="division"), dict)

    def test_unknown_org(self):
        self.assertIn("error", details("hr01", division="Z사업부"))


class TestTools(unittest.TestCase):
    """도구는 사용자를 config에서만 읽는다(인자로 권한을 바꿀 수 없다)."""

    def test_user_from_config(self):
        out = get_certification_details.invoke({}, config={"configurable": {"user_id": "glA11"}})
        data = json.loads(out)
        self.assertEqual(names(data["holders"]), expected(lambda r: r["group"] == "A1-1그룹"))

    def test_no_config_is_staff(self):
        self.assertEqual(get_certification_details.invoke({}), config.PERMISSION_REFUSAL)

    def test_user_id_not_an_argument(self):
        # LLM이 볼 수 있는 인자 목록에 사용자·권한 관련 항목이 없어야 한다
        params = set(get_certification_details.args)
        self.assertFalse({"user_id", "role", "config"} & params, params)

    def test_count_has_no_names(self):
        out = count_certifications.invoke({"vendor": "AWS"})
        self.assertFalse(any(n in out for n in expected(lambda r: True)))
        self.assertEqual(count("AWS")["total_certifications"], sum(r["vendor"] == "AWS" for r in ALL))


if __name__ == "__main__":
    unittest.main()
