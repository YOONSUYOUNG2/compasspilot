"""프로젝트 공통 상수: 경로, 모델 ID·리전, 고정 문구.

모델 ID와 리전은 이 파일에만 둔다(CLAUDE.md 2절). 다른 모듈은 여기서 가져다 쓴다.
"""
from pathlib import Path

from dotenv import load_dotenv

# ── 경로 (실행 위치와 무관하게 프로젝트 루트 기준) ──────────────────────────
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # AWS 키는 .env에서만 읽는다

DATA_DIR = ROOT / "data"
PRIVATE_DIR = DATA_DIR / "private"   # 실제 Assessment Excel (git 제외)
SAMPLE_DIR = DATA_DIR / "sample"     # 가상 데이터
DERIVED_DIR = DATA_DIR / "derived"   # 파싱·비교 결과 (git 제외, 재생성 가능)
CHROMA_DIR = ROOT / "chroma_db"
REPORTS_DIR = ROOT / "reports"
EVAL_DIR = ROOT / "evaluation"
TRACE_PATH = ROOT / "trace.jsonl"

# 버전별 Assessment Excel 폴더. 새 버전은 여기에 넣고 색인 명령을 실행한다.
# 버전 이름은 파일명이 아니라 Excel 안의 Validity Period로 정한다.
VERSIONS_DIR = PRIVATE_DIR / "versions"

# ── 모델 (CLAUDE.md 2절 표와 같아야 한다) ──────────────────────────────────
PRIMARY_REGION = "us-east-1"
TEMPERATURE = 0

SONNET_45_US = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
SONNET_45_GLOBAL = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
SONNET_46_US = "us.anthropic.claude-sonnet-4-6"
HAIKU_45_US = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
TITAN_EMBED = "amazon.titan-embed-text-v2:0"

# 기본 모델과 대체 순서: (모델 ID, 리전)
# 2026-11-05 us-east-1 Sonnet 4.5 하루 토큰 한도 소진 → 기본·judge를 us-west-2로 전환(같은 모델·파라미터)
CHAT_PRIMARY = (SONNET_45_US, "us-west-2")
CHAT_FALLBACKS = [
    (SONNET_45_US, "us-east-1"),        # 대체 1: 리전별 사용량 한도가 따로라 throttling 회피
    (SONNET_45_GLOBAL, "us-east-1"),    # 대체 2
    (SONNET_46_US, "us-east-1"),        # 대체 3
]
LIGHT_MODEL = (HAIKU_45_US, "us-east-1")           # 입력 가드레일 LLM 판별
LIGHT_FALLBACK = (HAIKU_45_US, "us-west-2")
JUDGE_MODEL = (SONNET_45_US, "us-west-2")          # 평가 심사: 고정, 대체 없음
EMBED_MODEL = (TITAN_EMBED, "us-east-1")

# ── 고정 문구 (evaluation/run_eval.py 판정 신호와 맞춘다) ────────────────────
INJECTION_REFUSAL = "Sorry, I can't process that request."
PERMISSION_REFUSAL = "You do not have permission to view this information."
NOT_IN_DOCUMENT = "This is not covered in the assessment."
