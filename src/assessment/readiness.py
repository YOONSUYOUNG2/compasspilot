"""준비 상태 로드·환산 (2단계 ③, CLAUDE.md 5.3).

입력: data/sample/readiness.csv (가상 데이터)
  requirement_id, status(회사 차원 항목: 준비완료/일부/미준비), cases_met(고객 사례 항목: 충족 건수 0~4)

환산 규칙 (파이썬)
- 회사 차원 항목: status를 그대로 쓴다.
- 고객 사례 항목: 충족 건수 4 = 준비완료, 1~3 = 일부, 0 = 미준비.
- 파일에 없는 항목은 미준비다.
"""
import csv

from src import config

READINESS_CSV = config.SAMPLE_DIR / "readiness.csv"

READY, PARTIAL, NOT_READY = "ready", "partial", "not_ready"
STATUS_KO = {"준비완료": READY, "일부": PARTIAL, "미준비": NOT_READY}
LABEL_KO = {READY: "준비완료", PARTIAL: "일부", NOT_READY: "미준비"}
CASES_TOTAL = 4  # 고객 사례 항목은 사례 4건마다 응답한다


def load_readiness(path=READINESS_CSV) -> dict[str, dict]:
    """ID → {"status": 원문 상태 또는 "", "cases_met": int 또는 None}. 파일이 없으면 빈 dict(모두 미준비)."""
    if not path.exists():
        return {}
    table = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rid = row["requirement_id"].strip()
            status = (row.get("status") or "").strip()
            cases = (row.get("cases_met") or "").strip()
            if status and status not in STATUS_KO:
                raise ValueError(f"{rid}: 알 수 없는 준비 상태 '{status}' (준비완료/일부/미준비)")
            cases_met = int(cases) if cases else None
            if cases_met is not None and not 0 <= cases_met <= CASES_TOTAL:
                raise ValueError(f"{rid}: 충족 건수는 0~{CASES_TOTAL}이어야 함 ({cases_met})")
            table[rid] = {"status": status, "cases_met": cases_met}
    return table


def cases_to_status(cases_met: int) -> str:
    """고객 사례 충족 건수를 준비 상태로 환산한다."""
    if cases_met >= CASES_TOTAL:
        return READY
    return PARTIAL if cases_met >= 1 else NOT_READY


def readiness_of(req: dict, table: dict) -> dict:
    """Requirement 하나의 준비 상태와 근거 문장(영문)을 돌려준다."""
    row = table.get(req["id"])
    if row is None:
        return {"status": NOT_READY, "basis": "not in readiness file (treated as not ready)"}
    if req["scope"] == "company":
        if not row["status"]:
            return {"status": NOT_READY, "basis": "no company-level status (treated as not ready)"}
        status = STATUS_KO[row["status"]]
        return {"status": status, "basis": f"company-level status: {status}"}
    cases = row["cases_met"] or 0
    return {"status": cases_to_status(cases), "basis": f"{cases}/{CASES_TOTAL} customer examples meet it"}
