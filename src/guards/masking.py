"""임직원 이름 마스킹 (예: 김하늘 → 김*늘).

- 대상: 디렉터리(data/sample/org_users.json)에 있는 임직원 이름
- 적용: staff 답변(출력 직전), 모든 trace 기록(파일에 쓰기 직전) — CLAUDE.md 5.5
"""
import re
from functools import lru_cache

from src.workforce.directory import employee_names


def mask_name(name: str) -> str:
    """가운데 글자를 *로 가린다. 두 글자 이름은 뒤 글자를 가린다."""
    if len(name) <= 1:
        return "*"
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


@lru_cache(maxsize=1)
def _pattern() -> re.Pattern | None:
    names = sorted(set(employee_names()), key=len, reverse=True)  # 긴 이름부터 맞춘다
    return re.compile("|".join(map(re.escape, names))) if names else None


def mask_text(text: str) -> str:
    """텍스트 안의 임직원 이름을 모두 가린다."""
    p = _pattern()
    return p.sub(lambda m: mask_name(m.group(0)), text) if p and text else text
