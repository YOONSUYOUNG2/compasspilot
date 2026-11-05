"""MCP 서버 연동 테스트: 실제로 자식 프로세스를 띄워 도구 목록과 호출 결과를 확인한다(Bedrock 호출 없음)."""
import asyncio
import json
import unittest

from langchain_mcp_adapters.client import MultiServerMCPClient

from src.assessment.parser import excel_files
from src.mcp_server import MCP_SERVER_CONFIG

HAS_EXCEL = len(excel_files()) >= 2


async def _call(args: dict):
    client = MultiServerMCPClient(MCP_SERVER_CONFIG)
    tools = {t.name: t for t in await client.get_tools()}
    result = await tools["diff_versions"].ainvoke(args) if "diff_versions" in tools else None
    return sorted(tools), result


def _text(result) -> str:
    """도구 결과가 문자열 또는 content 블록 리스트로 올 수 있어 텍스트만 꺼낸다."""
    if isinstance(result, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    return str(result)


@unittest.skipUnless(HAS_EXCEL, "실제 Assessment Excel이 없어 건너뜀 (data/private/versions/)")
class TestMcpServer(unittest.TestCase):
    def test_tools_and_default_diff(self):
        names, result = asyncio.run(_call({}))
        self.assertEqual(names, ["diff_versions"])
        data = json.loads(_text(result))
        self.assertEqual(data["counts"]["added"], 8)
        self.assertEqual((data["from_version"], data["to_version"]), ("2025-08", "2026-08"))

    def test_unknown_version(self):
        _, result = asyncio.run(_call({"to_version": "1999-01"}))
        self.assertIn("Unknown version", _text(result))


if __name__ == "__main__":
    unittest.main()
