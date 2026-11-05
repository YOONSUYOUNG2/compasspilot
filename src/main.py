"""CLI: python -m src.main --user <user_id> "질문"   (--user 생략 시 staff)

T7에서 입력 가드레일과 trace 기록을 앞뒤에 붙인다.
"""
import argparse
import asyncio
import logging
import sys
import warnings

from langchain_core.messages import HumanMessage

# 라이브러리 import 시 경고(chromadb, authlib 등)는 import 동안만 출력을 막는다(일부 라이브러리가 필터를 덮어씀)
_show = warnings.showwarning
warnings.showwarning = lambda *args, **kwargs: None
from src.agents import build_app, get_text  # noqa: E402
warnings.showwarning = _show
logging.getLogger("langchain_aws").setLevel(logging.ERROR)  # 도구 블록 변환 안내 로그 숨김

DEFAULT_USER = "staff"


async def ask(app, question: str, user_id: str = DEFAULT_USER, callbacks=None) -> dict:
    """질문 하나를 실행하고 최종 답변과 전체 결과를 돌려준다."""
    config = {"configurable": {"user_id": user_id}, "recursion_limit": 30}
    if callbacks:
        config["callbacks"] = callbacks
    result = await app.ainvoke({"messages": [HumanMessage(content=question)]}, config=config)
    return {"answer": get_text(result["messages"][-1]), "result": result}


async def _main(question: str, user_id: str):
    app = await build_app()
    out = await ask(app, question, user_id)
    print(out["answer"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="CompassPilot CLI")
    ap.add_argument("--user", default=DEFAULT_USER, help="사용자 ID (권한 판정용, 기본 staff)")
    ap.add_argument("question", help="질문")
    args = ap.parse_args()
    asyncio.run(_main(args.question, args.user))
