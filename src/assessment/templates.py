"""산출물 양식 연결 (사용자 요청 추가). 산출물 ↔ 양식 연결은 파이썬 규칙으로 한다(LLM 없음).

입력: data/sample/templates/templates.csv  (가상 양식 목록)
  template_id, file, title, keywords(;로 구분), requirement_ids(;로 구분, 비우면 모든 요구사항)

연결 규칙
- 산출물 이름(소문자)에 키워드가 들어 있고, 요구사항 ID가 그 양식의 requirement_ids에 있으면 연결한다.
- 여러 양식이 맞으면 목록 파일에 먼저 적힌 양식 하나를 쓴다.
- 실제 사내 양식은 같은 형식의 목록 파일과 함께 data/private/에 두고 경로만 바꿔 쓴다(git 제외).
"""
import base64
import csv
import mimetypes

from src import config

TEMPLATES_DIR = config.SAMPLE_DIR / "templates"
MIME = {".md": "text/markdown;charset=utf-8", ".csv": "text/csv;charset=utf-8"}


def load_templates(folder=TEMPLATES_DIR) -> list[dict]:
    """양식 목록을 읽는다. 파일이 없으면 빈 목록. 목록에 있는데 파일이 없는 양식은 missing=True로 표시한다."""
    index = folder / "templates.csv"
    if not index.exists():
        return []
    with open(index, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        path = folder / r["file"].strip()
        out.append({"id": r["template_id"].strip(), "file": r["file"].strip(), "title": r["title"].strip(),
                    "keywords": [k.strip().lower() for k in r["keywords"].split(";") if k.strip()],
                    "requirement_ids": [i.strip().upper() for i in r["requirement_ids"].split(";") if i.strip()],
                    "path": path, "missing": not path.exists()})
    return out


def match(requirement_id: str, deliverable_name: str, templates: list[dict]) -> str | None:
    """산출물 하나에 맞는 양식 ID. 없으면 None."""
    name = deliverable_name.lower()
    for t in templates:
        if t["missing"]:
            continue
        if t["requirement_ids"] and requirement_id.upper() not in t["requirement_ids"]:
            continue
        if any(k in name for k in t["keywords"]):
            return t["id"]
    return None


def embedded(templates: list[dict]) -> dict:
    """대시보드 HTML에 넣을 양식 파일(base64). 파일 하나로 전달되도록 내용까지 넣는다."""
    out = {}
    for t in templates:
        if t["missing"]:
            continue
        mime = MIME.get(t["path"].suffix.lower()) or mimetypes.guess_type(t["file"])[0] or "application/octet-stream"
        out[t["id"]] = {"title": t["title"], "file": t["file"], "mime": mime,
                        "requirement_ids": t["requirement_ids"],
                        "b64": base64.b64encode(t["path"].read_bytes()).decode("ascii")}
    return out
