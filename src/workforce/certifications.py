"""임직원 자격 도구: 숫자 집계(누구나)와 권한 범위 안의 명단 조회 (가상 데이터).

- 사용자는 RunnableConfig의 configurable.user_id에서만 읽는다(LLM 인자로 받지 않는다 → 위조 방지).
- LLM이 넘기는 조직 인자는 '범위를 좁히는' 용도로만 쓴다. 사용자 범위 밖을 요청하면 거절한다.
"""
import csv
import json
from collections import Counter
from functools import lru_cache

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src import config
from src.workforce.directory import ROLE_LABEL, get_user, in_scope, load_directory

CERTS_CSV = config.SAMPLE_DIR / "certifications.csv"
ORG_KEYS = ("division", "team", "group")


@lru_cache(maxsize=1)
def load_certifications() -> list[dict]:
    with CERTS_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _match(row: dict, vendor: str, certification: str) -> bool:
    if vendor and vendor.lower() not in row["vendor"].lower():
        return False
    if certification and certification.lower() not in row["certification"].lower():
        return False
    return True


def count(vendor: str = "", group_by: str = "certification") -> dict:
    """자격 보유 숫자 집계. 이름은 포함하지 않는다(모든 사용자 공통)."""
    rows = [r for r in load_certifications() if _match(r, vendor, "")]
    key = {"vendor": lambda r: r["vendor"],
           "certification": lambda r: f"{r['vendor']} | {r['certification']}",
           "division": lambda r: f"{r['division']} | {r['vendor']}"}.get(group_by)
    if key is None:
        return {"error": f"group_by must be one of vendor, certification, division (got '{group_by}')"}
    return {
        "scope": "company-wide (counts only, no names)",
        "total_certifications": len(rows),
        "certified_employees": len({r["employee_id"] for r in rows}),
        "by_" + group_by: dict(sorted(Counter(key(r) for r in rows).items())),
    }


def resolve_org(division: str, team: str, group: str) -> dict | None:
    """요청한 조직 이름을 조직도로 상위 계층까지 채운다. 없는 이름이거나 계층이 어긋나면 None."""
    org = load_directory()["organization"]
    if not (division or team or group):
        return {"division": "", "team": "", "group": ""}
    for d, teams in org.items():
        for t, groups in teams.items():
            for g in groups:
                if group and g != group:
                    continue
                if team and t != team:
                    continue
                if division and d != division:
                    continue
                # 가장 아래로 지정한 계층까지만 채운다 (팀만 지정하면 그룹은 비움)
                return {"division": d, "team": t if (team or group) else "", "group": g if group else ""}
    return None


def _in_requested(row: dict, requested: dict) -> bool:
    return all(not requested[k] or row[k] == requested[k] for k in ORG_KEYS)


def details(user_id: str | None, vendor: str = "", certification: str = "",
            division: str = "", team: str = "", group: str = "", other_than_mine: str = "") -> dict | str:
    """권한 범위 안의 자격 보유자 명단. 범위 밖이면 고정 거절 문구를 돌려준다.

    other_than_mine: "다른 사업부/팀/그룹"처럼 이름 없이 '내 것이 아닌' 조직을 요청할 때의 계층
      ("division" | "team" | "group"). 사용자 소속이 그 계층에서 정해져 있으면(예: 그룹장의 '다른 그룹')
      그 조직은 범위 밖이므로 거절한다. 정해져 있지 않으면(예: 팀장의 '다른 그룹' = 같은 팀 안) 범위 안이다.
    """
    user = get_user(user_id)
    if user["role"] == "staff":
        return config.PERMISSION_REFUSAL
    level = other_than_mine.strip().lower()
    if level:
        if level not in ORG_KEYS:
            return {"error": "other_than_mine must be one of division, team, group"}
        if user.get(level):
            return config.PERMISSION_REFUSAL
    requested = resolve_org(division.strip(), team.strip(), group.strip())
    if requested is None:
        return {"error": "Unknown organization name", "organization": load_directory()["organization"]}
    # 요청한 조직(상위 계층까지 펼친 것)이 사용자 범위 밖이면 거절
    # 예: 담당 A사업부가 B사업부 요청, 팀장 A1팀이 A2-1그룹 요청, 그룹장이 같은 팀의 다른 그룹 요청
    if any(requested.values()) and not in_scope(user, requested):
        return config.PERMISSION_REFUSAL
    rows = [r for r in load_certifications()
            if in_scope(user, r) and _match(r, vendor, certification) and _in_requested(r, requested)]
    return {
        "viewer_role": ROLE_LABEL[user["role"]],
        "viewer_scope": {k: user.get(k) for k in ORG_KEYS if user.get(k)} or "company-wide",
        "count": len(rows),
        "holders": [{k: r[k] for k in ("name", "division", "team", "group", "vendor", "certification")}
                    for r in rows],
    }


def _user_id(cfg: RunnableConfig | None) -> str | None:
    return ((cfg or {}).get("configurable") or {}).get("user_id")


@tool
def count_certifications(vendor: str = "", group_by: str = "certification", config: RunnableConfig = None) -> str:
    """임직원 자격 보유 현황을 숫자로 집계한다(이름 없음). 모든 사용자가 쓸 수 있다.

    언제 쓰나: "AWS 자격증 보유 현황", "자격증별 인원", "사업부별 보유 수"처럼 숫자를 묻는 질문.
    쓰지 않는 경우: 이름이 들어간 명단을 묻는 질문(→ get_certification_details).
    vendor: "AWS", "Google Cloud", "OpenAI" 중 하나로 좁힐 때만 넣는다.
    group_by: "vendor" | "certification"(기본) | "division"
    """
    return json.dumps(count(vendor, group_by), ensure_ascii=False)


@tool
def get_certification_details(vendor: str = "", certification: str = "", division: str = "",
                              team: str = "", group: str = "", other_than_mine: str = "",
                              config: RunnableConfig = None) -> str:
    """자격 보유자 명단(이름 포함)을 조회한다. 사용자 권한 범위 안의 명단만 돌려준다.

    언제 쓰나: "보유자 명단", "누가 자격증을 갖고 있나", "이름이랑 자격증 목록"처럼 이름을 묻는 질문.
    권한은 시스템이 사용자 ID로 판단한다. 사용자의 직책이나 소속을 인자로 넣지 않는다.
    division/team/group: 질문에 특정 조직(예: "B사업부", "A2팀", "A1-2그룹")이 나올 때만 그대로 넣는다.
      "우리 사업부/팀/그룹"처럼 자기 조직을 말하면 비워 둔다.
    other_than_mine: 이름 없이 "다른 사업부/다른 팀/다른 그룹"을 물으면 "division"/"team"/"group"을 넣는다.
      되묻지 말고 이 인자로 바로 호출한다. 범위 판단은 시스템이 한다.
    결과가 "You do not have permission to view this information."이면 그 문장을 그대로 답한다.
    """
    result = details(_user_id(config), vendor, certification, division, team, group, other_than_mine)
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
