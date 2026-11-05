"""두 Assessment 버전 비교 (파이썬 규칙, LLM 미사용).

판정 순서 (CLAUDE.md 5.3):
  1) 원문이 완전히 같음                          → unchanged
  2) 소문자·문장부호 제거·공백 정리 후 같음      → minor_notation (표기)
  3) 단어 단위로 철자가 비슷한 단어 치환만 있음  → minor_typo (오타)
  4) 그 외                                        → substantive (실질 변경)
시트 상단 안내문도 같은 규칙으로 비교한다.

실행: python -m src.assessment.diff [이전 버전] [새 버전]   (생략 시 직전 vs 최신)
"""
import difflib
import json
import re
import sys

from src.assessment import parser

UNCHANGED = "unchanged"
MINOR_NOTATION = "minor_notation"
MINOR_TYPO = "minor_typo"
SUBSTANTIVE = "substantive"

# 오타로 볼 단어 유사도 기준 (예: Recoverty ↔ Recovery = 0.94)
TYPO_SIMILARITY = 0.8


def normalize(text: str) -> str:
    """소문자 + 문장부호 제거 + 공백 정리."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(text.split())


def _word_ops(old: str, new: str):
    """정규화한 단어 목록 기준으로 바뀐 구간(opcode)을 돌려준다."""
    a, b = normalize(old).split(), normalize(new).split()
    ops = [op for op in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes() if op[0] != "equal"]
    return a, b, ops


def classify(old: str, new: str) -> str:
    """두 원문의 변경 종류를 판정한다."""
    if old == new:
        return UNCHANGED
    if normalize(old) == normalize(new):
        return MINOR_NOTATION
    a, b, ops = _word_ops(old, new)
    for tag, i1, i2, j1, j2 in ops:
        # 단어 수가 같은 치환이고, 각 단어 쌍의 철자가 비슷해야 오타로 본다
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            return SUBSTANTIVE
        for wa, wb in zip(a[i1:i2], b[j1:j2]):
            if difflib.SequenceMatcher(a=wa, b=wb).ratio() < TYPO_SIMILARITY:
                return SUBSTANTIVE
    return MINOR_TYPO


def changed_phrases(old: str, new: str, limit: int = 5) -> list[dict]:
    """바뀐 구간을 사람이 읽을 수 있게 정리한다(정규화한 단어 기준, 최대 limit개)."""
    a, b, ops = _word_ops(old, new)
    return [{"old": " ".join(a[i1:i2]), "new": " ".join(b[j1:j2])}
            for _, i1, i2, j1, j2 in ops[:limit]]


def _brief(req: dict) -> dict:
    return {"id": req["id"], "title": req["title"], "sheet": req["sheet"],
            "internal_note": req.get("internal_note")}


def diff_versions(old_label: str | None = None, new_label: str | None = None) -> dict:
    """두 버전을 비교한다. 생략하면 최신 버전과 그 직전 버전을 비교한다."""
    new_label = new_label or parser.latest_version()
    old_label = old_label or parser.previous_version(new_label)
    if old_label is None:
        raise ValueError(f"{new_label}보다 이전 버전이 없어 비교할 수 없습니다")
    old, new = parser.load(old_label), parser.load(new_label)
    return compare(old, new)


def compare(old: dict, new: dict) -> dict:
    """파싱 결과 두 개를 비교한다(파일 없이 테스트할 수 있도록 분리)."""
    old_reqs = {r["id"]: r for r in old["requirements"]}
    new_reqs = {r["id"]: r for r in new["requirements"]}

    added = [_brief(r) for rid, r in new_reqs.items() if rid not in old_reqs]
    removed = [_brief(r) for rid, r in old_reqs.items() if rid not in new_reqs]
    changed, unchanged = [], 0
    for rid, nr in new_reqs.items():
        if rid not in old_reqs:
            continue
        kind = classify(old_reqs[rid]["text"], nr["text"])
        if kind == UNCHANGED:
            unchanged += 1
            continue
        changed.append({**_brief(nr), "change_type": kind,
                        "changes": changed_phrases(old_reqs[rid]["text"], nr["text"]),
                        "old_text": old_reqs[rid]["text"], "new_text": nr["text"]})

    sheet_notes = []
    for sheet, new_note in new["sheet_notes"].items():
        old_note = old["sheet_notes"].get(sheet)
        if old_note is None:
            sheet_notes.append({"sheet": sheet, "change_type": "added", "old": None, "new": new_note})
            continue
        kind = classify(old_note, new_note)
        if kind != UNCHANGED:
            sheet_notes.append({"sheet": sheet, "change_type": kind, "old": old_note, "new": new_note,
                                "changes": changed_phrases(old_note, new_note)})

    return {
        "from_version": old["version"]["label"],
        "to_version": new["version"]["label"],
        "counts": {
            "old_total": len(old_reqs), "new_total": len(new_reqs),
            "added": len(added), "removed": len(removed),
            "substantive": sum(c["change_type"] == SUBSTANTIVE for c in changed),
            "minor": sum(c["change_type"] != SUBSTANTIVE for c in changed),
            "sheet_notes_changed": len(sheet_notes), "unchanged": unchanged,
        },
        "added": added,
        "removed": removed,
        "changed": changed,
        "sheet_notes_changed": sheet_notes,
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    result = diff_versions(*(args + [None] * (2 - len(args))))
    print(f"{result['from_version']} → {result['to_version']}: {json.dumps(result['counts'], ensure_ascii=False)}")
    print("added:", [a["id"] for a in result["added"]])
    print("removed:", [r["id"] for r in result["removed"]])
    for c in result["changed"]:
        print(f"changed: {c['id']} [{c['change_type']}] {c['changes'][:2]}")
    for s in result["sheet_notes_changed"]:
        print(f"sheet note: {s['sheet']} [{s['change_type']}] {str(s.get('changes', ''))[:150]}")
