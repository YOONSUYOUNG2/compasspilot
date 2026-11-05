"""보고서 파일 저장 (2단계 ⑤, CLAUDE.md 5.5). 판별·파일명·분리는 모두 파이썬 규칙이다(LLM 호출 없음).

- 질문에 "보고서"/"report"가 있으면 보고서 요청으로 본다.
- 긴 목록(산출물 체크리스트, 난이도)은 LLM이 옮겨 쓰지 않고 도구 결과 JSON으로 코드가 부록 표를 만들어 붙인다
  (35개 항목을 LLM이 다시 쓰다 응답 시간 초과가 난 문제 대응). LLM 본문은 요약과 근거 [ID]만 쓴다.
- 최종 답(영문 + "### 한국어 번역")을 화면에 출력하고 두 파일로 저장한다.
    reports/<날짜>_<주제>_en.md : 영문 부분만. [내부 메모] 줄은 넣지 않는다(코드로 한 번 더 제거).
    reports/<날짜>_<주제>_ko.md : 한국어 번역 부분([내부 메모] 포함)
- 같은 날 같은 주제 파일이 있으면 _2, _3 … 을 붙여 덮어쓰지 않는다.
"""
import json
import re
import time
from pathlib import Path

from src import config

KO_SECTION = "### 한국어 번역"
NOTE_TAG = "[내부 메모]"
REPORT_WORDS = re.compile(r"보고서|report", re.I)
# 주제명에서 뺄 요청 단어(단어 전체가 일치할 때만)와 단어 끝 조사
REQUEST_WORDS = re.compile(r"(보고서\w*|리포트\w*|report\w*|만들어\w*|작성해\w*|정리해\w*|저장해\w*|알려\w*|해줘|"
                           r"주세요|please|make|create|write|a|the|as|및|함께)", re.I)
PARTICLE = re.compile(r"(으로|로|를|을|와|과|의|에|에서)$")
MAX_TOPIC = 40


def is_report_request(question: str) -> bool:
    return bool(REPORT_WORDS.search(question))


def topic_slug(question: str) -> str:
    """질문에서 요청 단어를 빼고 남은 단어로 파일명용 주제를 만든다."""
    words = []
    for w in re.findall(r"[0-9A-Za-z가-힣\-]+", question):
        if REQUEST_WORDS.fullmatch(w):
            continue
        if re.search(r"[가-힣]", w) and len(w) > 2:
            w = PARTICLE.sub("", w)
        words.append(w)
    slug = "_".join(words)[:MAX_TOPIC].strip("_-")
    return slug or "report"


def split_answer(answer: str) -> tuple[str, str]:
    """최종 답을 (영문, 한국어) 부분으로 나눈다. 영문 부분에서 [내부 메모] 줄은 지운다."""
    en, _, ko = answer.partition(KO_SECTION)
    en = "\n".join(line for line in en.splitlines() if NOTE_TAG not in line)
    en = re.sub(r"\n-{3,}\s*$", "", en.strip()).strip()
    return en, ko.strip()


def _cell(text) -> str:
    return str(text).replace("|", "/").replace("\n", " ").strip()


def _last_json(tool_outputs: list[tuple[str, str]], name: str) -> dict | None:
    """같은 도구를 여러 번 불렀으면 마지막 정상 결과를 쓴다."""
    for tool, out in reversed(tool_outputs):
        if tool == name:
            try:
                data = json.loads(out)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and "items" in data:
                return data
    return None


CASES_KO = {None: "회사 차원 (1회)", 4: "고객 사례 4건 모두"}
LEVEL_KO = {"high": "상", "medium": "중", "low": "하"}


def appendix(tool_outputs: list[tuple[str, str]]) -> tuple[str, str]:
    """도구 결과(JSON)로 부록 표를 만든다(영문, 한국어). 목록은 LLM이 옮겨 쓰지 않고 코드가 그대로 표로 만든다."""
    en, ko = [], []
    dl = _last_json(tool_outputs, "list_deliverables")
    if dl and dl["items"]:
        s = dl.get("summary") or {}
        en += [f"## Appendix: Deliverables checklist (version {dl['version']}, from list_deliverables)", ""]
        ko += [f"## 부록: 산출물 체크리스트 ({dl['version']} 판, list_deliverables 결과)", ""]
        if s:
            en += [f"Requirements: {s['requirements']} · Deliverables: {s['deliverables']} · Company-level: {s['company_level']} · "
                   f"All 4 customer examples: {s['customer_all_4']} · At least 2-3: {s['customer_at_least_2_or_3']} · "
                   f"At least 1: {s['customer_at_least_1']}", ""]
            ko += [f"요구사항 {s['requirements']}개 · 산출물 {s['deliverables']}개 · 회사 차원 {s['company_level']}개 · "
                   f"고객 사례 4건 모두 {s['customer_all_4']}개 · 2~3건 이상 {s['customer_at_least_2_or_3']}개 · "
                   f"1건 이상 {s['customer_at_least_1']}개", ""]
        en += ["| ID | Requirement | Prepare for | Deliverables |", "|---|---|---|---|"]
        ko += ["| ID | 요구사항 | 준비 범위 | 산출물 |", "|---|---|---|---|"]
        for i in dl["items"]:
            names = "<br>".join(f"☐ {_cell(d['name'])}" for d in i["deliverables"])
            n = i.get("customer_examples_required")
            en.append(f"| {i['id']} | {_cell(i['title'])} | {_cell(i['checklist'])} | {names} |")
            ko.append(f"| {i['id']} | {_cell(i['title'])} | {CASES_KO.get(n, f'고객 사례 4건 중 {n}건 이상')} | {names} |")
        en.append("")
        ko.append("")
    df = _last_json(tool_outputs, "assess_difficulty")
    if df and df["items"]:
        en += [f"## Appendix: Preparation difficulty (version {df['version']}, from assess_difficulty)", "",
               "| ID | Requirement | Level | Score | Reasons |", "|---|---|---|---|---|"]
        ko += [f"## 부록: 준비 난이도 ({df['version']} 판, assess_difficulty 결과)", "",
               "| ID | 요구사항 | 난이도 | 점수 | 근거 |", "|---|---|---|---|---|"]
        for i in sorted(df["items"], key=lambda x: (-x["score"], x["id"])):
            reasons = "<br>".join(_cell(r) for r in i["reasons"])
            en.append(f"| {i['id']} | {_cell(i['title'])} | {i['level']} | {i['score']} | {reasons} |")
            ko.append(f"| {i['id']} | {_cell(i['title'])} | {LEVEL_KO.get(i['level'], i['level'])} | {i['score']} | {reasons} |")
    return "\n".join(en).strip(), "\n".join(ko).strip()


def with_appendix(answer: str, tool_outputs: list[tuple[str, str]]) -> str:
    """최종 답의 영문 부분 끝과 한국어 부분 끝에 부록 표를 붙인다. 붙일 도구 결과가 없으면 그대로 둔다."""
    en_app, ko_app = appendix(tool_outputs)
    if not en_app:
        return answer
    en, sep, ko = answer.partition(KO_SECTION)
    en = re.sub(r"\n-{3,}\s*$", "", en.rstrip()).rstrip()
    if not sep:
        return f"{en}\n\n{en_app}"
    return f"{en}\n\n{en_app}\n\n{KO_SECTION}\n{ko.strip()}\n\n{ko_app}"


def _unique(path: Path) -> Path:
    n = 2
    candidate = path
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    return candidate


def save_report(question: str, answer: str, out_dir: Path = config.REPORTS_DIR, date: str | None = None) -> dict:
    """보고서를 영문·국문 두 파일로 저장하고 경로를 돌려준다."""
    date = date or time.strftime("%Y-%m-%d")
    base = f"{date}_{topic_slug(question)}"
    en, ko = split_answer(answer)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 같은 번호로 en/ko 짝을 맞춘다
    en_path = _unique(out_dir / f"{base}_en.md")
    suffix = en_path.stem[len(base) + len("_en"):]
    ko_path = out_dir / f"{base}_ko{suffix}.md" if suffix else out_dir / f"{base}_ko.md"
    if ko_path.exists():
        ko_path = _unique(ko_path)
    header = f"<!-- CompassPilot report · {date} · question: {question} -->\n\n"
    en_path.write_text(header + en + "\n", encoding="utf-8")
    ko_path.write_text(header + (ko or "(한국어 번역 없음)") + "\n", encoding="utf-8")
    return {"en": str(en_path), "ko": str(ko_path)}
