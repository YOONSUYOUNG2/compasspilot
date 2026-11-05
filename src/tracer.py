"""FileTracer: 실행 기록을 JSONL 파일로 남기는 콜백 핸들러 (교안 local_tracer.py 방식).

- 질문 1건마다 trace_id를 붙여 질문 → LLM·도구 호출 → 답변(또는 차단)을 한 묶음으로 본다.
- 모든 기록은 파일에 쓰기 직전에 mask 함수를 거친다. main.ask가 임직원 이름 마스킹 함수
  (guards/masking.mask_text)를 넘긴다.
"""
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from langchain_core.callbacks import BaseCallbackHandler

from src import config

PREVIEW = 500  # 기록할 텍스트 최대 길이
_WRITE_LOCK = threading.Lock()  # 여러 질문을 동시에 실행해도 trace 줄이 섞이지 않게 한다


def _text(message) -> str:
    content = message.content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


def no_mask(text: str) -> str:
    return text


class FileTracer(BaseCallbackHandler):
    """LLM 호출, 도구 호출, 질문·답변을 JSONL 한 줄씩 기록한다."""

    def __init__(self, path: Path = config.TRACE_PATH, user_id: str = "staff",
                 mask: Callable[[str], str] = no_mask):
        self.path = Path(path)
        self.user_id = user_id
        self.mask = mask
        self.trace_id = uuid.uuid4().hex[:12]
        self._starts = {}
        self.tools_used: list[str] = []  # 이번 질문에서 호출된 도구 이름
        self.tool_outputs: list[tuple[str, str]] = []  # (도구 이름, 결과 전문) — 최종 답 검증용, 파일에는 쓰지 않음
        self._tool_names = {}

    def _write(self, record: dict):
        record = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "trace_id": self.trace_id,
                  "user_id": self.user_id, **record}
        line = self.mask(json.dumps(record, ensure_ascii=False))  # 기록 직전 마스킹
        with _WRITE_LOCK, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ---- 질문·답변·차단 (main.ask에서 직접 호출) ----
    def question(self, text: str):
        self._write({"event": "question", "input": text})

    def answer(self, text: str, elapsed: float):
        self._write({"event": "answer", "output": text[:PREVIEW], "latency_s": round(elapsed, 2)})

    def repaired(self, reason: str):
        self._write({"event": "answer_repaired", "reason": reason})

    def report_saved(self, paths: dict):
        self._write({"event": "report_saved", "files": paths})

    def blocked(self, text: str, reason: str):
        self._write({"event": "guard_block", "input": text, "reason": reason})

    # ---- LLM ----
    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        self._starts[run_id] = time.time()
        last = messages[0][-1] if messages and messages[0] else None
        # 실행 경로(checkpoint_ns)의 첫 구간이 에이전트 이름이다 (예: "competency_agent:...")
        ns = (kw.get("metadata") or {}).get("langgraph_checkpoint_ns", "")
        self._write({"event": "llm_start", "run_id": str(run_id),
                     "agent": ns.split(":")[0] if ns else None,
                     "n_messages": len(messages[0]) if messages else 0,
                     "last_input": _text(last)[:PREVIEW] if last is not None else ""})

    def on_llm_end(self, response, *, run_id, **kw):
        elapsed = time.time() - self._starts.pop(run_id, time.time())
        gen = response.generations[0][0]
        msg = getattr(gen, "message", None)
        tool_calls = [tc["name"] for tc in (getattr(msg, "tool_calls", None) or [])]
        self._write({"event": "llm_end", "run_id": str(run_id), "output": gen.text[:PREVIEW],
                     "tool_calls": tool_calls, "latency_s": round(elapsed, 2),
                     "usage": getattr(msg, "usage_metadata", None) or {}})

    def on_llm_error(self, error, *, run_id, **kw):
        self._write({"event": "llm_error", "run_id": str(run_id), "error": str(error)[:PREVIEW]})

    # ---- 도구 ----
    def on_tool_start(self, serialized, input_str, *, run_id, **kw):
        self._starts[run_id] = time.time()
        name = (serialized or {}).get("name") or ""
        self.tools_used.append(name)
        self._tool_names[run_id] = name
        self._write({"event": "tool_start", "run_id": str(run_id),
                     "tool": (serialized or {}).get("name"), "input": str(input_str)[:PREVIEW]})

    def on_tool_end(self, output, *, run_id, **kw):
        elapsed = time.time() - self._starts.pop(run_id, time.time())
        out = getattr(output, "content", output)
        if isinstance(out, list):  # MCP 도구는 content 블록 리스트로 줄 수 있다
            out = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in out)
        self.tool_outputs.append((self._tool_names.pop(run_id, ""), str(out)))
        self._write({"event": "tool_end", "run_id": str(run_id), "output": str(out)[:PREVIEW],
                     "latency_s": round(elapsed, 2)})

    def on_tool_error(self, error, *, run_id, **kw):
        self._write({"event": "tool_error", "run_id": str(run_id), "error": str(error)[:PREVIEW]})
