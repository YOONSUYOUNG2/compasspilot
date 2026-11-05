# CompassPilot 구조

> 기준 커밋: T17 (2026-11-05). 2절은 `app.get_graph().draw_mermaid()`가 자동으로 만든 그래프이고, 1절은 그 앞뒤의 가드레일·후처리·데이터를 포함한 전체 흐름이다.

## 1. 전체 흐름

```mermaid
flowchart TD
    U["사용자 질문<br/>python -m src.main --user &lt;id&gt;"] --> G{"입력 가드레일<br/>① 정규식 ② Haiku 판별(확신도 &gt; 0.7)"}
    G -- 주입 --> R1["고정 문구 거절<br/>Sorry, I can't process that request."]
    G -- 정상 --> S["Supervisor<br/>(Sonnet 4.5, langgraph-supervisor)"]

    S --> A["assessment_agent<br/>요구사항 검색"]
    S --> C["competency_agent<br/>버전 비교·난이도·산출물"]
    S --> W["workforce_agent<br/>임직원 자격"]
    S --> N["general_agent<br/>인사·기능 안내"]

    A --> T1["search_requirements<br/>(로컬 도구, RAG)"]
    T1 --> V[("Chroma<br/>Requirement 1개 = 1청크<br/>Titan v2 임베딩")]

    C --> MCP["MCP 서버 (FastMCP, stdio)"]
    MCP --> T2["diff_versions"]
    MCP --> T3["assess_difficulty"]
    MCP --> T4["list_deliverables"]
    T2 --> P[("data/derived<br/>버전별 파싱 결과")]
    T3 --> RD[("data/sample/readiness.csv")]
    T4 --> D[("data/derived/deliverables.json<br/>색인 때 1회 LLM 추출")]

    W --> T5["count_certifications<br/>get_certification_details"]
    T5 --> O[("data/sample<br/>org_users.json · certifications.csv")]
    T5 -. "권한: RunnableConfig의 user_id로 판정<br/>(질문 내용·LLM 인자로 정하지 않음)" .- O

    S --> F["최종 답 (영문 + ### 한국어 번역)"]
    F --> PP["후처리 (파이썬 규칙)<br/>· repair_reason → format_report<br/>· [내부 메모] 근거 없으면 삭제<br/>· '문서에 없음' 고정 문구 보정<br/>· staff 답변 이름 마스킹"]
    PP --> OUT["화면 출력"]
    PP -- "질문에 '보고서'" --> REP["src/report.py<br/>도구 결과로 부록 표 + 집계<br/>reports/날짜_주제_en.md / _ko.md"]

    S -. 모든 단계 .-> TR[("trace.jsonl<br/>FileTracer, 기록 직전 이름 마스킹")]

    X["Assessment Excel<br/>data/private/versions/*.xlsx"] --> IDX["python -m src.rag.index<br/>zipfile+xml 파싱 → 색인 → 산출물 추출"]
    IDX --> P
    IDX --> V
    IDX --> D
    P --> DB["python -m src.dashboard<br/>reports/dashboard.html (LLM 호출 없음)"]
```

| 구분 | 역할 | 판정 주체 |
|---|---|---|
| 입력 가드레일 | 프롬프트 주입 차단 | 정규식 + Haiku 4.5 |
| Supervisor | 질문 라우팅, 최종 답 작성(영문 + 한국어 번역) | Sonnet 4.5 |
| `search_requirements` | Requirement 원문 검색, `[ID: XXX-000]` 출처 | Chroma 유사도 |
| `diff_versions` | 버전 비교(추가·삭제·실질·경미·안내문) | 파이썬 규칙 |
| `assess_difficulty` | 난이도 상/중/하와 점수 근거 | 파이썬 규칙 |
| `list_deliverables` | 산출물과 고객 사례 체크리스트, 집계 | 미리 추출한 파일 + 파이썬 집계 |
| `count_certifications`·`get_certification_details` | 자격 집계(누구나), 명단(권한별) | 파이썬 규칙 |
| 후처리 | 최종 답 검증·메모 삭제·고정 문구·마스킹·보고서 부록 | 파이썬 규칙 (번역·형식만 LLM) |
| 대시보드 | 버전·난이도·산출물·자격 집계·평가 결과 | 파이썬(LLM 없음) |

## 2. LangGraph 그래프 (자동 생성)

`app.get_graph().draw_mermaid()` 출력 그대로다. 점선은 Supervisor의 조건부 이동(handoff), 실선은 하위 에이전트가 Supervisor로 돌아가는 경로다.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	supervisor(supervisor)
	assessment_agent(assessment_agent)
	competency_agent(competency_agent)
	workforce_agent(workforce_agent)
	general_agent(general_agent)
	__end__([<p>__end__</p>]):::last
	__start__ --> supervisor;
	assessment_agent --> supervisor;
	competency_agent --> supervisor;
	general_agent --> supervisor;
	supervisor -.-> __end__;
	supervisor -.-> assessment_agent;
	supervisor -.-> competency_agent;
	supervisor -.-> general_agent;
	supervisor -.-> workforce_agent;
	workforce_agent --> supervisor;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

각 하위 에이전트는 `create_react_agent`로 만든 `agent ⇄ tools` 반복 그래프다(general_agent는 도구 없음).

다시 만들기:

```powershell
.venv\Scripts\python.exe -c "import asyncio; from src.agents import build_app; print(asyncio.run(build_app()).get_graph().draw_mermaid())"
```

## 3. 모델

| 용도 | 모델 · 리전 |
|---|---|
| Supervisor·하위 에이전트·산출물 추출 | Sonnet 4.5 (us-west-2), 대체: us-east-1 → global → Sonnet 4.6 |
| 입력 가드레일 | Haiku 4.5 (us-east-1, 대체 us-west-2) |
| 평가 judge | Sonnet 4.5 (us-west-2), 대체 없음 |
| 임베딩 | Titan Text Embeddings v2 (us-east-1) |
