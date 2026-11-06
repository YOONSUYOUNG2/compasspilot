"""운영 지표: trace.jsonl 숫자 집계 (대시보드 전용, 파이썬, LLM 미사용).

trace에는 질문·답변 원문과 내부 메모가 들어 있으므로 **숫자와 정해진 분류 이름만** 돌려준다.
- 원문(input·output·last_input), 도구 입력·출력, 차단된 문장, 오류 메시지 원문은 돌려주지 않는다.
- 사용자는 user_id 대신 권한(role)으로 묶는다(디렉터리에 없으면 staff).
- 차단 사유는 [rule]/[llm] 판별 방식만, 자동 수정 사유는 아래 REPAIR_KINDS 분류만, 모델 오류는 ERROR_KINDS 분류만 쓴다.

실행: python -m src.ops
"""
import json
import sys
from collections import Counter, defaultdict

from src import config
from src.workforce.directory import get_user

REPAIR_KINDS = (("권한 없음", "permission"), ("문서에 없음", "not_covered"), ("영문", "empty_english"))
ERROR_KINDS = (("Throttling", "throttling"), ("timeout", "timeout"), ("Timeout", "timeout"))


def _kind(text: str, kinds, default="other") -> str:
    return next((k for key, k in kinds if key in (text or "")), default)


def percentile(values: list[float], p: float) -> float | None:
    """가장 가까운 순위 방식 백분위(0~100). 값이 없으면 None."""
    if not values:
        return None
    v = sorted(values)
    idx = max(0, min(len(v) - 1, round(p / 100 * len(v) + 0.5) - 1))
    return v[idx]


def load_events(path=config.TRACE_PATH) -> list[dict]:
    """trace.jsonl → 이벤트 목록. 깨진 줄은 건너뛴다(개수는 summarize가 따로 세지 않는다)."""
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def summarize(events: list[dict]) -> dict:
    by = defaultdict(list)
    for e in events:
        by[e.get("event")].append(e)
    answers = by["answer"]
    outputs = [a.get("output") or "" for a in answers]
    latencies = [a["latency_s"] for a in answers if isinstance(a.get("latency_s"), (int, float))]

    tools = defaultdict(lambda: {"calls": 0, "latency": [], "errors": 0})
    starts = {e["run_id"]: e.get("tool") for e in by["tool_start"] if e.get("run_id")}
    handoff = lambda name: (name or "").startswith("transfer_to_")  # 하위 에이전트 넘기기는 routing에서 센다
    for e in by["tool_start"]:
        if not handoff(e.get("tool")):
            tools[e.get("tool") or "?"]["calls"] += 1
    for e in by["tool_end"]:
        name = starts.get(e.get("run_id"), "?")
        if not handoff(name) and isinstance(e.get("latency_s"), (int, float)):
            tools[name]["latency"].append(e["latency_s"])
    for e in by["tool_error"]:
        name = starts.get(e.get("run_id"), "?")
        if not handoff(name):
            tools[name]["errors"] += 1

    routing = Counter(tc.removeprefix("transfer_to_") for e in by["llm_end"]
                      for tc in (e.get("tool_calls") or []) if tc.startswith("transfer_to_"))
    usage = [e.get("usage") or {} for e in by["llm_end"]]
    hours = Counter((e.get("ts") or "")[:13] for e in by["question"] if e.get("ts"))
    ts = sorted(e["ts"] for e in events if e.get("ts"))
    return {
        "period": {"from": ts[0] if ts else None, "to": ts[-1] if ts else None},
        "questions": len(by["question"]),
        "answers": len(answers),
        "by_role": dict(Counter(get_user(e.get("user_id"))["role"] for e in by["question"])),
        "routing": dict(routing.most_common()),
        "tools": {k: {"calls": v["calls"], "errors": v["errors"],
                      "avg_latency_s": round(sum(v["latency"]) / len(v["latency"]), 2) if v["latency"] else None}
                  for k, v in sorted(tools.items(), key=lambda kv: -kv[1]["calls"])},
        "guard_blocks": dict(Counter("llm" if (e.get("reason") or "").startswith("[llm]") else "rule"
                                     for e in by["guard_block"])),
        "refusals": {"permission": sum(config.PERMISSION_REFUSAL in o for o in outputs),
                     "not_covered": sum(config.NOT_IN_DOCUMENT in o for o in outputs),
                     "injection": sum(o.startswith(config.INJECTION_REFUSAL) for o in outputs)},
        "repairs": dict(Counter(_kind(e.get("reason"), REPAIR_KINDS) for e in by["answer_repaired"])),
        "reports_saved": len(by["report_saved"]),
        "latency_s": {"p50": percentile(latencies, 50), "p90": percentile(latencies, 90),
                      "max": max(latencies) if latencies else None},
        "llm": {"calls": len(by["llm_start"]),
                "input_tokens": sum(u.get("input_tokens") or 0 for u in usage),
                "output_tokens": sum(u.get("output_tokens") or 0 for u in usage),
                "errors": dict(Counter(_kind(e.get("error"), ERROR_KINDS) for e in by["llm_error"]))},
        "by_hour": dict(sorted(hours.items())),
    }


def ops_metrics(path=config.TRACE_PATH) -> dict | None:
    """trace 파일 집계. 파일이 없거나 비면 None."""
    events = load_events(path)
    return summarize(events) if events else None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(ops_metrics(), ensure_ascii=False, indent=1))
