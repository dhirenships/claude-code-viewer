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

    def test_search_index_reuses_unchanged_session_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            first_session = project_dir / "session-1.jsonl"
            second_session = project_dir / "session-2.jsonl"
            self._write_jsonl(
                first_session,
                [
                    {
                        "type": "user",
                        "timestamp": "2026-05-21T10:00:00Z",
                        "message": {"role": "user", "content": "stable needle"},
                    }
                ],
            )
            self._write_jsonl(
                second_session,
                [
                    {
                        "type": "user",
                        "timestamp": "2026-05-21T10:00:01Z",
                        "message": {"role": "user", "content": "changing haystack"},
                    }
                ],
            )

            parser = JSONLParser(str(tmp))
            original_update = parser._update_search_file
            built_paths = []

            def tracking_update(path, mtime_ns, size):
                built_paths.append(Path(path).name)
                return original_update(path, mtime_ns, size)

            parser._update_search_file = tracking_update

            parser.search_messages("needle")
            self.assertEqual(sorted(built_paths), ["session-1.jsonl", "session-2.jsonl"])

            built_paths.clear()
            self._write_jsonl(
                second_session,
                [
                    {
                        "type": "user",
                        "timestamp": "2026-05-21T10:00:01Z",
                        "message": {"role": "user", "content": "changing needle"},
                    }
                ],
            )

            results = parser.search_messages("needle")

            self.assertEqual(built_paths, ["session-2.jsonl"])
            self.assertEqual(results["total"], 2)

    def test_search_index_parses_only_appended_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            session_path = project_dir / "session-1.jsonl"
            self._write_jsonl(session_path, [self._user_row("first needle", "10:00:00")])

            parser = JSONLParser(str(tmp))
            self.assertEqual(parser.search_messages("needle")["total"], 1)
            first_entry = parser._search_file_index[str(session_path)]["entries"][0]

            parsed_lines = []
            original_parse = parser._parse_message

            def tracking_parse(data, line_num, include_tools=False):
                parsed_lines.append(line_num)
                return original_parse(data, line_num, include_tools)

            parser._parse_message = tracking_parse
            with session_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(self._user_row("second NEEDLE", "10:00:01")) + "\n")

            results = parser.search_messages("Needle")

            self.assertEqual(parsed_lines, [2])
            self.assertIs(parser._search_file_index[str(session_path)]["entries"][0], first_entry)
            self.assertEqual(results["total"], 2)
            self.assertEqual([r["line_number"] for r in results["results"]], [2, 1])
            self.assertIn("<mark>NEEDLE</mark>", results["results"][0]["snippet"])

    def test_search_index_rereads_rewritten_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            session_path = project_dir / "session-1.jsonl"
            self._write_jsonl(session_path, [self._user_row("old needle", "10:00:00")])

            parser = JSONLParser(str(tmp))
            self.assertEqual(parser.search_messages("old needle")["total"], 1)

            # Longer than before, so only the content check can spot the rewrite.
            self._write_jsonl(
                session_path,
                [
                    self._user_row("new needle", "10:00:00"),
                    self._user_row("another needle", "10:00:01"),
                ],
            )

            self.assertEqual(parser.search_messages("old needle")["total"], 0)
            self.assertEqual(parser.search_messages("needle")["total"], 2)

    def test_search_index_handles_last_line_without_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            session_path = project_dir / "session-1.jsonl"
            first = json.dumps(self._user_row("first needle", "10:00:00"))
            second = json.dumps(self._user_row("second needle", "10:00:01"))
            session_path.write_text(first, encoding="utf-8")

            parser = JSONLParser(str(tmp))
            self.assertEqual(parser.search_messages("needle")["total"], 1)

            with session_path.open("a", encoding="utf-8") as f:
                f.write("\n" + second[:20])
            self.assertEqual(parser.search_messages("needle")["total"], 1)
            self.assertEqual(parser.get_sessions("project")[0]["message_count"], 2)

            with session_path.open("a", encoding="utf-8") as f:
                f.write(second[20:] + "\n")
            results = parser.search_messages("needle")

            self.assertEqual(results["total"], 2)
            self.assertEqual([r["line_number"] for r in results["results"]], [2, 1])
            self.assertEqual(parser.get_sessions("project")[0]["message_count"], 2)

    def test_session_metadata_is_cached_and_updated_on_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            session_path = project_dir / "session-1.jsonl"
            self._write_jsonl(
                session_path,
                [
                    {**self._user_row("hello", "10:00:00"), "slug": "first-slug"},
                    {"type": "custom-title", "customTitle": "My title"},
                ],
            )

            parser = JSONLParser(str(tmp))
            session = parser.get_sessions("project")[0]
            self.assertEqual(session["message_count"], 2)
            self.assertEqual(session["session_name"], "My title")
            self.assertEqual(session["session_slug"], "first-slug")

            with session_path.open("a", encoding="utf-8") as f:
                f.write("\n")
                f.write(json.dumps({"type": "system", "subtype": "away_summary",
                                    "content": "Recap here (disable recaps in /config)"}) + "\n")
                f.write(json.dumps({"type": "last-prompt", "lastPrompt": "latest ask"}) + "\n")

            session = parser.get_sessions("project")[0]
            self.assertEqual(session["message_count"], 4)
            self.assertEqual(session["session_name"], "My title")
            self.assertEqual(session["session_recap"], "Recap here")
            self.assertEqual(session["session_last_prompt"], "latest ask")

            conversation = parser.get_conversation("project", "session-1")
            self.assertEqual(conversation["metadata"]["session_last_prompt"], "latest ask")

    def test_global_search_excludes_observer_sessions_unless_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            regular_project = Path(tmp) / "regular-project"
            observer_project_name = "-Users-name--claude-mem-observer-sessions"
            observer_project = Path(tmp) / observer_project_name
            regular_project.mkdir()
            observer_project.mkdir()

            matching_message = {
                "type": "user",
                "timestamp": "2026-08-10T10:00:00Z",
                "message": {"role": "user", "content": "WeeklyUpdate"},
            }
            self._write_jsonl(regular_project / "regular.jsonl", [matching_message])
            self._write_jsonl(observer_project / "observer.jsonl", [matching_message])

            parser = JSONLParser(str(tmp))

            default_results = parser.search_messages("WeeklyUpdate")
            observer_results = parser.search_messages(
                "WeeklyUpdate",
                filters={"project": observer_project_name},
            )

            self.assertEqual(default_results["total"], 1)
            self.assertEqual(default_results["results"][0]["session_id"], "regular")
            self.assertEqual(observer_results["total"], 1)
            self.assertEqual(observer_results["results"][0]["session_id"], "observer")

    def _user_row(self, content, time):
        return {
            "type": "user",
            "timestamp": f"2026-05-21T{time}Z",
            "message": {"role": "user", "content": content},
        }

    def _write_jsonl(self, path, rows):
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    unittest.main()
