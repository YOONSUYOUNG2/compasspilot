"""답변 후처리 규칙 테스트 (Bedrock 호출 없음).

- 근거 없는 [내부 메모] 줄 제거
- Supervisor 최종 답 검증(repair_reason): 라운드 3·4에서 발견한 세 가지 어긋남
"""
import unittest
import warnings

from langchain_core.messages import AIMessage, HumanMessage

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from src import config
    from src.main import last_agent_report, repair_reason, strip_unsupported_notes

ANSWER = "English answer [ID: POV-007]\n\n### 한국어 번역\n번역\n[내부 메모] POV-007: 메모"
ROSTER = '{"viewer_role": "인사팀", "count": 2, "holders": []}'


class TestStripNotes(unittest.TestCase):
    def test_removed_without_note_tool(self):
        out = strip_unsupported_notes(ANSWER, ["transfer_to_assessment_agent", "search_requirements"])
        self.assertNotIn("[내부 메모]", out)
        self.assertIn("[ID: POV-007]", out)

    def test_kept_with_diff_versions(self):
        self.assertEqual(strip_unsupported_notes(ANSWER, ["diff_versions"]), ANSWER)


class TestRepairReason(unittest.TestCase):
    def test_refusal_but_tool_gave_roster(self):  # 라운드 4 #23, #24
        ans = f"{config.PERMISSION_REFUSAL}\n\n### 한국어 번역\n권한이 없습니다."
        self.assertIsNotNone(repair_reason(ans, "Here is the list", [("get_certification_details", ROSTER)]))

    def test_real_refusal_is_kept(self):
        ans = f"{config.PERMISSION_REFUSAL}\n\n### 한국어 번역\n권한이 없습니다."
        self.assertIsNone(repair_reason(ans, config.PERMISSION_REFUSAL,
                                        [("get_certification_details", config.PERMISSION_REFUSAL)]))

    def test_not_covered_but_agent_cited(self):  # 라운드 3 #1
        ans = f"{config.NOT_IN_DOCUMENT}\n\n### 한국어 번역\n없습니다."
        self.assertIsNotNone(repair_reason(ans, "POV-007 requires ... [ID: POV-007]", []))

    def test_real_not_covered_is_kept(self):
        ans = f"{config.NOT_IN_DOCUMENT} I can help with requirement search.\n\n### 한국어 번역\n없습니다."
        self.assertIsNone(repair_reason(ans, config.NOT_IN_DOCUMENT, []))

    def test_missing_english(self):  # 라운드 4 #9
        self.assertIsNotNone(repair_reason("---\n\n### 한국어 번역\n네, PRJ-007이 있습니다.", "report", []))

    def test_normal_answer(self):
        self.assertIsNone(repair_reason(ANSWER, "report [ID: POV-007]", []))

    def test_last_agent_report(self):
        msgs = [HumanMessage(content="q"), AIMessage(content="agent says [ID: X-001]", name="assessment_agent"),
                AIMessage(content="Transferring back", name="supervisor")]
        self.assertEqual(last_agent_report(msgs), "agent says [ID: X-001]")


if __name__ == "__main__":
    unittest.main()
