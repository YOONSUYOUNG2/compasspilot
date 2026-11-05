"""파트너 등급 현주소 비교 (대시보드 '현주소' 시트). 순위·격차·전망은 모두 파이썬으로 계산한다(LLM 없음).

입력 (가상 데이터, 실제 회사와 무관. 비교 대상은 익명 A사~E사)
- data/sample/partner_benchmark.csv : company, is_us, aws_tier, competencies, certified_people, launches, in_progress
- data/sample/tier_criteria.csv     : tier, level, competencies, certified_people, launches  (등급별 기준, 가상)

계산
- 종합 순위: 등급 → Competency 수 → 자격 인원 순으로 비교한다. 값이 모두 같으면 같은 순위(공동)다.
- 지표별 순위와 격차: 1위와의 차이, 바로 위 순위와의 차이
- 다음 등급 조건: 지표마다 현재·기준·부족분
- 전망: 진행 중인 Competency(in_progress)를 취득하면(+1) 순위와 다음 등급 조건이 어떻게 바뀌는가
"""
import csv

from src import config

BENCHMARK_CSV = config.SAMPLE_DIR / "partner_benchmark.csv"
CRITERIA_CSV = config.SAMPLE_DIR / "tier_criteria.csv"
METRICS = [("competencies", "Competency 수", "개"), ("certified_people", "AWS 자격 인원", "명"), ("launches", "고객 사례(Launch)", "건")]


def _read(path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load(bench_path=BENCHMARK_CSV, criteria_path=CRITERIA_CSV) -> tuple[list[dict], list[dict]]:
    criteria = sorted(({"tier": r["tier"].strip(), "level": int(r["level"]),
                        **{m: int(r[m]) for m, _, _ in METRICS}} for r in _read(criteria_path)), key=lambda c: c["level"])
    level = {c["tier"]: c["level"] for c in criteria}
    companies = []
    for r in _read(bench_path):
        tier = r["aws_tier"].strip()
        if tier not in level:
            raise ValueError(f"{r['company']}: 등급 기준에 없는 등급 '{tier}'")
        companies.append({"company": r["company"].strip(), "is_us": r["is_us"].strip() == "1", "tier": tier,
                          "level": level[tier], **{m: int(r[m]) for m, _, _ in METRICS},
                          "in_progress": (r.get("in_progress") or "").strip()})
    if sum(c["is_us"] for c in companies) != 1:
        raise ValueError("is_us=1인 회사(우리 회사)가 정확히 하나여야 합니다")
    return companies, criteria


def _overall_key(c: dict) -> tuple:
    return (c["level"], c["competencies"], c["certified_people"])


def rank_of(target: dict, others: list[dict], key) -> int:
    """target보다 엄격히 앞선 회사 수 + 1 (같으면 공동 순위)."""
    return 1 + sum(1 for o in others if o is not target and key(o) > key(target))


def next_tier(us: dict, criteria: list[dict]) -> dict | None:
    """다음 등급과 조건별 현재·기준·부족분. 최고 등급이면 None."""
    nxt = next((c for c in criteria if c["level"] == us["level"] + 1), None)
    if not nxt:
        return None
    conds = [{"metric": m, "label": label, "unit": unit, "current": us[m], "required": nxt[m],
              "gap": max(0, nxt[m] - us[m]), "met": us[m] >= nxt[m]} for m, label, unit in METRICS]
    return {"tier": nxt["tier"], "conditions": conds, "all_met": all(c["met"] for c in conds)}


def status(companies: list[dict] | None = None, criteria: list[dict] | None = None) -> dict:
    if companies is None or criteria is None:
        companies, criteria = load()
    us = next(c for c in companies if c["is_us"])
    n = len(companies)

    metrics = []
    for m, label, unit in METRICS:
        values = sorted({c[m] for c in companies}, reverse=True)
        above = [v for v in values if v > us[m]]
        metrics.append({"metric": m, "label": label, "unit": unit, "us": us[m],
                        "rank": rank_of(us, companies, lambda c, m=m: c[m]), "leader": values[0],
                        "gap_to_leader": values[0] - us[m], "gap_to_next": (min(above) - us[m]) if above else 0,
                        "companies": sorted(({"company": c["company"], "is_us": c["is_us"], "value": c[m]} for c in companies),
                                            key=lambda x: (-x["value"], not x["is_us"], x["company"]))})

    ranked = sorted(companies, key=lambda c: (_overall_key(c), c["is_us"]), reverse=True)
    table = [{**{k: c[k] for k in ("company", "is_us", "tier", "level", "competencies", "certified_people", "launches")},
              "rank": rank_of(c, companies, _overall_key)} for c in ranked]
    overall = rank_of(us, companies, _overall_key)
    above = [c for c in companies if _overall_key(c) > _overall_key(us)]
    nearest = min(above, key=_overall_key) if above else None

    projection = None
    if us["in_progress"]:  # 진행 중인 Competency를 취득하면(+1) 어떻게 바뀌는가
        after = {**us, "competencies": us["competencies"] + 1}
        others = [c for c in companies if not c["is_us"]]
        nt = next_tier(after, criteria)
        comp_key = lambda c: c["competencies"]  # noqa: E731
        projection = {"competency": us["in_progress"], "competencies": after["competencies"],
                      "overall_rank": rank_of(after, others + [after], _overall_key),
                      "competency_rank": rank_of(after, others + [after], comp_key),
                      "competency_tied": any(comp_key(o) == comp_key(after) for o in others),
                      "next_tier": nt, "tier_up": None}
        if nt and not nt["all_met"]:  # 남은 조건까지 채우면 다음 등급으로 오른다
            full = {**after, **{c["metric"]: max(c["current"], c["required"]) for c in nt["conditions"]}}
            nxt = next(c for c in criteria if c["tier"] == nt["tier"])
            full["level"] = nxt["level"]
            projection["tier_up"] = {"tier": nt["tier"], "remaining": [c for c in nt["conditions"] if not c["met"]],
                                     "overall_rank": rank_of(full, others + [full], _overall_key),
                                     "same_tier": [o["company"] for o in others if o["level"] == nxt["level"]]}

    return {"us": {k: us[k] for k in ("company", "tier", "level", "competencies", "certified_people", "launches", "in_progress")},
            "companies": n, "overall_rank": overall,
            "tied": sum(1 for c in companies if _overall_key(c) == _overall_key(us)) > 1,
            "nearest_above": {"company": nearest["company"], "tier": nearest["tier"],
                              **{m: nearest[m] - us[m] for m, _, _ in METRICS}} if nearest else None,
            "tiers": [{"tier": c["tier"], "level": c["level"],
                       "companies": [x["company"] for x in ranked if x["level"] == c["level"]]} for c in criteria],
            "next_tier": next_tier(us, criteria), "metrics": metrics, "table": table, "projection": projection}
