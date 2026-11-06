"""CLI: python -m src.main --user <user_id> "질문"   (--user 생략 시 staff)
     python -m src.main --user <user_id> --chat     (멀티턴 대화: 최근 3턴 기억, /new 새 대화, /exit 종료)

흐름: 입력 가드레일 → Supervisor → 답변. 실행 기록은 trace.jsonl, 차단 사유는 guard_audit.log.
"""
import argparse
import asyncio
import logging
import re
import sys
import time
import uuid
import warnings

from langchain_core.messages import AIMessage, HumanMessage

# 라이브러리 import 시 경고(chromadb, authlib 등)는 import 동안만 출력을 막는다(일부 라이브러리가 필터를 덮어씀)
_show = warnings.showwarning
warnings.showwarning = lambda *args, **kwargs: None
from src import config  # noqa: E402
from src.agents import build_app, format_report, get_text  # noqa: E402
from src.guards.input_guard import input_guard, log_block, refusal_text  # noqa: E402
from src.report import is_report_request, save_report, with_appendix  # noqa: E402
from src.tracer import FileTracer  # noqa: E402
from src.guards.masking import mask_text  # noqa: E402
from src.workforce.directory import get_user  # noqa: E402
warnings.showwarning = _show
logging.getLogger("langchain_aws").setLevel(logging.ERROR)  # 도구 블록 변환 안내 로그 숨김
warnings.filterwarnings("ignore", category=RuntimeWarning, module="langchain_aws")  # 같은 안내의 경고판

DEFAULT_USER = "staff"
NOTE_TAG = "[내부 메모]"
NOTE_SOURCE_TOOLS = {"diff_versions"}  # internal_note(담당자 메모)를 돌려주는 도구


AGENT_NAMES = {"assessment_agent", "competency_agent", "workforce_agent", "general_agent"}
KO_SECTION = "### 한국어 번역"
HISTORY_TURNS = 3            # 멀티턴: 앞 대화는 최근 3턴만
HISTORY_ANSWER_CHARS = 1500  # 앞 답변은 영문 부분만, 이 길이까지


def english_part(answer: str) -> str:
    return answer.split(KO_SECTION)[0].replace("---", "").strip()


def last_agent_report(messages) -> str:
    """Supervisor가 받은 마지막 하위 에이전트 보고(도구 호출이 아닌 최종 메시지)."""
    for m in reversed(messages):
        if getattr(m, "name", None) in AGENT_NAMES and not getattr(m, "tool_calls", None):
            text = get_text(m).strip()
            if text:
                return text
    return ""


def history_messages(history: list[tuple[str, str]] | None) -> list:
    """멀티턴 앞 대화 → 메시지. 최근 HISTORY_TURNS턴, 답변은 영문 부분만(한국어 번역·[내부 메모] 제외).

    내부 메모가 다음 턴의 영문 답에 섞이지 않도록 영문 부분만 넘기고, 혹시 남은 [내부 메모] 줄도 지운다.
    """
    out = []
    for question, answer in (history or [])[-HISTORY_TURNS:]:
        en = "\n".join(line for line in english_part(answer).splitlines() if NOTE_TAG not in line).strip()
        out += [HumanMessage(content=question), AIMessage(content=en[:HISTORY_ANSWER_CHARS] or "(no answer)")]
    return out


def repair_reason(answer: str, report: str, tool_outputs: list[tuple[str, str]]) -> str | None:
    """Supervisor 최종 답이 실제 도구 결과·하위 에이전트 보고와 어긋나는지 파이썬 규칙으로 검사한다.

    어긋나면 사유를, 아니면 None을 돌려준다(라운드 3·4에서 발견한 세 가지 경우).
    """
    permission_outputs = [out for name, out in tool_outputs if name == "get_certification_details"]
    if (config.PERMISSION_REFUSAL in answer and permission_outputs
            and not any(out.strip() == config.PERMISSION_REFUSAL for out in permission_outputs)):
        return "권한 도구는 명단을 줬는데 최종 답이 '권한 없음'"
    if (config.NOT_IN_DOCUMENT in answer and report
            and config.NOT_IN_DOCUMENT not in report and "[ID:" in report):
        return "하위 에이전트는 근거를 보고했는데 최종 답이 '문서에 없음'"
    if len(english_part(answer)) < 20:
        return "최종 답에 영문 부분이 없음"
    return None


# '문서에 없음'을 풀어 쓴 영문 표현(라운드 10 #10). 지난 라운드 답변 전체에 돌려 정상 답변은 걸리지 않음을 확인했다.
NOT_COVERED_PARAPHRASE = re.compile(
    r"\b(no (information|mention|details?|data) (about|on|regarding|related to|for|of)"
    r"|not (covered|mentioned|addressed|specified|found) in the (assessment|documents?|requirements?)"
    r"|(does|do) not (cover|address|mention|contain|include) (any )?(information|details?|requirements?)"
    r" (about|on|regarding|for))", re.I)


def ensure_not_covered_phrase(answer: str) -> str:
    """영문 답이 '문서에 없음'을 풀어 썼는데 고정 문구가 빠졌으면 맨 앞에 고정 문구를 붙인다(판정 신호 일치)."""
    if config.NOT_IN_DOCUMENT in answer or not NOT_COVERED_PARAPHRASE.search(english_part(answer)):
        return answer
    return f"{config.NOT_IN_DOCUMENT}\n\n{answer.lstrip()}"


def strip_unsupported_notes(answer: str, tools_used: list[str]) -> str:
    """[내부 메모]는 도구가 돌려준 internal_note에만 쓴다. 메모를 주는 도구를 쓰지 않았으면 그 줄을 지운다."""
    if NOTE_SOURCE_TOOLS & set(tools_used):
        return answer
    return "\n".join(line for line in answer.splitlines() if NOTE_TAG not in line).rstrip()


async def ask(app, question: str, user_id: str = DEFAULT_USER, callbacks=None, save_reports: bool = True,
              history: list[tuple[str, str]] | None = None, session: tuple[str, int] | None = None) -> dict:
    """질문 하나를 실행한다: 입력 가드레일 → Supervisor. 모든 단계는 trace.jsonl에 남는다.

    history: 멀티턴 앞 대화 [(질문, 최종 답변), ...]. 없으면(한 번 묻기·평가) 메시지는 질문 하나뿐이다.
    session: (대화 ID, 턴 번호) — trace에는 턴 번호만 남긴다.

    반환: {"answer": 최종 답변, "blocked": 차단 여부, "result": 그래프 결과(차단 시 None),
           "report_files": 보고서 요청이면 {"en": 경로, "ko": 경로}, 아니면 None}
    """
    start = time.time()
    tracer = FileTracer(user_id=user_id, mask=mask_text)  # 모든 trace는 기록 직전 이름 마스킹
    tracer.question(question)
    if session:
        tracer.turn(session[0], session[1], min(len(history or []), HISTORY_TURNS))

    blocked, reason = input_guard(question)
    if blocked:
        log_block("injection", reason)
        tracer.blocked(question, reason)
        answer = refusal_text()
        tracer.answer(answer, time.time() - start)
        return {"answer": answer, "blocked": True, "result": None}

    run_config = {"configurable": {"user_id": user_id}, "recursion_limit": 30,
              "callbacks": [tracer, *(callbacks or [])]}
    messages = history_messages(history) + [HumanMessage(content=question)]
    result = await app.ainvoke({"messages": messages}, config=run_config)
    answer = get_text(result["messages"][-1])
    report = last_agent_report(result["messages"])
    reason = repair_reason(answer, report, tracer.tool_outputs)
    if reason and report:
        # Supervisor 최종 정리가 어긋나면 하위 에이전트 보고를 영문+한국어 형식으로 다시 쓴다(번역·형식만 LLM)
        tracer.repaired(reason)
        answer = await format_report(report)
    answer = strip_unsupported_notes(answer, tracer.tools_used)
    answer = ensure_not_covered_phrase(answer)
    if get_user(user_id)["role"] == "staff":
        answer = mask_text(answer)  # 일반 권한 답변은 출력 직전 이름 마스킹
    report_files = None
    if is_report_request(question):
        # 2단계 ⑤: 긴 목록은 도구 결과로 코드가 부록 표를 붙이고, 영문·국문 두 파일로 저장(영문본에는 [내부 메모] 없음)
        answer = with_appendix(answer, tracer.tool_outputs)
    if save_reports and is_report_request(question):
        report_files = save_report(question, answer)
        tracer.report_saved(report_files)
    tracer.answer(answer, time.time() - start)
    return {"answer": answer, "blocked": False, "result": result, "report_files": report_files}


async def _main(question: str, user_id: str):
    app = await build_app()
    out = await ask(app, question, user_id)
    print(out["answer"])
    if out.get("report_files"):
        print(f"\n[보고서 저장] {out['report_files']['en']}\n[보고서 저장] {out['report_files']['ko']}")


async def _chat(user_id: str):
    """멀티턴 대화. 사용자(권한)는 시작 때 정한 것으로 고정하고, 대화 기록은 메모리에만 둔다."""
    app = await build_app()
    history, session = [], uuid.uuid4().hex[:8]
    print(f"CompassPilot 대화 모드 · 사용자 {user_id} · 앞 대화 최근 {HISTORY_TURNS}턴 기억 · /new 새 대화 · /exit 종료")
    while True:
        try:
            question = input("\n질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            continue
        if question in ("/exit", "/quit"):
            break
        if question == "/new":
            history, session = [], uuid.uuid4().hex[:8]
            print("새 대화를 시작합니다.")
            continue
        out = await ask(app, question, user_id, history=history, session=(session, len(history) + 1))
        print(out["answer"])
        if out.get("report_files"):
            print(f"\n[보고서 저장] {out['report_files']['en']}\n[보고서 저장] {out['report_files']['ko']}")
        if not out["blocked"]:  # 차단된 질문은 앞 대화에 넣지 않는다
            history.append((question, out["answer"]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="CompassPilot CLI")
    ap.add_argument("--user", default=DEFAULT_USER, help="사용자 ID (권한 판정용, 기본 staff)")
    ap.add_argument("--chat", action="store_true", help="멀티턴 대화 모드")
    ap.add_argument("question", nargs="?", help="질문 (--chat이면 생략)")
    args = ap.parse_args()
    if args.chat:
        asyncio.run(_chat(args.user))
    elif args.question:
        asyncio.run(_main(args.question, args.user))
    else:
        ap.error("질문을 넣거나 --chat을 쓰세요")
