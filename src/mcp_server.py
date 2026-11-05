"""CompassPilot MCP 서버 (fastmcp, stdio).

노출하는 도구:
  - diff_versions(from_version, to_version)         Assessment 버전 간 변경 내역 (1단계)
  - assess_difficulty(requirement_ids, version)     준비 난이도와 점수 근거 (2단계 ③)
  - list_deliverables(requirement_ids, version)     필요 산출물과 고객 사례 체크리스트 (2단계 ④, 미리 추출한 파일만 읽음)

계산은 src/assessment의 파이썬 규칙이 하고, 이 서버는 결과를 JSON으로 돌려주기만 한다.
클라이언트(agents.py)가 자식 프로세스로 띄운다: python -m src.mcp_server
"""
import json
import os
import sys
import warnings

# fastmcp가 import될 때 authlib가 경고를 '항상 표시'로 강제 등록하므로, import 동안만 경고 출력을 막는다.
_show = warnings.showwarning
warnings.showwarning = lambda *args, **kwargs: None
from fastmcp import FastMCP  # noqa: E402
warnings.showwarning = _show

from src import config
from src.assessment import deliverables, diff, difficulty, parser

mcp = FastMCP("compasspilot")

# 클라이언트(MultiServerMCPClient)가 이 서버를 띄울 때 쓰는 설정
MCP_SERVER_CONFIG = {
    "compasspilot": {
        "command": sys.executable,
        "args": ["-m", "src.mcp_server"],
        "transport": "stdio",
        "cwd": str(config.ROOT),
        # 서버 프로세스의 라이브러리 경고와 시작 로그를 줄인다(stderr 출력 정리)
        "env": {**os.environ, "PYTHONWARNINGS": "ignore", "FASTMCP_LOG_LEVEL": "WARNING"},
    }
}


@mcp.tool()
def diff_versions(from_version: str = "", to_version: str = "") -> str:
    """AWS M&M Competency Assessment 두 버전 사이의 변경 내역을 정리한다.

    언제 쓰나: "이번 버전에서 새로 추가된/바뀐/삭제된 요구사항", "POV-001이 어떻게 바뀌었나",
      "오타나 표기만 바뀐 항목", "시트 안내문 변경"처럼 버전 간 차이를 묻는 질문.
    쓰지 않는 경우: 요구사항의 내용 자체를 묻는 질문(→ search_requirements).

    결과(JSON):
      counts: 추가/삭제/실질 변경/경미 변경/안내문 변경 건수
      added, removed: [{id, title, sheet, internal_note}]
      changed: [{id, title, change_type, changes(바뀐 단어 구간), old_text, new_text, internal_note}]
        change_type: substantive(실질 변경) | minor_notation(대소문자·문장부호) | minor_typo(오타)
      sheet_notes_changed: 시트 상단 안내문 변경
      internal_note는 담당자 한글 메모다. 영문 답변에는 쓰지 말고 한국어 번역 섹션에만 [내부 메모]로 쓴다.

    Args:
        from_version: 이전 버전 (예: "2025-08"). 비우면 to_version의 직전 버전.
        to_version: 새 버전 (예: "2026-08"). 비우면 최신 버전.
    """
    versions = parser.list_versions()
    for v in (from_version, to_version):
        if v and v not in versions:
            return json.dumps({"error": f"Unknown version '{v}'", "registered_versions": versions})
    try:
        result = diff.diff_versions(from_version or None, to_version or None)
    except ValueError as e:
        return json.dumps({"error": str(e), "registered_versions": versions})
    result["registered_versions"] = versions
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def assess_difficulty(requirement_ids: str = "", version: str = "") -> str:
    """Requirement의 준비 난이도(high/medium/low)와 점수 근거를 파이썬 규칙으로 판정한다.

    언제 쓰나: "POV-007 난이도는?", "준비하기 어려운 항목", "신규 항목들의 난이도", "난이도 분포"처럼
      준비 난이도·준비 상태를 묻는 질문. 신규·변경 항목의 난이도는 diff_versions로 ID를 먼저 얻고 그 ID를 넣는다.
    쓰지 않는 경우: 요구사항 내용(→ search_requirements), 버전 간 변경 내역 자체(→ diff_versions).

    점수 규칙: 준비 상태 not_ready +2 / partial +1 / ready 0, 고객 사례 4건 증빙 항목 +1, 이번 버전 신규 +1.
      0~1점 low, 2점 medium, 3~4점 high. 직접 계산하지 말고 결과의 score·level·reasons를 그대로 보고한다.

    결과(JSON): version, counts{high,medium,low}, items[{id, title, readiness, score, level, reasons}], unknown_ids

    Args:
        requirement_ids: 쉼표로 구분한 ID (예: "POV-007,PRJ-007"). 비우면 해당 버전 전체.
        version: 버전 (예: "2026-08"). 비우면 최신 버전.
    """
    versions = parser.list_versions()
    if version and version not in versions:
        return json.dumps({"error": f"Unknown version '{version}'", "registered_versions": versions})
    ids = [i for i in requirement_ids.replace(" ", ",").split(",") if i.strip()]
    result = difficulty.assess(ids or None, version or None)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def list_deliverables(requirement_ids: str = "", version: str = "", scope: str = "") -> str:
    """Requirement별로 제출해야 할 산출물(증빙 자료)과 고객 사례 4건 체크리스트를 보여 준다.

    언제 쓰나: "MOB-004에 필요한 산출물", "무엇을 제출/준비해야 하나(증빙 자료 목록)", "고객 사례별 준비 체크리스트".
      신규·변경 항목의 산출물은 diff_versions로 ID를 먼저 얻고 그 ID를 넣는다.
    쓰지 않는 경우: 요구사항의 의미·조건 설명(→ search_requirements), 버전 간 변경 내역(→ diff_versions),
      난이도(→ assess_difficulty).

    산출물은 색인할 때 원문에서 미리 추출해 둔 결과다(이 도구는 LLM을 호출하지 않는다). 목록을 지어내거나 더하지 말고 그대로 보고한다.
    결과(JSON): version, summary(파이썬 집계: requirements, deliverables, company_level, customer_all_4,
      customer_at_least_2_or_3, customer_at_least_1 — 개수는 직접 세지 말고 이 값을 인용한다),
      items[{id, title, scope, checklist, customer_examples_required, deliverables[{name, description}]}], unknown_ids
      customer_examples_required: 고객 사례 4건 중 몇 건에 준비해야 하는지 (회사 차원 항목은 null)

    Args:
        requirement_ids: 쉼표로 구분한 ID (예: "MOB-004,PS-001"). 비우면 해당 버전 전체.
        version: 버전 (예: "2026-08"). 비우면 최신 버전.
        scope: "customer_example"이면 고객 사례 4건마다 증빙하는 항목만, "company"면 회사 차원 항목만. 비우면 전체.
          "고객 사례(4건) 준비용 체크리스트"에는 "customer_example"을 넣는다.
    """
    versions = parser.list_versions()
    if version and version not in versions:
        return json.dumps({"error": f"Unknown version '{version}'", "registered_versions": versions})
    if scope and scope not in ("company", "customer_example"):
        return json.dumps({"error": f"Unknown scope '{scope}'. Use 'company' or 'customer_example'."})
    ids = [i for i in requirement_ids.replace(" ", ",").split(",") if i.strip()]
    return json.dumps(deliverables.lookup(ids or None, version or None, scope=scope or None), ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(show_banner=False)  # stdio 모드로 대기 (안내 배너는 끈다)
