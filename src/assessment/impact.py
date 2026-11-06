"""변경 영향 분석: 버전 비교 × 준비 상태 (대시보드 전용, 파이썬 규칙, LLM 미사용).

버전이 바뀌어 **이미 준비한 것 중 다시 손봐야 할 항목**을 찾는다. 기준표는 SERVICE.md 3절.

| 구분       | 조건                                      |
|------------|-------------------------------------------|
| rework     | 실질 변경 + 준비완료·일부                 |
| start      | 신규 추가, 또는 실질 변경 + 미준비        |
| wording    | 경미 변경(표기·오타)                      |
| retire     | 삭제 + 준비완료·일부                      |
| (없음)     | 변경 없음 → 개수만, 삭제 + 미준비 → 할 일 없음 |

준비 상태(readiness.csv)는 현재 상태 한 벌뿐이므로 최신 버전의 비교에만 적용한다.
삭제 항목의 준비 상태는 이전 버전의 Requirement로 판정한다(새 버전에는 없으므로).

실행: python -m src.assessment.impact
"""
import json
import sys

from src.assessment import diff, parser
from src.assessment.readiness import NOT_READY, load_readiness, readiness_of

REWORK, START, WORDING, RETIRE = "rework", "start", "wording", "retire"
CATEGORIES = (REWORK, START, WORDING, RETIRE)
LABEL_KO = {REWORK: "재작업 필요", START: "새 기준으로 착수", WORDING: "문구 확인", RETIRE: "준비 자료 정리"}
ACTION_KO = {REWORK: "준비한 자료를 새 원문 기준으로 고친다",
             START: "새 원문 기준으로 준비를 시작한다",
             WORDING: "자료에 인용한 원문 문구만 맞춘다",
             RETIRE: "더 이상 필요 없는 자료를 정리한다"}


def categorize(change: str, readiness: str) -> str | None:
    """변경 종류(added/removed/substantive/minor_notation/minor_typo/unchanged)와 준비 상태로 구분을 정한다."""
    prepared = readiness != NOT_READY
    if change == "added":
        return START
    if change == "removed":
        return RETIRE if prepared else None
    if change == diff.SUBSTANTIVE:
        return REWORK if prepared else START
    if change in (diff.MINOR_NOTATION, diff.MINOR_TYPO):
        return WORDING
    return None


def analyze(diff_result: dict, old_reqs: list[dict], new_reqs: list[dict], table: dict) -> dict:
    """diff.compare 결과와 두 버전의 Requirement 목록, 준비 상태 표로 영향 목록을 만든다."""
    old_by, new_by = {r["id"]: r for r in old_reqs}, {r["id"]: r for r in new_reqs}
    items = []

    def add(rid, req, change, extra=None):
        status = readiness_of(req, table)["status"]
        cat = categorize(change, status)
        if cat:
            items.append({"id": rid, "title": req["title"], "scope": req["scope"], "change": change,
                          "readiness": status, "category": cat, **(extra or {})})

    for a in diff_result["added"]:
        add(a["id"], new_by[a["id"]], "added")
    for c in diff_result["changed"]:
        add(c["id"], new_by[c["id"]], c["change_type"],
            {"changes": c["changes"], "old_text": c["old_text"], "new_text": c["new_text"]})
    for r in diff_result["removed"]:
        add(r["id"], old_by[r["id"]], "removed")

    order = {c: i for i, c in enumerate(CATEGORIES)}
    items.sort(key=lambda i: (order[i["category"]], i["id"]))
    counts = {c: sum(i["category"] == c for i in items) for c in CATEGORIES}
    counts["unchanged"] = diff_result["counts"]["unchanged"]
    counts["sheet_notes"] = len(diff_result["sheet_notes_changed"])
    return {"from_version": diff_result["from_version"], "to_version": diff_result["to_version"],
            "counts": counts, "items": items,
            "sheet_notes": [{"sheet": n["sheet"], "change_type": n["change_type"]}
                            for n in diff_result["sheet_notes_changed"]]}


def impact(old_label: str | None = None, new_label: str | None = None, table: dict | None = None) -> dict:
    """등록된 버전으로 영향 분석을 한다. 생략하면 직전 vs 최신, 준비 상태는 data/sample/readiness.csv."""
    new_label = new_label or parser.latest_version()
    old_label = old_label or parser.previous_version(new_label)
    if old_label is None:
        raise ValueError(f"{new_label}보다 이전 버전이 없어 영향 분석을 할 수 없습니다")
    old, new = parser.load(old_label), parser.load(new_label)
    return analyze(diff.compare(old, new), old["requirements"], new["requirements"],
                   load_readiness() if table is None else table)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = impact()
    print(f"{r['from_version']} → {r['to_version']}: {json.dumps(r['counts'], ensure_ascii=False)}")
    for i in r["items"]:
        print(f"{LABEL_KO[i['category']]:<10} {i['id']:<8} {i['change']:<15} {i['readiness']:<10} {i['title']}")
