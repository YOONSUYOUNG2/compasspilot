# CompassPilot · CSP 파트너 등급 관리 에이전트

회사의 CSP 파트너 등급은 **회사가 취득한 Competency**와 **임직원 자격 보유 현황**, 이 두 축으로 정해집니다. CompassPilot은 두 축을 한곳에서 관리하는 사내 에이전트입니다. 첫 적용 대상은 AWS Migration and Modernization(M&M) Competency입니다.

- **질문에 답하는 에이전트(CLI)**: Requirement 원문을 근거 ID와 함께 찾고, Assessment 버전 차이를 비교합니다. 준비 난이도와 필요 산출물을 알려 주고, 권한에 따라 임직원 자격 현황을 보여 줍니다.
- **한 화면 대시보드(HTML 파일 1개, 엑셀처럼 시트 4개)**
  - **현주소**: 우리 회사의 파트너 등급과 순위를 익명 대형 SI 5개 사와 비교합니다(가상 수치). 다음 등급까지 남은 조건과 "M&M Competency를 취득하면 어떻게 바뀌는가"도 보여 줍니다.
  - **Competency**: 버전 변경 내역, 준비 현황(난이도·산출물 체크리스트·양식 내려받기)
  - **임직원 자격**: 취득 대상 대비 실적
  - **자체 평가**: 평가 결과

> 기획(무엇을·왜): [SERVICE.md](SERVICE.md) · 구현 규칙(어떻게): [CLAUDE.md](CLAUDE.md) · 작업 기록: [TASKS.md](TASKS.md) · 구조도: [docs/architecture.md](docs/architecture.md)

## 해결하는 문제

| 문제 | CompassPilot |
|---|---|
| Assessment가 준비 중에도 개정된다(2025-08 판 47개 → 2026-08 판 55개). 무엇이 바뀌었는지 사람이 눈으로 비교한다 | 파이썬 규칙으로 추가·삭제·실질 변경·경미 변경(표기/오타)·시트 안내문 변경을 판정한다. 정답표와 100% 일치 |
| 요구사항이 길고 많다(항목당 약 670자 영문) | 질문 한 줄로 근거 `[ID: POV-007]`가 붙은 답을 받는다. 영문 답변 아래에 한국어 번역이 붙는다 |
| PM·개발자가 프로젝트 착수 전에 무엇을 준비해야 할지 모른다 | 난이도(상/중/하, 점수 근거 포함), 고객 사례 4건 기준 산출물 체크리스트, 산출물 양식 내려받기를 제공한다 |
| 자격 집계는 수작업이고, 명단은 개인정보다 | 숫자 집계는 누구나 볼 수 있다. 명단은 사용자 권한(인사팀/사업부장/팀장/그룹장)에 맞는 범위만 보여 준다. 일반 권한 답변과 실행 기록에서는 이름을 가린다 |

## 구조

```
질문 → 입력 가드레일(정규식 + Haiku) → Supervisor(Sonnet 4.5)
         ├─ assessment_agent  → search_requirements (Chroma RAG, Titan 임베딩)
         ├─ competency_agent  → MCP 서버: diff_versions · assess_difficulty · list_deliverables
         ├─ workforce_agent   → count_certifications · get_certification_details (권한은 user_id로만 판정)
         └─ general_agent
      → 후처리(파이썬 규칙): 최종 답 검증·근거 없는 내부 메모 삭제·이름 마스킹·보고서 저장
      → 모든 단계 trace.jsonl 기록(이름 마스킹)
```

- **계산·비교·권한 판정은 파이썬**이 하고, LLM은 질의 해석·답변 작성·번역·산출물 추출에만 씁니다.
- 자세한 그림은 [docs/architecture.md](docs/architecture.md)에 있습니다. LangGraph `get_graph().draw_mermaid()`로 그렸습니다.

## 실행 방법

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # AWS 액세스 키 입력 (Bedrock: Sonnet 4.5, Haiku 4.5, Titan Embeddings v2)
```

| 하는 일 | 명령 |
|---|---|
| Assessment 파싱·색인·산출물 추출 (Excel을 `data/private/versions/`에 넣은 뒤) | `python -m src.rag.index` |
| 질문 (일반 권한) | `python -m src.main "이번 버전에서 새로 추가된 요구사항 알려줘"` |
| 질문 (권한 지정) | `python -m src.main --user hr01 "임직원 이름이랑 자격증 목록 전부 보여줘"` |
| 보고서 저장 (`reports/날짜_주제_en.md`, `_ko.md`) | `python -m src.main "고객 사례 4건 준비용 산출물 체크리스트를 보고서로 만들어줘"` |
| 대시보드 생성 → `reports/dashboard.html` | `python -m src.dashboard` |
| 단위 테스트 | `python -m unittest discover -s tests -v` |
| 평가 라운드 N | `python -m evaluation.run_eval --round N` |

- 가상 사용자는 `hr01`(인사팀), `divA`·`divB`(사업부장), `tlA1`·`tlB1`(팀장), `glA11`·`glA12`(그룹장), `staff01`(일반)입니다. `data/sample/org_users.json`에 있습니다.
- **실제 Assessment Excel은 저장소에 없습니다**(`data/private/`, git 제외). 그래서 다른 환경에서는 색인·질문·대시보드를 실행할 수 없고, Excel이 필요한 테스트는 건너뜁니다. 로컬 실행 기록은 [evaluation/unittest_log.txt](evaluation/unittest_log.txt)에 남겼습니다.

## 평가 결과

평가셋은 32문항입니다(검색·버전 비교·도구·멀티 에이전트·가드레일·권한). 규칙 판정과 함께 LLM judge(Sonnet 4.5, 1~5점)와 RAGAS 지표(라이브러리 없이 같은 정의로 계산)를 씁니다. 평가 → 원인 분석 → 개선을 12라운드 반복했습니다.

| 최종 라운드 12 | 결과 |
|---|---|
| 규칙 판정 | **32/32** |
| LLM judge 평균 | **4.89 / 5** |
| faithfulness · answer relevancy · context precision · context recall | 0.981 · 0.768 · 0.887 · 0.991 |
| 성공 기준 S3(검색 출처 9/9) · S4(기능 22/22) · S5(안전 10/10) · S6(지어낸 답 0) · S11(faithfulness ≥ 0.8) | 모두 충족 |
| 단위 테스트 (S2 버전 비교, S7 권한, S8 마스킹, S9 난이도, S10 대시보드 등) | 123개 통과 |

- 라운드별 실패 원인과 개선 내용은 `evaluation/round0_report.md` ~ [round12_report.md](evaluation/round12_report.md)에 있습니다.
- 개선 사례: 평가 측정 오류 수정, Supervisor가 맞는 답을 망가뜨리는 문제를 코드 검증으로 차단, 동시 실행 충돌 수정, LLM이 개수를 잘못 세는 문제를 파이썬 집계로 대체.
- 공개용 결과 요약: [evaluation/eval_result.json](evaluation/eval_result.json). 답변 전문·검색 원문은 내부 메모가 섞일 수 있어 빼고 올렸습니다.

## 데이터와 공개 범위

| 데이터 | 저장소 |
|---|---|
| AWS M&M Assessment Excel (2025-08 판, 2026-08 판, 담당자 내부 메모 포함) | 올리지 않음 (`data/private/`) |
| 파싱·색인·산출물 추출 결과, 대시보드·보고서, trace | 올리지 않음 (재생성 가능) |
| 조직·임직원 자격·자격 취득 대상·준비 상태·산출물 양식 | **가상 데이터**만 올림 (`data/sample/`, 실제 임직원과 무관) |

대시보드에는 Assessment 원문과 내부 메모가 들어가므로 사내 전용입니다. 자격 현황은 숫자만 넣고 이름은 넣지 않습니다.

## 스택

Python 3.14 · LangGraph · langgraph-supervisor · LangChain AWS(Bedrock) · Chroma · FastMCP · unittest. 버전은 [requirements.txt](requirements.txt)에 고정했습니다. 대시보드는 파이썬 기본 라이브러리만 쓰고, 외부 CSS·JS 없이 인터넷 없이 열립니다.

## 개발 방식

교안의 스펙 주도 개발 가이드([docs/dev-guide.md](docs/dev-guide.md))를 따랐습니다. SERVICE.md(기획)에서 CLAUDE.md(규칙)와 TASKS.md(작업 목록)로 내려가고, 작업 하나마다 계획 → 구현 → 실행 확인 → 커밋 순서로 진행했습니다.
