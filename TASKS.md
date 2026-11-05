# TASKS · CompassPilot

> 기준: [SERVICE.md](SERVICE.md)(무엇을), [CLAUDE.md](CLAUDE.md)(어떻게). 한 번에 한 작업. 끝나면 [x] 체크 → 사용자 확인 → 커밋 `[T번호] 요약`.
> 마감 11/6 14:00. 11/6 12:30에는 무조건 개발을 멈추고 T18(제출 준비)으로 간다.

## 1단계 (필수) — 목표: 11/5 저녁 (오늘: 에이전트·도구·RAG·가드레일·트레이스, 평가 라운드)

- [x] **T1 환경**: requirements.txt(버전 고정), venv, `src/config.py`, `src/llm.py`(대체 모델 포함) (1h)
  - 확인: `python -m src.llm` → Sonnet 응답 1줄 + Titan 임베딩 차원(1024) 출력. Python 3.14에서 설치가 실패하면 사용자에게 3.12 설치 여부 확인
- [x] **T2 Excel 파서** + 버전 등록(`data/private/versions/`) + 테스트 (1h)
  - 확인: unittest 통과 — 2025-08 판 47개·2026-08 판 55개, Validity Period로 버전 구분, 같은 버전 중복 거절, internal_note 분리
- [x] **T3 버전 비교** `diff.py`(두 버전 지정, 기본 최신 vs 직전) + 테스트 (1h)
  - 확인: unittest가 SERVICE.md 5.1 정답표(2025-08 → 2026-08)와 100% 일치 (S2)
- [x] **T4 Chroma 색인** + `search_requirements` (1h)
  - 확인: `python -m src.rag.index` 후 평가 1~9번 질문 검색 시 상위 결과에 기대 ID 8개 이상 (S3 사전 점검)
- [x] **T5 MCP 서버** (`diff_versions`) (0.5h)
  - 확인: MCP 클라이언트로 도구 목록 조회·호출 → 추가 8건 확인
- [x] **T6 Supervisor** + 하위 에이전트 3개 + CLI (1h)
  - 확인: `python -m src.main "이번 버전에서 새로 추가된 요구사항 알려줘"` → 영문 답변 + `### 한국어 번역`, 8개 ID 포함 (S1)
- [x] **T7 입력 가드레일** + FileTracer (1h)
  - 확인: 주입 문장 → `Sorry, I can't process that request.`, 정상 질문 통과, `trace.jsonl` 기록
- [x] **T8 평가셋** 1단계 20문항(참조 답변 포함) + `run_eval.py` 수정 (1h)
  - 확인: `python -m evaluation.run_eval --round 0` → 규칙 판정 결과가 담긴 `eval_result_round0.json` 생성 (시험 실행)
- [x] **T9 LLM judge + RAGAS 지표** `evaluation/judge.py` + 라운드 보고서 자동 생성 (1h)
  - 확인: 문항 2~3개로 judge 점수와 RAGAS 4개 지표(0~1)가 나오고 `round0_report.md` 생성
- [x] **T10 라운드 1 평가** (0.5h)
  - 확인: `evaluation/round1_report.md`에 유형별 통과율, S1~S11 충족 여부, RAGAS 평균, 실패 원인, 개선 계획 기록
- [x] **T11 개선 → 라운드 2 평가** (1h)
  - 확인: `evaluation/round2_report.md`에서 라운드 1 대비 변화 기록. 기능 13/16 이상, 안전 4/4, no_answer 지어낸 답 0건, faithfulness 0.8 이상 (S4~S6, S11)

## 2단계 (시간 되는 대로, 순서대로) — 목표: 11/6 12:30까지

- [x] **T12 ① 권한 도구**: 가상 조직·자격 데이터(초안 사용자 확인) + 조회·집계 도구 + 테스트 (1h)
  - 확인: unittest — 권한·소속별 명단 정답 100%, 범위 밖 거절 (S7)
- [x] **T13 ① 연결·마스킹**: `workforce_agent` 연결 + 이름 마스킹(답변·trace) + 평가 21~27번 추가 (1h)
  - 확인: unittest + trace 검색에서 staff 이름 0건 (S8), 평가 재실행(다음 라운드 보고서)
- [x] **T14 ② HTML 대시보드**(버전 드롭다운 포함) + 테스트 (1.5h)
  - 확인: `python -m src.dashboard` → `reports/dashboard.html`이 브라우저에서 열림, 변경 건수 정답 일치·이름 0건 (S10)
- [x] **T15 ③ 난이도**: 준비 상태 가상 데이터 + `assess_difficulty` + 테스트 + 평가 28~29번 (1h)
  - 확인: unittest 규칙 100% 일치 (S9). 대시보드 난이도 칸 추가
  - 메모(11/5 13:10): Sonnet 하루 토큰 한도 소진(us-west-2·us-east-1·4.6, global도 간헐 실패)으로 28~29번 에이전트 실행은 한도가 풀린 뒤(11/6 오전) 라운드 평가에서 함께 돌린다
- [ ] **T16 ④ 산출물**: 추출 + `list_deliverables` + 평가 30~31번 (1h)
  - 확인: `data/derived/deliverables.json` 생성, "MOB-004에 필요한 산출물 알려줘" 응답
- [ ] **T17 ⑤ 보고서** 저장 + 평가 32번 (0.5h)
  - 확인: `reports/*_en.md`, `*_ko.md` 생성, 영문본에 내부 메모 없음

## 제출 준비 — 11/6 12:30 시작

- [ ] **T18 제출**: 최종 라운드 평가·보고서, `evaluation/unittest_log.txt`, `docs/architecture.md`(Mermaid), 대시보드 갱신, GitHub 저장소 생성 → 올릴 파일 목록 확인 → push, 패들릿 제출
  - 확인: 저장소에 `.env`·`data/private`·`ref` 없음, 최종 라운드 보고서가 SERVICE.md 기준(S4~S6, S11) 충족
