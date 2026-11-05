"""Assessment Excel → Requirement JSON (파이썬 기본 라이브러리만 사용).

- Excel(.xlsx)은 zip 안의 XML이므로 zipfile + xml.etree로 읽는다(openpyxl 미사용).
- 버전마다 컬럼 위치가 달라서, 'ID' 헤더 행을 찾아 헤더 이름으로 컬럼을 정한다.
- 담당자가 쓴 한글 메모(비고, 헤더 없는 칸, 한글 Partner Response)는 internal_note로 분리한다.

- 버전은 data/private/versions/의 Excel을 모두 읽어 Validity Period(예: 2026-08)로 구분한다.

실행: python -m src.assessment.parser  → data/derived/requirements_<버전>.json, versions.json
"""
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from src import config

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

ID_PATTERN = re.compile(r"^[A-Z]+-\d{3}$")
HANGUL = re.compile("[가-힣]")
VALIDITY = re.compile(r"Validity Period:\s*([A-Za-z]+)\s+(\d{4})\s*-\s*([A-Za-z]+)\s+(\d{4})")
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}

INTRO_SHEET = "Introduction"
COMPANY_SHEET = "Common Practice Requirements"  # 회사 차원(응답 1건)
# 나머지 시트는 고객 사례 4건마다 응답하는 항목이다.


# ── xlsx 저수준 읽기 ───────────────────────────────────────────────────────

def _col_index(cell_ref: str) -> int:
    """'C12' → 3 (1부터 시작하는 컬럼 번호)."""
    n = 0
    for ch in re.match(r"[A-Z]+", cell_ref).group():
        n = n * 26 + ord(ch) - 64
    return n


def read_xlsx(path: Path) -> dict[str, list[tuple[int, dict[int, str]]]]:
    """시트 이름 → [(행 번호, {컬럼 번호: 셀 문자열})] (빈 셀은 제외)."""
    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{_NS}si"):
                # 서식이 섞인 문자열(r/t)도 이어 붙인다. 발음 표기(rPh)는 제외한다.
                parts = [t.text or "" for t in si.iter(f"{_NS}t")
                         if t not in {x for ph in si.findall(f"{_NS}rPh") for x in ph.iter()}]
                shared.append("".join(parts))
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{_REL_NS}Relationship")}

        sheets = {}
        for sheet in workbook.find(f"{_NS}sheets"):
            target = targets[sheet.get(_R_ID)].lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            root = ET.fromstring(z.read(target))
            rows = []
            for row in root.iter(f"{_NS}row"):
                cells = {}
                for c in row.findall(f"{_NS}c"):
                    v = c.find(f"{_NS}v")
                    if c.get("t") == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif c.get("t") == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter(f"{_NS}t"))
                    else:
                        val = v.text if v is not None else None
                    if val is not None and val.strip():
                        cells[_col_index(c.get("r"))] = val
                if cells:
                    rows.append((int(row.get("r")), cells))
            sheets[sheet.get("name")] = rows
    return sheets


# ── Assessment 해석 ───────────────────────────────────────────────────────

def _parse_version(intro_rows) -> dict:
    """Introduction 시트의 Validity Period에서 버전 정보를 만든다."""
    text = "\n".join(v for _, cells in intro_rows for v in cells.values())
    m = VALIDITY.search(text)
    if not m:
        return {"label": "unknown", "validity_period": None}
    m1, y1, m2, y2 = m.groups()
    return {
        "label": f"{y1}-{MONTHS.get(m1, 0):02d}",  # 예: 2026-08
        "validity_period": f"{m1} {y1} - {m2} {y2}",
    }


def _find_header(rows) -> tuple[int, dict[str, int]]:
    """'ID'로 시작하는 헤더 행을 찾아 (행 번호, {헤더 이름: 컬럼})을 돌려준다."""
    for r, cells in rows:
        if cells.get(1, "").strip() == "ID":
            return r, {v.strip(): k for k, v in cells.items()}
    raise ValueError("ID 헤더 행을 찾지 못했습니다")


def _split_title(text: str) -> str:
    """설명 셀의 첫 줄이 제목이다."""
    return text.strip().splitlines()[0].strip()


def parse_sheet(name: str, rows) -> tuple[str, list[dict]]:
    """요구사항 시트 하나 → (시트 안내문, Requirement 목록)."""
    sheet_note = rows[0][1].get(1, "").strip() if rows else ""
    header_row, header = _find_header(rows)
    id_col = header["ID"]
    desc_col = header["Requirement Description"]
    # Met? 칸은 메모가 아니므로 제외한다. (고객 사례 시트는 헤더 아래 행에 Met?/Partner Response가 있다)
    met_cols = {k for r, cells in rows if header_row <= r <= header_row + 1
                for k, v in cells.items() if v.strip() == "Met?"}

    scope = "company" if name == COMPANY_SHEET else "customer_example"
    reqs, area, area_desc, prev_nonid_row = [], None, None, None
    for r, cells in rows:
        if r <= header_row + (0 if scope == "company" else 1):
            continue  # 안내문·헤더 행
        rid = cells.get(id_col, "").strip()
        if not ID_PATTERN.match(rid):
            text = " ".join(v.strip() for v in cells.values())
            if prev_nonid_row == r - 1:
                area_desc = text  # 영역 제목 바로 다음 줄 = 영역 설명
            else:
                area, area_desc = text, None
            prev_nonid_row = r
            continue
        text = cells.get(desc_col, "").strip()
        notes = [v.strip() for k, v in sorted(cells.items())
                 if k not in (id_col, desc_col) and k not in met_cols and HANGUL.search(v)]
        reqs.append({
            "id": rid,
            "title": _split_title(text),
            "text": text,
            "sheet": name,
            "scope": scope,
            "area": area,
            "area_description": area_desc,
            "internal_note": "\n".join(notes) or None,
        })
    return sheet_note, reqs


def parse_assessment(path: Path) -> dict:
    """Excel 한 개를 버전 정보·시트 안내문·Requirement 목록으로 변환한다."""
    sheets = read_xlsx(path)
    version = _parse_version(sheets.get(INTRO_SHEET, []))
    version["file"] = Path(path).name
    sheet_notes, requirements = {}, []
    for name, rows in sheets.items():
        if name == INTRO_SHEET:
            continue
        note, reqs = parse_sheet(name, rows)
        sheet_notes[name] = note
        for req in reqs:
            req["version"] = version["label"]
        requirements.extend(reqs)
    return {"version": version, "sheet_notes": sheet_notes, "requirements": requirements}


# ── 버전 등록·조회 ─────────────────────────────────────────────────────────

VERSIONS_INDEX = config.DERIVED_DIR / "versions.json"


def derived_path(label: str) -> Path:
    """버전별 파싱 결과 파일 경로 (예: requirements_2026-08.json)."""
    return config.DERIVED_DIR / f"requirements_{label}.json"


def excel_files(folder: Path = None) -> list[Path]:
    """버전 폴더의 Excel 목록 (임시 파일 ~$*.xlsx 제외)."""
    folder = folder or config.VERSIONS_DIR
    return sorted(p for p in folder.glob("*.xlsx") if not p.name.startswith("~$"))


def build_all(folder: Path = None) -> dict[str, dict]:
    """버전 폴더의 Excel을 모두 파싱해 data/derived/에 저장한다. 반환: {버전 이름: 파싱 결과} (오래된 순)."""
    parsed = {}
    for path in excel_files(folder):
        data = parse_assessment(path)
        label = data["version"]["label"]
        if label == "unknown":
            raise ValueError(f"Validity Period를 찾지 못했습니다: {path.name}")
        if label in parsed:
            raise ValueError(f"같은 버전({label})의 파일이 두 개입니다: "
                             f"{parsed[label]['version']['file']}, {path.name}")
        parsed[label] = data
    parsed = dict(sorted(parsed.items()))

    config.DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for label, data in parsed.items():
        derived_path(label).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        index.append({**data["version"], "requirements": len(data["requirements"])})
    VERSIONS_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return parsed


def list_versions() -> list[str]:
    """등록된 버전 이름 목록 (오래된 순). 파싱 결과가 없으면 새로 만든다."""
    if not VERSIONS_INDEX.exists():
        build_all()
    return [v["label"] for v in json.loads(VERSIONS_INDEX.read_text(encoding="utf-8"))]


def latest_version() -> str:
    return list_versions()[-1]


def previous_version(label: str) -> str | None:
    """바로 앞 버전 이름. 첫 버전이면 None."""
    versions = list_versions()
    i = versions.index(label)
    return versions[i - 1] if i > 0 else None


def load(label: str | None = None) -> dict:
    """버전별 파싱 결과를 읽는다. label이 없으면 최신 버전."""
    label = label or latest_version()
    if label not in list_versions():
        raise ValueError(f"등록되지 않은 버전입니다: {label} (등록: {', '.join(list_versions())})")
    p = derived_path(label)
    if not p.exists():
        build_all()
    return json.loads(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    for label, data in build_all().items():
        v = data["version"]
        n_note = sum(1 for r in data["requirements"] if r["internal_note"])
        print(f"{label} ({v['validity_period']}) requirements={len(data['requirements'])} "
              f"internal_note={n_note} file={v['file']}")
