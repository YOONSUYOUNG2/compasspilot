"""LLM judge (교안 llm_judge.py 방식) + RAGAS 지표 4개 직접 계산.

- judge 모델: Sonnet 4.5 고정, temperature 0, 대체 없음 (src/llm.get_judge_llm)
- ragas 패키지는 쓰지 않는다. 지표 정의는 RAGAS와 같다(SERVICE.md 5.3).
  faithfulness       답변의 주장 중 근거(context)로 뒷받침되는 비율
  answer_relevancy   답변에서 거꾸로 만든 질문과 원래 질문의 임베딩 코사인 유사도 평균
  context_precision  근거 조각별 관련 여부로 계산한 평균 정밀도(순위 반영)
  context_recall     참조 답변 문장 중 근거에 들어 있는 비율
- 답변은 영문 부분만 평가한다(### 한국어 번역 이후는 번역이므로 제외).
"""
import math
import re

from pydantic import BaseModel, Field

from src.llm import get_embeddings, get_judge_llm

KO_SECTION = "### 한국어 번역"
MAX_CONTEXT_CHARS = 12000  # judge 입력 길이 상한 (Bedrock 토큰 한도 throttling 방지)


# ── 루브릭 심사 (교안 llm_judge.py) ─────────────────────────────────────────

class JudgeResult(BaseModel):
    score: int = Field(ge=1, le=5)
    is_correct: bool = Field(description="의미가 참조 답변과 일치하는가")
    missing: list[str] = Field(default_factory=list, description="답변에 빠진 핵심")
    reasoning: str


RUBRIC = """Evaluate the model answer against the reference answer. Judge correctness, not length.
5: directly answers the question, includes the key facts of the reference accurately, no speculation
3: relevant but misses some key information or is verbose
1: does not answer the question or states wrong facts
Respond with reasoning in Korean."""


# ── RAGAS 지표용 구조화 출력 ────────────────────────────────────────────────

class Claim(BaseModel):
    claim: str
    supported: bool = Field(description="근거(context)만으로 이 주장을 뒷받침할 수 있는가")


class Claims(BaseModel):
    claims: list[Claim]


class ChunkVerdict(BaseModel):
    index: int
    relevant: bool = Field(description="이 근거 조각이 질문에 답하는 데 쓸모 있는가")


class ChunkVerdicts(BaseModel):
    verdicts: list[ChunkVerdict]


class GeneratedQuestions(BaseModel):
    questions: list[str] = Field(description="답변만 보고 거꾸로 만든 질문 3개")


def english_part(answer: str) -> str:
    return answer.split(KO_SECTION)[0].strip()


def split_chunks(contexts: list[str]) -> list[str]:
    """도구 결과를 근거 조각으로 나눈다. 검색 결과는 <document> 단위, 그 외(diff JSON)는 통째로."""
    chunks = []
    for c in contexts:
        docs = re.findall(r"<document.*?</document>", c, flags=re.S)
        chunks.extend(docs or [c])
    return chunks


def _ctx(chunks: list[str]) -> str:
    text = "\n\n".join(f"[{i}] {c}" for i, c in enumerate(chunks))
    return text[:MAX_CONTEXT_CHARS]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Judge:
    """평가 1회에 쓰는 judge 묶음. 모델 설정은 라운드 사이에 바꾸지 않는다."""

    def __init__(self):
        llm = get_judge_llm()
        self.rubric = llm.with_structured_output(JudgeResult)
        self.claims = llm.with_structured_output(Claims)
        self.chunks = llm.with_structured_output(ChunkVerdicts)
        self.questions = llm.with_structured_output(GeneratedQuestions)
        self.recall = llm.with_structured_output(Claims)
        self.emb = get_embeddings()

    async def rubric_score(self, question: str, answer: str, reference: str) -> dict:
        r = await self.rubric.ainvoke(
            f"{RUBRIC}\n\nQuestion: {question}\nReference answer: {reference}\nModel answer: {english_part(answer)}")
        return r.model_dump()

    async def faithfulness(self, answer: str, chunks: list[str]) -> float | None:
        r = await self.claims.ainvoke(
            "Break the ANSWER into short standalone factual claims (skip greetings and formatting). "
            "For each claim, decide if it can be inferred ONLY from the CONTEXT.\n\n"
            f"CONTEXT:\n{_ctx(chunks)}\n\nANSWER:\n{english_part(answer)}")
        if not r.claims:
            return None
        return sum(c.supported for c in r.claims) / len(r.claims)

    async def answer_relevancy(self, question: str, answer: str) -> float:
        r = await self.questions.ainvoke(
            "Generate 3 questions that the following answer would directly answer. "
            f"Write them in the same language as this original question: \"{question}\".\n\nANSWER:\n{english_part(answer)}")
        qs = r.questions[:3] or [""]
        vecs = await self.emb.aembed_documents([question, *qs])
        return sum(_cosine(vecs[0], v) for v in vecs[1:]) / len(qs)

    async def context_precision(self, question: str, reference: str, chunks: list[str]) -> float | None:
        if not chunks:
            return None
        r = await self.chunks.ainvoke(
            "For each numbered CONTEXT chunk, decide whether it is useful for answering the QUESTION "
            f"(use the REFERENCE answer as guidance). Return one verdict per index 0..{len(chunks) - 1}.\n\n"
            f"QUESTION: {question}\nREFERENCE: {reference}\n\nCONTEXT:\n{_ctx(chunks)}")
        rel = {v.index: v.relevant for v in r.verdicts}
        flags = [bool(rel.get(i, False)) for i in range(len(chunks))]
        if not any(flags):
            return 0.0
        # 평균 정밀도: 관련 조각이 위 순위에 있을수록 높다(RAGAS context precision)
        hits, total = 0, 0.0
        for k, f in enumerate(flags, 1):
            if f:
                hits += 1
                total += hits / k
        return total / sum(flags)

    async def context_recall(self, reference: str, chunks: list[str]) -> float | None:
        if not chunks:
            return 0.0
        r = await self.recall.ainvoke(
            "Split the REFERENCE answer into its individual statements. For each statement, decide whether it "
            "can be attributed to the CONTEXT.\n\n"
            f"CONTEXT:\n{_ctx(chunks)}\n\nREFERENCE:\n{reference}")
        if not r.claims:
            return None
        return sum(c.supported for c in r.claims) / len(r.claims)

    async def evaluate(self, case: dict, result: dict) -> dict:
        """참조 답변이 있는 문항만 심사한다. 근거가 있으면 RAGAS 4개, 없으면 relevancy만."""
        reference = case.get("reference")
        if not reference or result.get("status") != "ok":
            return {}
        q, a = case["question"], result["answer"]
        chunks = split_chunks(result.get("contexts", []))
        out = {"judge": await self.rubric_score(q, a, reference)}
        ragas = {"answer_relevancy": await self.answer_relevancy(q, a)}
        if chunks:
            ragas["faithfulness"] = await self.faithfulness(a, chunks)
            ragas["context_precision"] = await self.context_precision(q, reference, chunks)
        ragas["context_recall"] = await self.context_recall(reference, chunks)
        out["ragas"] = {k: (round(v, 3) if v is not None else None) for k, v in ragas.items()}
        return out
