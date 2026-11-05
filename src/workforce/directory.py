"""사용자 권한·소속 조회 (data/sample/org_users.json, 가상 데이터).

권한은 user_id로 이 디렉터리에서만 정한다. 질문 내용이나 LLM이 넘기는 인자로는 바뀌지 않는다(CLAUDE.md 5.3).
  hr            전사
  division_head 본인 사업부
  team_leader   본인 사업부 + 팀
  group_leader  본인 사업부 + 팀 + 그룹
  staff         명단 없음 (숫자 집계만). 미등록 사용자도 staff
"""
import json
from functools import lru_cache

from src import config

ORG_USERS = config.SAMPLE_DIR / "org_users.json"
ROLES = ("hr", "division_head", "team_leader", "group_leader", "staff")
ROLE_LABEL = {"hr": "인사팀", "division_head": "담당", "team_leader": "팀장",
              "group_leader": "그룹장", "staff": "일반"}


@lru_cache(maxsize=1)
def load_directory() -> dict:
    return json.loads(ORG_USERS.read_text(encoding="utf-8"))


def get_user(user_id: str | None) -> dict:
    """사용자의 권한과 소속. 등록되지 않은 사용자는 소속 없는 staff로 본다."""
    for u in load_directory()["users"]:
        if u["user_id"] == user_id:
            return u
    return {"user_id": user_id or "anonymous", "role": "staff", "division": None, "team": None, "group": None}


def employee_names() -> list[str]:
    """디렉터리에 있는 임직원 이름 목록(마스킹 대상)."""
    return [e["name"] for e in load_directory()["employees"]]


def in_scope(user: dict, row: dict) -> bool:
    """이 행(임직원)이 사용자의 명단 조회 범위 안에 있는가. 사용자 소속과 계층이 일치해야 한다."""
    role = user["role"]
    if role == "hr":
        return True
    if role == "division_head":
        return row["division"] == user["division"]
    if role == "team_leader":
        return (row["division"], row["team"]) == (user["division"], user["team"])
    if role == "group_leader":
        return (row["division"], row["team"], row["group"]) == (user["division"], user["team"], user["group"])
    return False  # staff: 명단 없음
