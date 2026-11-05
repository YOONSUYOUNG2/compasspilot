"""CompassPilot MCP 서버 (fastmcp, stdio).

노출하는 도구 (1단계):
  - diff_versions(from_version, to_version)   Assessment 버전 간 변경 내역
2단계에서 assess_difficulty, list_deliverables를 추가한다.

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
from src.assessment import diff, parser

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


if __name__ == "__main__":
    mcp.run(show_banner=False)  # stdio 모드로 대기 (안내 배너는 끈다)
