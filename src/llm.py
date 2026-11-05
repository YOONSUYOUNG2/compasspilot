"""LLM·임베딩 생성 함수. LLM 객체는 이 모듈의 함수로만 만든다(CLAUDE.md 2절).

실행하면 연결 점검을 한다: python -m src.llm
"""
from langchain_aws import BedrockEmbeddings, ChatBedrockConverse

from src import config


def _chat(model_id: str, region: str) -> ChatBedrockConverse:
    """모델 ID와 리전으로 Bedrock 대화 모델 하나를 만든다."""
    return ChatBedrockConverse(model=model_id, region_name=region, temperature=config.TEMPERATURE)


def get_chat_llm(with_fallbacks: bool = True):
    """기본 모델(Supervisor, 하위 에이전트, 산출물 추출용).

    with_fallbacks=True면 호출 실패·throttling 시 config.CHAT_FALLBACKS 순서로 넘어간다.
    """
    primary = _chat(*config.CHAT_PRIMARY)
    if not with_fallbacks:
        return primary
    return primary.with_fallbacks([_chat(m, r) for m, r in config.CHAT_FALLBACKS])


def get_fallback_models() -> list[ChatBedrockConverse]:
    """대체 모델 목록(도구 바인딩 후 따로 fallback을 걸어야 할 때 쓴다)."""
    return [_chat(m, r) for m, r in config.CHAT_FALLBACKS]


def get_light_llm(with_fallbacks: bool = True):
    """가벼운 작업용(입력 가드레일 LLM 판별). 한도에 걸리면 같은 모델의 다른 리전으로 넘어간다."""
    primary = _chat(*config.LIGHT_MODEL)
    return primary.with_fallbacks([_chat(*config.LIGHT_FALLBACK)]) if with_fallbacks else primary


def get_judge_llm() -> ChatBedrockConverse:
    """평가 심사용. 재평가 조건을 고정하려고 대체 모델을 걸지 않는다."""
    return _chat(*config.JUDGE_MODEL)


def get_embeddings() -> BedrockEmbeddings:
    """Requirement 색인·검색용 임베딩."""
    model_id, region = config.EMBED_MODEL
    return BedrockEmbeddings(model_id=model_id, region_name=region)


if __name__ == "__main__":
    # 연결 점검: 기본·대체·경량 모델 각각 1회 호출 + 임베딩 차원 확인 (키 값은 출력하지 않는다)
    prompt = "Reply with exactly: OK"
    checks = [("primary", config.CHAT_PRIMARY)]
    checks += [(f"fallback{i}", mr) for i, mr in enumerate(config.CHAT_FALLBACKS, 1)]
    checks += [("light", config.LIGHT_MODEL)]
    for name, (model_id, region) in checks:
        try:
            text = _chat(model_id, region).invoke(prompt).content
            print(f"[OK]   {name:9} {model_id} @ {region} -> {str(text).strip()[:40]}")
        except Exception as e:  # 어떤 모델이 막혔는지 보려고 계속 진행
            print(f"[FAIL] {name:9} {model_id} @ {region} -> {type(e).__name__}: {str(e)[:120]}")
    try:
        vec = get_embeddings().embed_query("landing zone requirement")
        print(f"[OK]   embedding {config.EMBED_MODEL[0]} dim={len(vec)}")
    except Exception as e:
        print(f"[FAIL] embedding -> {type(e).__name__}: {str(e)[:120]}")
