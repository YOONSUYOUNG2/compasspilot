"""난이도 점수 (2단계 ③, CLAUDE.md 5.3). 점수 계산은 모두 파이썬 규칙으로 한다.

점수 = 준비 상태(미준비 +2 / 일부 +1 / 준비완료 0)
     + 고객 사례 4건 증빙 항목 +1
     + 이번 버전 신규 항목 +1 (직전 버전에 없던 ID)
등급: 0~1점 low(하), 2점 medium(중), 3~4점 high(상). 점수 근거를 함께 돌려준다.
산출물 개수는 점수에 넣지 않는다(산출물은 2단계 ④에서 붙인다).
"""
from collections import Counter

from src.assessment import parser
from src.assessment.readiness import NOT_READY, PARTIAL, load_readiness, readiness_of

READINESS_POINTS = {NOT_READY: 2, PARTIAL: 1}
LEVEL_KO = {"high": "상", "medium": "중", "low": "하"}


def level_of(score: int) -> str:
    if score >= 3:
        return "high"
    return "medium" if score == 2 else "low"


def score_requirement(req: dict, readiness: dict, is_new: bool, version: str) -> dict:
    """Requirement 하나의 점수·등급·근거."""
    reasons = []
    points = READINESS_POINTS.get(readiness["status"], 0)
    reasons.append(f"readiness {readiness['status']} ({readiness['basis']}): +{points}")
    score = points
    if req["scope"] != "company":
        score += 1
        reasons.append("evidence required for each of 4 customer examples: +1")
    if is_new:
        score += 1
        reasons.append(f"new in version {version}: +1")
    level = level_of(score)
    return {"id": req["id"], "title": req["title"], "sheet": req["sheet"], "readiness": readiness["status"],
            "score": score, "level": level, "level_ko": LEVEL_KO[level], "reasons": reasons}


def assess(ids: list[str] | None = None, version: str | None = None, readiness_table: dict | None = None) -> dict:
    """버전의 Requirement 난이도를 판정한다. ids가 없으면 전체.

    반환: {version, counts{high,medium,low}, items[...], unknown_ids[...]}
    """
    version = version or parser.latest_version()
    data = parser.load(version)
    labels = parser.list_versions()
    idx = labels.index(version)
    prev_ids = {r["id"] for r in parser.load(labels[idx - 1])["requirements"]} if idx > 0 else None
    table = load_readiness() if readiness_table is None else readiness_table

    reqs = data["requirements"]
    unknown = []
    if ids:
        wanted = [i.strip().upper() for i in ids if i.strip()]
        by_id = {r["id"]: r for r in reqs}
        unknown = [i for i in wanted if i not in by_id]
        reqs = [by_id[i] for i in wanted if i in by_id]
    items = [score_requirement(r, readiness_of(r, table),
                               is_new=prev_ids is not None and r["id"] not in prev_ids, version=version)
             for r in reqs]
    counts = Counter(i["level"] for i in items)
    return {"version": version, "previous_version": labels[idx - 1] if idx > 0 else None,
            "counts": {k: counts.get(k, 0) for k in ("high", "medium", "low")},
            "items": items, "unknown_ids": unknown}
