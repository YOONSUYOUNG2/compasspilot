"""2023 심사 제출본 재활용 매트릭스 (대시보드 전용, 파이썬 규칙, LLM 미사용).

입력 (모두 data/private/cases/, git 제외, 읽기만 한다)
- 2023 실제 심사 제출 Excel 1개: 옛 Migration Competency 양식. 회사 차원 시트는 응답 1건,
  고객 사례 시트는 "Customer Reference #1~4"마다 Met? / Partner Response / Evidence 칸이 있다.
- mapping_2023_2026.csv: 2026 항목 ↔ 2023 항목 대응표(사람이 원문을 읽고 확인). 열: id_2026, level, ids_2023, basis

규칙 (SERVICE.md 3절)
- ID 체계가 다르고 같은 ID가 다른 뜻인 경우가 있어 ID로 맞추지 않는다. 대응표만 쓴다.
- 칸 판정: 대응 항목이 그 사례에서 모두 Yes면 same → reuse, partial → adapt. 대응이 없거나 Yes가 아니면 new.
- 회사 차원 2023 항목은 사례 구분이 없으므로 네 사례 모두에 같은 응답으로 본다.
- 고객사명·응답 본문·증빙 파일명은 돌려주지 않는다. 증빙은 파일 개수만 센다.

실행: python -m src.assessment.cases
"""
import csv
import re
import sys

from src import config
from src.assessment import parser

CASES_DIR = config.PRIVATE_DIR / "cases"
MAPPING_CSV = CASES_DIR / "mapping_2023_2026.csv"
ID_RE = re.compile(r"^[A-Z]+-\d{3}$")
FILE_RE = re.compile(r"\.(pptx?|xlsx?|docx?|pdf|png|jpe?g|zip|txt|csv|hwp|vsdx?|md)\b", re.I)
LEVELS = ("same", "partial", "none")
REUSE, ADAPT, NEW = "reuse", "adapt", "new"
CELL_KO = {REUSE: "재활용", ADAPT: "보완 후 재활용", NEW: "새로 준비"}
CASES_TOTAL = 4


def case_file(folder=CASES_DIR):
    """제출본 Excel 경로(임시 파일 제외). 없으면 None, 두 개 이상이면 오류."""
    files = parser.excel_files(folder) if folder.exists() else []
    if len(files) > 1:
        raise ValueError(f"{folder}에 제출본 Excel이 {len(files)}개 있습니다(1개만 두세요)")
    return files[0] if files else None


def evidence_count(text: str) -> int:
    """증빙 칸에 적힌 파일 개수(확장자 기준). 같은 파일을 다른 항목과 함께 쓴다는 메모도 파일명이 있으면 센다."""
    return len(FILE_RE.findall(text or ""))


def _case_columns(rows) -> tuple[int, int, list[tuple[int, int]]]:
    """헤더 이름으로 (헤더 행 번호, ID 열, [(Met? 열, Evidence 열), ...])를 찾는다. 컬럼 위치는 쓰지 않는다."""
    for idx, (_, cells) in enumerate(rows):
        id_col = next((c for c, v in cells.items() if v.strip() == "ID"), None)
        if id_col is None:
            continue
        head = {}  # 열 → 이름 (헤더 행과 바로 아래 행을 합친다: 고객 사례 시트는 두 줄 헤더)
        for _, cs in rows[idx: idx + 2]:
            for c, v in cs.items():
                head.setdefault(c, v.strip())
                if v.strip() in ("Met?", "Evidence"):
                    head[c] = v.strip()
        mets = sorted(c for c, v in head.items() if v == "Met?")
        evs = sorted(c for c, v in head.items() if v == "Evidence")
        pairs = [(m, next((e for e in evs if e > m), None)) for m in mets]
        if not pairs:
            raise ValueError("Met? 열을 찾지 못했습니다")
        return idx, id_col, pairs
    raise ValueError("ID 헤더 행을 찾지 못했습니다")


def load_submission(path) -> dict:
    """제출본 → {"items": {ID: {"title", "scope", "cases": [{"met": bool, "evidence": int}] * 4}}, "version": 제목 줄}."""
    sheets = parser.read_xlsx(path)
    intro = next(iter(sheets.get("Introduction", [])), (0, {}))[1]
    version = " ".join((next(iter(intro.values()), "")).split("\n")[:3]).strip()
    items = {}
    for name, rows in sheets.items():
        if name == "Introduction":
            continue
        start, id_col, pairs = _case_columns(rows)
        for _, cells in rows[start + 1:]:
            rid = cells.get(id_col, "").strip()
            if not ID_RE.match(rid):
                continue
            title = (cells.get(id_col + 1, "").strip().split("\n") or [""])[0].strip()
            cases = [{"met": cells.get(m, "").strip().lower() == "yes",
                      "evidence": evidence_count(cells.get(e, "")) if e else 0} for m, e in pairs]
            if len(cases) == 1:  # 회사 차원: 네 사례에 같은 응답
                scope, cases = "company", cases * CASES_TOTAL
            else:
                scope = "customer_example"
            if rid in items:
                raise ValueError(f"제출본에 같은 ID가 두 번 있습니다: {rid}")
            items[rid] = {"title": title, "scope": scope, "cases": cases}
    return {"version": version, "items": items}


def load_mapping(path=MAPPING_CSV) -> dict[str, dict]:
    """대응표 → {2026 ID: {"level", "ids_2023": [...], "basis"}}. 값 검사를 한다."""
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rid, level = row["id_2026"].strip(), row["level"].strip()
            ids = [i.strip() for i in (row.get("ids_2023") or "").split(";") if i.strip()]
            if level not in LEVELS:
                raise ValueError(f"{rid}: 대응 수준은 {LEVELS} 중 하나여야 함 ({level})")
            if (level == "none") != (not ids):
                raise ValueError(f"{rid}: none이면 2023 ID가 없어야 하고, 그 외에는 있어야 함")
            out[rid] = {"level": level, "ids_2023": ids, "basis": (row.get("basis") or "").strip()}
    return out


def cell(level: str, ids_2023: list[str], items: dict, k: int) -> dict:
    """2026 항목 하나 × 사례 k의 판정."""
    found = [items[i]["cases"][k] for i in ids_2023 if i in items]
    if level == "none" or not found or len(found) < len(ids_2023) or not all(c["met"] for c in found):
        return {"status": NEW, "evidence": sum(c["evidence"] for c in found)}
    return {"status": REUSE if level == "same" else ADAPT, "evidence": sum(c["evidence"] for c in found)}


def matrix(requirements: list[dict], submission: dict, mapping: dict) -> dict:
    """2026 Requirement 목록 × 사례 1~4 매트릭스와 집계. 대응표에 없는 2026 항목은 오류로 알린다."""
    missing = [r["id"] for r in requirements if r["id"] not in mapping]
    unknown = sorted({i for m in mapping.values() for i in m["ids_2023"]} - set(submission["items"]))
    if missing or unknown:
        raise ValueError(f"대응표 점검: 2026 항목 누락 {missing}, 제출본에 없는 2023 ID {unknown}")
    rows = []
    for r in requirements:
        m = mapping[r["id"]]
        cells = [cell(m["level"], m["ids_2023"], submission["items"], k) for k in range(CASES_TOTAL)]
        rows.append({"id": r["id"], "title": r["title"], "scope": r["scope"], "level": m["level"],
                     "ids_2023": m["ids_2023"], "basis": m["basis"], "cells": cells})
    used = {i for m in mapping.values() for i in m["ids_2023"]}
    by_case = [{s: sum(row["cells"][k]["status"] == s for row in rows) for s in (REUSE, ADAPT, NEW)}
               for k in range(CASES_TOTAL)]
    return {
        "version_2023": submission["version"],
        "counts": {lv: sum(row["level"] == lv for row in rows) for lv in LEVELS},
        "by_case": by_case,
        "submission": {"items": len(submission["items"]),
                       "customer_items": sum(i["scope"] == "customer_example" for i in submission["items"].values()),
                       "met_cells": sum(c["met"] for i in submission["items"].values() if i["scope"] == "customer_example"
                                        for c in i["cases"]),
                       "unused_2023": sorted(set(submission["items"]) - used)},
        # ID만 같고 내용이 다른 항목: 옛 자료를 ID로 찾으면 틀린다
        "same_id_diff": [{"id": row["id"], "ids_2023": row["ids_2023"]} for row in rows
                         if row["id"] in submission["items"] and row["id"] not in row["ids_2023"]],
        "rows": rows,
    }


def build(version: str | None = None) -> dict | None:
    """등록된 2026(기본: 최신) 버전 기준 매트릭스. 제출본이 없으면 None."""
    path = case_file()
    if path is None:
        return None
    return matrix(parser.load(version)["requirements"], load_submission(path), load_mapping())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = build()
    if r is None:
        print("제출본 없음 (data/private/cases/)")
        sys.exit()
    print(r["version_2023"], r["counts"], r["submission"])
    for k, c in enumerate(r["by_case"], 1):
        print(f"사례 {k}: {c}")
    for row in r["rows"]:
        print(f"{row['id']:<10} {row['level']:<8} {','.join(row['ids_2023']):<28} "
              + " ".join(f"{CELL_KO[c['status']]}({c['evidence']})" for c in row["cells"]))
