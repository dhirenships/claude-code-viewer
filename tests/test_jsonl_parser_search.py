import json
import tempfile
import unittest
from pathlib import Path

from cocomon.utils.jsonl_parser import JSONLParser


class JSONLParserSearchTests(unittest.TestCase):
    def test_global_search_finds_tool_only_messages_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            session_path = project_dir / "session-1.jsonl"
            self._write_jsonl(
                session_path,
                [
                    {
                        "type": "assistant",
                        "timestamp": "2026-05-21T10:00:00Z",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {
                                        "command": "git push -u origin fix/search-tools 2>&1 | tail -8",
                                        "description": "Push branch",
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "type": "user",
                        "timestamp": "2026-05-21T10:00:01Z",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "content": "remote: To create a merge request, visit: https://gitlab.example.test/project/-/merge_requests/new?merge_request%5Bsource_branch%5D=fix%2Fsearch-tools",
                                }
                            ],
                        },
                    },
                ],
            )

            parser = JSONLParser(str(tmp))
            command_results = parser.search_messages("git push -u origin fix/search-tools")
            output_results = parser.search_messages("merge_requests/new?merge_request%5Bsource_branch%5D=fix%2Fsearch-tools")

            self.assertEqual(command_results["total"], 1)
            self.assertEqual(command_results["results"][0]["line_number"], 1)
            self.assertTrue(command_results["results"][0]["is_tool_only"])
            self.assertEqual(output_results["total"], 1)
            self.assertEqual(output_results["results"][0]["line_number"], 2)
            self.assertTrue(output_results["results"][0]["has_tools"])

    def test_conversation_search_parses_tool_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            session_path = project_dir / "session-1.jsonl"
            self._write_jsonl(
                session_path,
                [
                    {
                        "type": "assistant",
                        "timestamp": "2026-05-21T10:00:00Z",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {"command": "git push -u origin fix/search-tools"},
                                }
                            ],
                        },
                    }
                ],
            )

            parser = JSONLParser(str(tmp))
            conversation = parser.get_conversation(
                "project",
                "session-1",
                search="git push -u origin fix/search-tools",
            )

            self.assertEqual(conversation["total"], 1)
            self.assertEqual(conversation["messages"][0]["line_number"], 1)
            self.assertIn("Tool Used: Bash", conversation["messages"][0]["content"])

    def _write_jsonl(self, path, rows):
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    unittest.main()
