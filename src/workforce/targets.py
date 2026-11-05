"""자격 취득 대상 대비 실적 집계 (사내 취합 자료 구조 반영). 계산은 모두 파이썬, 결과는 숫자만(이름 없음).

입력
- data/sample/cert_targets.csv : employee_id, vendor  — 사람별 취득 대상 벤더 (가상 데이터)
- data/sample/certifications.csv : 보유 자격 (그 벤더 자격이 1건 이상이면 '취득'으로 본다)
- data/sample/org_users.json : 조직도 (사번 → 사업부·팀·그룹)

집계 (사내 '교육 수료현황' 취합 양식과 같은 관점)
- 벤더별(연인원): 대상, 취득, 미취득, 취득률
- 사람별(실인원): 대상 인원, 전부 취득, 일부 취득, 미취득(0건), 2개 이상 벤더 대상자
- 사업부·팀·그룹별: 벤더마다 대상·취득
- 점검: 조직도에 없는 사번, 중복 행(0이어야 정상) / 대상이 아닌데 보유(참고)
  가상 데이터에는 점검 기능을 보이려고 오류를 일부러 넣었다(E099 사번, E003 AWS 중복).
"""
import csv
from collections import Counter, defaultdict

from src import config
from src.workforce.certifications import load_certifications
from src.workforce.directory import load_directory

TARGETS_CSV = config.SAMPLE_DIR / "cert_targets.csv"


def load_targets(path=TARGETS_CSV) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [{"employee_id": r["employee_id"].strip(), "vendor": r["vendor"].strip()} for r in csv.DictReader(f)]


def _rate(achieved: int, target: int) -> float | None:
    return round(achieved / target, 3) if target else None


def target_status(targets: list[dict] | None = None, certs: list[dict] | None = None,
                  employees: list[dict] | None = None) -> dict:
    """대상 대비 취득 현황(숫자만). 인자를 주지 않으면 가상 데이터 파일을 읽는다."""
    targets = load_targets() if targets is None else targets
    certs = load_certifications() if certs is None else certs
    employees = load_directory()["employees"] if employees is None else employees
    org = {e["employee_id"]: e for e in employees}

    # 점검: 조직도에 없는 사번, 중복 행은 집계에서 뺀다
    pairs = Counter((t["employee_id"], t["vendor"]) for t in targets)
    duplicate_rows = sum(n - 1 for n in pairs.values() if n > 1)
    unknown_ids = sorted({e for e, _ in pairs if e not in org})
    valid = sorted(p for p in pairs if p[0] in org)

    held = defaultdict(set)
    for c in certs:
        held[c["employee_id"]].add(c["vendor"])
    target_set = set(valid)
    holders_not_target = sum(1 for e, vs in held.items() for v in vs if (e, v) not in target_set)

    vendors = sorted({v for _, v in valid})
    by_vendor = {}
    for v in vendors:
        t = [e for e, vv in valid if vv == v]
        a = sum(1 for e in t if v in held.get(e, set()))
        by_vendor[v] = {"target": len(t), "achieved": a, "not_achieved": len(t) - a, "rate": _rate(a, len(t))}
    total_t = sum(x["target"] for x in by_vendor.values())
    total_a = sum(x["achieved"] for x in by_vendor.values())

    per_person = defaultdict(list)
    for e, v in valid:
        per_person[e].append(v in held.get(e, set()))
    persons = len(per_person)
    all_done = sum(1 for xs in per_person.values() if all(xs))
    none_done = sum(1 for xs in per_person.values() if not any(xs))

    def by_org(keys: tuple[str, ...]) -> list[dict]:
        cell = defaultdict(lambda: {v: [0, 0] for v in vendors})
        people = defaultdict(set)
        for e, v in valid:
            k = tuple(org[e][x] for x in keys)
            cell[k][v][0] += 1
            cell[k][v][1] += v in held.get(e, set())
            people[k].add(e)
        rows = []
        for k in sorted(cell):
            t = sum(x[0] for x in cell[k].values())
            a = sum(x[1] for x in cell[k].values())
            rows.append({"org": list(k), "people": len(people[k]), "target": t, "achieved": a, "rate": _rate(a, t),
                         "vendors": {v: {"target": cell[k][v][0], "achieved": cell[k][v][1]} for v in vendors}})
        return rows

    return {
        "vendors": vendors,
        "by_vendor": by_vendor,
        "total": {"target": total_t, "achieved": total_a, "not_achieved": total_t - total_a, "rate": _rate(total_a, total_t)},
        "by_person": {"people": persons, "all": all_done, "partial": persons - all_done - none_done, "none": none_done,
                      "multi_vendor": sum(1 for xs in per_person.values() if len(xs) >= 2)},
        "by_division": by_org(("division",)),
        "by_team": by_org(("division", "team")),
        "by_group": by_org(("division", "team", "group")),
        "checks": {"unknown_employee_ids": len(unknown_ids), "duplicate_rows": duplicate_rows,
                   "holders_not_target": holders_not_target},
    }
