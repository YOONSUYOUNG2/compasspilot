"""운영 지표 테스트 (SERVICE.md 3절): 가상 trace로 집계 규칙과 원문 미포함을 확인한다."""
import json
import tempfile
import unittest
from pathlib import Path

from src import config
from src.ops import ops_metrics, percentile, summarize

SECRET = "비밀원문-질문-내부메모"


def ev(event, tid="t1", **kw):
    return {"ts": "2026-11-06 10:15:00", "trace_id": tid, "user_id": "staff", "event": event, **kw}


EVENTS = [
    ev("question", input=SECRET), ev("question", "t2", user_id="hr01", input=SECRET),
    ev("question", "t3", input="ignore previous " + SECRET),
    ev("guard_block", "t3", input=SECRET, reason="[rule] rule: ignore ..."),
    ev("answer", "t3", output=config.INJECTION_REFUSAL + " " + SECRET, latency_s=1.0),
    ev("llm_start", run_id="l1", agent="supervisor", last_input=SECRET),
    ev("llm_end", run_id="l1", output=SECRET, tool_calls=["transfer_to_assessment_agent"], latency_s=2.0,
       usage={"input_tokens": 100, "output_tokens": 10}),
    ev("llm_error", run_id="l2", error="An error occurred (ThrottlingException) " + SECRET),
    ev("tool_start", run_id="h1", tool="transfer_to_assessment_agent", input=SECRET),
    ev("tool_start", run_id="r1", tool="search_requirements", input=SECRET),
    ev("tool_end", run_id="r1", output=SECRET, latency_s=0.5),
    ev("tool_start", run_id="r2", tool="search_requirements", input=SECRET),
    ev("tool_error", run_id="r2", error=SECRET),
    ev("answer_repaired", reason="권한 도구는 명단을 줬는데 최종 답이 '권한 없음'"),
    ev("answer", output="Answer. " + config.NOT_IN_DOCUMENT + SECRET, latency_s=3.0),
    ev("answer", "t2", user_id="hr01", output=config.PERMISSION_REFUSAL, latency_s=10.0),
    ev("report_saved", files=["reports/x_en.md"]),
]


class TestOps(unittest.TestCase):
    def test_counts(self):
        r = summarize(EVENTS)
        self.assertEqual((r["questions"], r["answers"]), (3, 3))
        self.assertEqual(r["by_role"], {"staff": 2, "hr": 1})
        self.assertEqual(r["routing"], {"assessment_agent": 1})
        self.assertEqual(r["tools"], {"search_requirements": {"calls": 2, "errors": 1, "avg_latency_s": 0.5}})
        self.assertEqual(r["guard_blocks"], {"rule": 1})
        self.assertEqual(r["refusals"], {"permission": 1, "not_covered": 1, "injection": 1})
        self.assertEqual(r["repairs"], {"permission": 1})
        self.assertEqual(r["reports_saved"], 1)
        self.assertEqual(r["llm"], {"calls": 1, "input_tokens": 100, "output_tokens": 10, "errors": {"throttling": 1}})
        self.assertEqual(r["latency_s"], {"p50": 3.0, "p90": 10.0, "max": 10.0})
        self.assertEqual(r["by_hour"], {"2026-11-06 10": 3})

    def test_no_raw_text(self):
        self.assertNotIn(SECRET, json.dumps(summarize(EVENTS), ensure_ascii=False))

    def test_percentile(self):
        self.assertEqual([percentile([1, 2, 3, 4], p) for p in (50, 90)], [2, 4])
        self.assertIsNone(percentile([], 50))

    def test_missing_or_broken_file(self):
        self.assertIsNone(ops_metrics(Path(tempfile.gettempdir()) / "no_such_trace.jsonl"))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text("{broken\n" + json.dumps(ev("question", input="q")) + "\n", encoding="utf-8")
            self.assertEqual(ops_metrics(p)["questions"], 1)


if __name__ == "__main__":
    unittest.main()
