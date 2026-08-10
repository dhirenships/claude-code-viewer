import json
import os
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
import re
from datetime import datetime
import difflib
import html
from bisect import bisect_right

# Session lines that can carry title/recap metadata contain one of these.
SESSION_METADATA_MARKERS = (b'"customTitle"', b'"slug"', b'"lastPrompt"', b'away_summary')


DEFAULT_EXCLUDED_SEARCH_PROJECTS = {
    "mem/observer/sessions",
    "mom/observer/sessions",
}


class JSONLParser:
    def __init__(self, claude_projects_path: str = None):
        self.claude_projects_path = claude_projects_path or os.path.expanduser("~/.claude/projects")
        self.claude_home = os.path.dirname(self.claude_projects_path.rstrip(os.sep))
        self._session_registry = None
        self._session_file_info = {}
        self._search_file_index = {}
    
    def get_projects(self) -> List[Dict]:
        """Scan and return all Claude Code projects"""
        projects = []
        if not os.path.exists(self.claude_projects_path):
            return projects
        
        for project_dir in os.listdir(self.claude_projects_path):
            project_path = os.path.join(self.claude_projects_path, project_dir)
            if os.path.isdir(project_path):
                # Get JSONL files in this project
                jsonl_files = [f for f in os.listdir(project_path) if f.endswith('.jsonl')]
                
                projects.append({
                    "name": project_dir,
                    "display_name": self._format_project_name(project_dir),
                    "path": project_path,
                    "session_count": len(jsonl_files),
                    "sessions": jsonl_files
                })
        
        return sorted(projects, key=lambda x: x["display_name"])

    def get_projects_with_sessions(self) -> List[Dict]:
        """Return projects with session metadata, sorted by latest activity."""
        projects = []
        for project in self.get_projects():
            sessions = self.get_sessions(project["name"])
            latest_session = sessions[0] if sessions else None

            projects.append({
                **project,
                "sessions": sessions,
                "latest_modified": latest_session["modified"] if latest_session else None,
            })

        current_paths = {session["path"] for project in projects for session in project["sessions"]}
        for cached_path in list(self._session_file_info):
            if cached_path not in current_paths:
                del self._session_file_info[cached_path]

        return sorted(
            projects,
            key=lambda project: project["latest_modified"] or "",
            reverse=True,
        )
    
    def get_sessions(self, project_name: str) -> List[Dict]:
        """Get all session files for a project with metadata"""
        project_path = os.path.join(self.claude_projects_path, project_name)
        sessions = []
        
        if not os.path.exists(project_path):
            return sessions
        
        for filename in os.listdir(project_path):
            if filename.endswith('.jsonl'):
                file_path = os.path.join(project_path, filename)
                file_stats = os.stat(file_path)
                session_id = filename.replace('.jsonl', '')
                file_info = self._get_session_file_info(file_path, file_stats)

                sessions.append({
                    "id": session_id,
                    "filename": filename,
                    "path": file_path,
                    "size": file_stats.st_size,
                    "modified": datetime.fromtimestamp(file_stats.st_mtime).isoformat(),
                    "message_count": file_info["message_count"],
                    **self._session_metadata_from_info(file_info, session_id)
                })
        
        return sorted(sessions, key=lambda x: x["modified"], reverse=True)
    
    def get_conversation(
        self, 
        project_name: str, 
        session_id: str, 
        page: Optional[int] = 1,
        per_page: int = 50,
        search: Optional[str] = None,
        message_type: Optional[str] = None,
        target_line: Optional[int] = None,
        include_tools: bool = False
    ) -> Dict:
        """Get paginated conversation data with optional filtering"""
        
        session_path = os.path.join(self.claude_projects_path, project_name, f"{session_id}.jsonl")
        
        if not os.path.exists(session_path):
            return {"messages": [], "total": 0, "page": page or 1, "per_page": per_page, "total_pages": 0}
        file_stats = os.stat(session_path)
        
        messages = []
        include_searchable_tools = include_tools or bool(search)

        with open(session_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line.strip())
                    
                    # Parse different message types
                    parsed_message = self._parse_message(data, line_num, include_searchable_tools)
                    parsed_message.update(self._content_view_flags(parsed_message))
                    
                    # Apply filters
                    if self._should_include_message(parsed_message, search, message_type, include_searchable_tools):
                        messages.append(parsed_message)
                        
                except json.JSONDecodeError:
                    continue
        
        # Pagination
        total = len(messages)
        total_pages = (total + per_page - 1) // per_page
        if target_line:
            target_index = next(
                (index for index, message in enumerate(messages)
                 if message.get("line_number") == target_line),
                None,
            )
            page = (target_index // per_page) + 1 if target_index is not None else None

        if page is None:
            page = 1 if (search or message_type) else total_pages or 1
        else:
            page = min(max(page, 1), total_pages or 1)

        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_messages = messages[start_idx:end_idx]
        
        return {
            "messages": paginated_messages,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "file_revision": f"{file_stats.st_mtime_ns}:{file_stats.st_size}",
            "metadata": self._get_session_metadata(session_path, session_id)
        }

    def search_messages(
        self,
        search: str,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict:
        """Search message text, tool calls, and tool output across every session."""
        search = (search or "").strip()
        if not search:
            return {"results": [], "total": 0, "limit": limit}

        records = self._get_search_index()
        needle = search.lower().encode("utf-8", "surrogatepass")
        filters = filters or {}
        project = filters.get("project")
        matches = []
        indexed_messages = 0

        for record in records:
            indexed_messages += len(record["entries"])
            if project and record["project_name"] != project:
                continue

            for index in self._matching_entry_indexes(record, needle):
                entry = record["entries"][index]
                match = {
                    **entry,
                    "project_name": record["project_name"],
                    "project_display_name": record["project_display_name"],
                    "session_id": record["session_id"],
                    "session_modified": record["session_modified"],
                    "message_date": self._message_date(entry, record["session_modified"]),
                }
                if self._entry_matches_filters(match, filters):
                    matches.append(match)

        # Matches are collected in path/line order and the sort is stable, so
        # ties keep the same order they had in a fully sorted index.
        matches.sort(
            key=lambda match: match["timestamp"] or match["session_modified"],
            reverse=True,
        )

        results = []
        session_match_count = {}
        for match in matches:
            session_key = (match["project_name"], match["session_id"])
            session_match_count[session_key] = session_match_count.get(session_key, 0) + 1
            if len(results) >= limit:
                continue

            content = match["content"].decode("utf-8", "surrogatepass")
            results.append({
                "project_name": match["project_name"],
                "project_display_name": match["project_display_name"],
                "session_id": match["session_id"],
                "session_modified": match["session_modified"],
                "line_number": match["line_number"],
                "page": ((session_match_count[session_key] - 1) // 50) + 1,
                "role": match["role"],
                "timestamp": match["timestamp"],
                "snippet": self._make_search_snippet(content, search),
                "has_tools": match["has_tools"],
                "is_tool_only": match["is_tool_only"],
                "has_file_edits": match["has_file_edits"],
            })

        return {
            "results": results,
            "total": len(matches),
            "limit": limit,
            "indexed_messages": indexed_messages,
            "matching_sessions": [
                {
                    "project_name": project_name,
                    "session_id": session_id,
                    "count": count,
                }
                for (project_name, session_id), count in session_match_count.items()
            ],
        }

    def _get_search_index(self) -> List[Dict]:
        """Return one search record per session file, refreshing changed files."""
        signature = self._get_search_index_signature()
        current_paths = {path for path, _, _ in signature}

        for cached_path in list(self._search_file_index):
            if cached_path not in current_paths:
                del self._search_file_index[cached_path]

        records = []
        for session_path, mtime_ns, size in signature:
            record = self._search_file_index.get(session_path)
            if not record or record["signature"] != (mtime_ns, size):
                record = self._update_search_file(session_path, mtime_ns, size)
            records.append(record)

        return records

    def _get_search_index_signature(self) -> Tuple:
        files = []
        if not os.path.isdir(self.claude_projects_path):
            return tuple()

        for root, _, filenames in os.walk(self.claude_projects_path):
            for filename in filenames:
                if not filename.endswith(".jsonl"):
                    continue

                path = os.path.join(root, filename)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                files.append((path, stat.st_mtime_ns, stat.st_size))

        return tuple(sorted(files))

    def _update_search_file(self, session_path: str, mtime_ns: int, size: int) -> Dict:
        """Parse the lines added to a session file into its search record.

        Each record keeps every entry's lowercased text in one NUL-terminated
        UTF-8 `corpus`, with `starts` giving each entry's offset into it. One
        bytes.find per file then skips files without a match, and bytes stay
        ~4x smaller than str once emoji in tool output force UCS-4 storage.
        """
        record = self._search_file_index.get(session_path)
        if record is None:
            project_name = os.path.basename(os.path.dirname(session_path))
            record = {
                "project_name": project_name,
                "project_display_name": self._format_project_name(project_name),
                "session_id": os.path.splitext(os.path.basename(session_path))[0],
                "reader": {},
            }

        try:
            restarted, first_line, lines, _ = self._read_appended_lines(session_path, record["reader"])
        except OSError:
            record["reader"].clear()
            restarted, first_line, lines = True, 1, []

        if restarted:
            record["entries"] = []
            record["starts"] = []
            record["corpus"] = b""

        entries = record["entries"]
        starts = record["starts"]
        corpus_parts = []
        corpus_size = len(record["corpus"])

        for line_num, line in enumerate(lines, first_line):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue

            message = self._parse_message(data, line_num, include_tools=True)
            if not self._should_include_message(message, None, None, include_tools=True):
                continue

            content = str(message.get("content", ""))
            text = content.lower().encode("utf-8", "surrogatepass")
            starts.append(corpus_size)
            corpus_parts.append(text)
            corpus_parts.append(b"\x00")
            corpus_size += len(text) + 1
            entries.append({
                "line_number": line_num,
                "role": message.get("role", ""),
                "timestamp": message.get("timestamp"),
                "content": content.encode("utf-8", "surrogatepass"),
                "is_tool_only": bool(message.get("is_tool_only")),
                **self._content_view_flags(message),
            })

        if corpus_parts:
            record["corpus"] += b"".join(corpus_parts)
        record["signature"] = (mtime_ns, size)
        record["session_modified"] = datetime.fromtimestamp(mtime_ns / 1_000_000_000).isoformat()
        self._search_file_index[session_path] = record
        return record

    def _matching_entry_indexes(self, record: Dict, needle: bytes):
        """Yield the index of each entry in a search record containing needle."""
        corpus = record["corpus"]
        starts = record["starts"]
        pos = corpus.find(needle)
        while pos != -1:
            index = bisect_right(starts, pos) - 1
            # The byte before the next entry's start is this entry's NUL terminator.
            entry_end = starts[index + 1] - 1 if index + 1 < len(starts) else len(corpus) - 1
            if pos + len(needle) <= entry_end:
                yield index
                pos = corpus.find(needle, entry_end + 1)
            else:
                pos = corpus.find(needle, pos + 1)

    def _read_appended_lines(self, path: str, state: Dict) -> Tuple[bool, int, List[bytes], bytes]:
        """Read the complete lines appended to a JSONL file since the last call.

        Claude Code only appends to session files, so `state` remembers how far
        the last call read and the bytes just before that point. If those bytes
        changed, the file was rewritten and is read again from the top.

        Returns (restarted, first_line_number, lines, unfinished_line). When
        restarted is True, callers must drop what they built from earlier lines.
        """
        offset = state.get("offset", 0)
        tail = state.get("tail", b"")

        with open(path, "rb") as f:
            if offset:
                f.seek(offset - len(tail))
                restarted = f.read(len(tail)) != tail
            else:
                restarted = True
            if restarted:
                state.clear()
                offset, tail = 0, b""
                f.seek(0)
            data = f.read()

        if state.get("open_line"):
            # The last call consumed a final line that had no newline yet.
            if not data:
                return False, state["lines"] + 1, [], b""
            if not data.startswith(b"\n"):
                state.clear()
                return self._read_appended_lines(path, state)
            data = data[1:]
            offset += 1
            tail = (tail + b"\n")[-64:]

        first_line = state.get("lines", 0) + 1
        *lines, unfinished = data.split(b"\n")
        open_line = bool(unfinished.strip()) and self._is_json(unfinished)
        if open_line:
            lines.append(unfinished)
            unfinished = b""

        consumed = len(data) - len(unfinished)
        state["offset"] = offset + consumed
        state["tail"] = (tail + data[max(0, consumed - 64):consumed])[-64:]
        state["lines"] = first_line - 1 + len(lines)
        state["open_line"] = open_line
        return restarted, first_line, lines, unfinished

    def _is_json(self, data: bytes) -> bool:
        try:
            json.loads(data)
        except ValueError:
            return False
        return True

    def _entry_matches_filters(self, entry: Dict, filters: Dict[str, Any]) -> bool:
        project = filters.get("project")
        if project and entry["project_name"] != project:
            return False
        if (
            not project
            and entry.get("project_display_name", "").lower()
            in DEFAULT_EXCLUDED_SEARCH_PROJECTS
        ):
            return False

        role = filters.get("role")
        if role and role != "all" and entry["role"] != role:
            return False

        date_from = filters.get("date_from")
        if date_from and entry["message_date"] and entry["message_date"] < date_from:
            return False

        date_to = filters.get("date_to")
        if date_to and entry["message_date"] and entry["message_date"] > date_to:
            return False

        for key in ("has_code", "has_tools", "has_errors", "has_file_edits"):
            if filters.get(key) and not entry.get(key):
                return False

        return True

    def _message_date(self, message: Dict, fallback: str) -> str:
        timestamp = message.get("timestamp") or fallback or ""
        return str(timestamp)[:10]

    def _message_has_error(self, message: Dict) -> bool:
        if message.get("raw_type") == "error":
            return True
        content = str(message.get("content", "")).lower()
        return "error" in content or "traceback" in content or "exception" in content

    def _content_view_flags(self, message: Dict) -> Dict[str, bool]:
        tool_names = message.get("tool_names", [])
        return {
            "has_code": bool(message.get("has_code")),
            "has_tools": bool(message.get("has_tool_activity")),
            "has_file_edits": any(
                name in {"Write", "Edit", "MultiEdit", "NotebookEdit"}
                for name in tool_names
            ),
            "has_errors": self._message_has_error(message),
        }
    
    def _parse_message(self, data: Dict, line_num: int, include_tools: bool = False) -> Dict:
        """Parse different types of JSONL messages"""
        base_message = {
            "line_number": line_num,
            "raw_type": data.get("type", "unknown"),
            "timestamp": data.get("timestamp"),
            "is_meta": data.get("isMeta", False),
        }
        
        # Handle different message types
        if data.get("type") == "summary":
            return {
                **base_message,
                "type": "summary",
                "content": data.get("summary", ""),
                "uuid": data.get("leafUuid", ""),
                "display_type": "Summary"
            }
        elif data.get("type") in ["user", "assistant"]:
            # Direct user/assistant messages (new format)
            message_data = data.get("message", {})
            content = message_data.get("content", "")
            content_metadata = self._structured_content_metadata(content)
            
            if isinstance(content, list):
                # Handle structured content (tool calls, etc.)
                content = self._parse_structured_content(content, include_tools)
            
            return {
                **base_message,
                "type": "message",
                "role": data.get("type"),
                "content": content,
                "display_type": data.get("type", "").title(),
                "model": message_data.get("model"),
                "has_code": self._contains_code(content),
                **content_metadata
            }
        elif "role" in data:
            # Legacy format - User/Assistant messages
            content = data.get("content", "")
            content_metadata = self._structured_content_metadata(content)
            if isinstance(content, list):
                # Handle structured content (tool calls, etc.)
                content = self._parse_structured_content(content, include_tools)
            
            return {
                **base_message,
                "type": "message",
                "role": data.get("role"),
                "content": content,
                "display_type": data.get("role", "").title(),
                "model": data.get("model"),
                "has_code": self._contains_code(content),
                **content_metadata
            }
        else:
            # Other types (system messages, etc.)
            return {
                **base_message,
                "type": "other",
                "content": json.dumps(data, indent=2),
                "display_type": data.get("type", "Unknown").title()
            }
    
    def _structured_content_metadata(self, content: object) -> Dict:
        """Classify structured content without relying on rendered text."""
        metadata = {
            "content_item_types": [],
            "tool_names": [],
            "has_tool_activity": False,
            "has_internal_activity": False,
            "is_tool_only": False,
            "is_internal_only": False,
        }

        if not isinstance(content, list):
            return metadata

        tool_types = {"tool_use", "tool_result"}
        internal_types = {"thinking", "redacted_thinking"}
        has_tool_activity = False
        has_internal_activity = False
        has_visible_content = False

        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type", "unknown")
                metadata["content_item_types"].append(item_type)

                if item_type in tool_types:
                    has_tool_activity = True
                    metadata["has_tool_activity"] = True
                    if item_type == "tool_use" and item.get("name"):
                        metadata["tool_names"].append(item["name"])
                    continue

                if item_type in internal_types:
                    has_internal_activity = True
                    metadata["has_internal_activity"] = True
                    continue

                if item_type == "text":
                    has_visible_content = bool(str(item.get("text", "")).strip()) or has_visible_content
                else:
                    has_visible_content = True
            elif isinstance(item, str):
                metadata["content_item_types"].append("text")
                has_visible_content = bool(item.strip()) or has_visible_content
            else:
                metadata["content_item_types"].append(type(item).__name__)
                has_visible_content = True

        metadata["is_tool_only"] = has_tool_activity and not has_visible_content
        metadata["is_internal_only"] = has_internal_activity and not has_visible_content
        return metadata

    def _parse_structured_content(self, content_list: List, include_tools: bool = False) -> str:
        """Parse structured content from tool calls"""
        parsed_parts = []
        for item in content_list:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    # Regular text content - preserve line breaks
                    text_content = item.get("text", "")
                    parsed_parts.append(text_content)
                elif item.get("type") == "image":
                    # Image content
                    parsed_parts.append("📷 **[Image attached]**")
                elif item.get("type") == "tool_use":
                    if not include_tools:
                        continue

                    # Tool use - format nicely
                    tool_name = item.get("name", "unknown_tool")
                    tool_params = item.get("input", {})
                    
                    # Special handling for Edit tool calls - show as diff
                    if tool_name == "Edit" and tool_params.get("old_string") and tool_params.get("new_string"):
                        file_path = tool_params.get("file_path", "unknown_file")
                        old_string = tool_params.get("old_string", "")
                        new_string = tool_params.get("new_string", "")
                        
                        # Generate diff HTML
                        diff_html = self._generate_diff_html(old_string, new_string, file_path)
                        parsed_parts.append(f"✏️ **Edit Tool: {file_path}**\n{diff_html}")
                    else:
                        # Regular tool use - format parameters readably
                        if tool_params:
                            param_lines = []
                            for key, value in tool_params.items():
                                if isinstance(value, str) and len(value) > 100:
                                    # Truncate very long strings
                                    param_lines.append(f"  **{key}**: {value[:100]}...")
                                else:
                                    param_lines.append(f"  **{key}**: {value}")
                            params_text = "\n".join(param_lines)
                        else:
                            params_text = "  (no parameters)"
                        
                        parsed_parts.append(f"🔧 **Tool Used: {tool_name}**\n{params_text}")
                    
                elif item.get("type") == "tool_result":
                    if not include_tools:
                        continue

                    # Tool result - handle different result types
                    result_content = item.get("content", "")
                    
                    # Check for Edit tool results with diff information
                    tool_use_result = item.get("toolUseResult", {})
                    if (tool_use_result and 
                        tool_use_result.get("oldString") and 
                        tool_use_result.get("newString")):
                        # This is an Edit tool result with diff data
                        file_path = tool_use_result.get("filePath", "unknown_file")
                        old_string = tool_use_result.get("oldString", "")
                        new_string = tool_use_result.get("newString", "")
                        
                        # Generate diff HTML for tool result
                        diff_html = self._generate_diff_html(old_string, new_string, file_path)
                        parsed_parts.append(f"✅ **Edit Result: {file_path}**\n{diff_html}")
                        
                        # Also show the regular tool output if it contains useful info
                        if isinstance(result_content, str) and result_content.strip():
                            parsed_parts.append(f"📋 **Tool Output:**\n```\n{result_content}\n```")
                    else:
                        # Regular tool result handling
                        if isinstance(result_content, str):
                            # Check if already truncated in JSONL or if we need to truncate
                            if "... (output truncated)" in result_content:
                                # Already truncated in JSONL - keep as is
                                parsed_parts.append(f"📋 **Tool Output:**\n```\n{result_content}\n```")
                            elif len(result_content) > 5000:
                                # Only truncate very long results (increased limit)
                                result_content = result_content[:5000] + "\n... (output truncated by viewer)"
                                parsed_parts.append(f"📋 **Tool Output:**\n```\n{result_content}\n```")
                            else:
                                # Show full result
                                parsed_parts.append(f"📋 **Tool Output:**\n```\n{result_content}\n```")
                        else:
                            parsed_parts.append(f"📋 **Tool Output:**\n```json\n{json.dumps(result_content, indent=2)}\n```")
                elif item.get("type") in {"thinking", "redacted_thinking"}:
                    continue
                else:
                    # Unknown content type
                    parsed_parts.append(f"ℹ️ **{item.get('type', 'Unknown')}:**\n```json\n{json.dumps(item, indent=2)}\n```")
            elif isinstance(item, str):
                # Simple string content
                parsed_parts.append(item)
            else:
                # Other types
                parsed_parts.append(str(item))
        
        return "\n\n".join(parsed_parts)
    
    def _contains_code(self, content: str) -> bool:
        """Check if content contains code blocks"""
        if not isinstance(content, str):
            return False
        
        # Look for common code patterns
        code_patterns = [
            r'```[\w]*\n',  # Markdown code blocks
            r'def \w+\(',   # Python functions
            r'class \w+',   # Class definitions
            r'import \w+',  # Import statements
            r'from \w+',    # From imports
            r'<[a-zA-Z][^>]*>',  # HTML tags
            r'\$\s*\w+',    # Shell commands
        ]
        
        return any(re.search(pattern, content) for pattern in code_patterns)
    
    def _should_include_message(
        self, 
        message: Dict, 
        search: Optional[str], 
        message_type: Optional[str],
        include_tools: bool = False
    ) -> bool:
        """Apply search and type filters"""
        
        role = message.get("role", "").lower()
        content = str(message.get("content", ""))

        if message.get("is_meta"):
            return False

        if message.get("model") == "<synthetic>" and content == "No response requested.":
            return False

        if message.get("is_tool_only") and not include_tools:
            return False

        if message.get("is_internal_only"):
            return False

        if not content.strip():
            return False

        # Type filter. By default the viewer focuses on the real conversation
        # turns and hides summaries, tool/system records, and other JSONL noise.
        if message_type:
            if role != message_type.lower():
                return False
        elif role not in {"user", "assistant"}:
            return False
        
        # Search filter
        if search:
            search_text = search.lower()
            content = str(message.get("content", "")).lower()
            
            if search_text not in content:
                return False
        
        return True

    def _make_search_snippet(self, content: str, search: str, radius: int = 90) -> str:
        """Return a compact escaped snippet with the search term highlighted."""
        text = re.sub(r'\s+', ' ', str(content)).strip()
        search_text = search.lower()
        match_index = text.lower().find(search_text)

        if match_index == -1:
            snippet = text[:radius * 2]
            prefix = ""
            suffix = "..." if len(text) > len(snippet) else ""
        else:
            start = max(match_index - radius, 0)
            end = min(match_index + len(search) + radius, len(text))
            snippet = text[start:end]
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(text) else ""

        escaped = html.escape(snippet)
        escaped_search = re.escape(html.escape(search))
        highlighted = re.sub(
            f"({escaped_search})",
            r"<mark>\1</mark>",
            escaped,
            flags=re.IGNORECASE,
        )

        return f"{prefix}{highlighted}{suffix}"
    
    def _get_session_file_info(self, file_path: str, file_stats: Optional[os.stat_result] = None) -> Dict:
        """Return the message count and title fields stored in a session file.

        Cached per file. A changed file only has its newly appended lines read,
        and only lines that mention a metadata key are JSON-decoded.
        """
        try:
            file_stats = file_stats or os.stat(file_path)
            signature = (file_stats.st_mtime_ns, file_stats.st_size)
            info = self._session_file_info.get(file_path)
            if info and info["signature"] == signature:
                return info

            info = info or {"reader": {}}
            restarted, _, lines, unfinished = self._read_appended_lines(file_path, info["reader"])
        except OSError:
            self._session_file_info.pop(file_path, None)
            return {
                "message_count": 0,
                "custom_title": None,
                "slug": None,
                "away_summary": None,
                "last_prompt": None,
            }

        if restarted:
            info.update(
                line_count=0,
                custom_title=None,
                slug=None,
                away_summary=None,
                last_prompt=None,
            )

        for line in lines:
            if not line.strip():
                continue
            info["line_count"] += 1
            if not any(marker in line for marker in SESSION_METADATA_MARKERS):
                continue

            try:
                data = json.loads(line)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue

            info["custom_title"] = data.get("customTitle") or info["custom_title"]
            info["slug"] = data.get("slug") or info["slug"]
            if data.get("type") == "system" and data.get("subtype") == "away_summary":
                info["away_summary"] = data.get("content") or info["away_summary"]
            info["last_prompt"] = data.get("lastPrompt") or info["last_prompt"]

        # A line still being written counts as a message too.
        info["message_count"] = info["line_count"] + (1 if unfinished.strip() else 0)
        info["signature"] = signature
        self._session_file_info[file_path] = info
        return info

    def _get_session_registry(self) -> Dict:
        """Read live Claude session metadata from ~/.claude/sessions/*.json."""
        if self._session_registry is not None:
            return self._session_registry

        registry = {}
        sessions_dir = os.path.join(self.claude_home, "sessions")
        if os.path.isdir(sessions_dir):
            for filename in os.listdir(sessions_dir):
                if not filename.endswith(".json"):
                    continue

                path = os.path.join(sessions_dir, filename)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except (OSError, json.JSONDecodeError):
                    continue

                session_id = data.get("sessionId")
                if session_id:
                    registry[session_id] = data

        self._session_registry = registry
        return registry

    def _get_session_metadata(self, file_path: str, session_id: str) -> Dict:
        """Return display metadata discoverable from Claude's JSON/JSONL stores."""
        return self._session_metadata_from_info(self._get_session_file_info(file_path), session_id)

    def _session_metadata_from_info(self, info: Dict, session_id: str) -> Dict:
        registry_meta = self._get_session_registry().get(session_id, {})
        away_summary = info["away_summary"]
        if away_summary:
            away_summary = away_summary.replace(" (disable recaps in /config)", "").strip()

        return {
            "session_name": registry_meta.get("name") or info["custom_title"] or info["slug"],
            "session_custom_title": info["custom_title"],
            "session_slug": info["slug"],
            "session_recap": away_summary,
            "session_last_prompt": info["last_prompt"],
        }
    def _format_project_name(self, project_dir: str) -> str:
        """Convert project directory name to readable format"""
        # Convert -media-sukhon-usbd-python-projects-converters to a readable name
        if project_dir.startswith('-'):
            # Remove leading dash and convert to path-like format
            clean_name = project_dir[1:].replace('-', '/')
            # Take last few meaningful parts
            parts = clean_name.split('/')
            if len(parts) > 3:
                return '/'.join(parts[-3:])  # Last 3 parts
            return clean_name
        
        return project_dir
    
    def _generate_diff_html(self, old_string: str, new_string: str, file_path: str = "") -> str:
        """Generate HTML diff view from old_string and new_string"""
        # Split into lines for difflib
        old_lines = old_string.splitlines(keepends=True)
        new_lines = new_string.splitlines(keepends=True)
        
        # Generate unified diff
        diff = list(difflib.unified_diff(
            old_lines, 
            new_lines, 
            fromfile=f"a/{file_path}", 
            tofile=f"b/{file_path}",
            lineterm=""
        ))
        
        if not diff:
            return f"<div class='diff-no-changes'>No changes detected in {file_path}</div>"
        
        # Parse unified diff and create HTML
        html_lines = []
        html_lines.append(f'<div class="diff-container">')
        html_lines.append(f'<div class="diff-header">📝 <strong>File:</strong> {file_path}</div>')
        html_lines.append('<div class="diff-content">')
        
        line_num_old = 0
        line_num_new = 0
        
        for line in diff:
            if line.startswith('@@'):
                # Hunk header - extract line numbers
                match = re.search(r'-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?', line)
                if match:
                    line_num_old = int(match.group(1))
                    line_num_new = int(match.group(2))
                html_lines.append(f'<div class="diff-hunk-header">{line.strip()}</div>')
            elif line.startswith('---') or line.startswith('+++'):
                # File headers - skip as we already show filename
                continue
            elif line.startswith('-'):
                # Removed line
                content = line[1:].rstrip('\n\r')
                html_lines.append(f'<div class="diff-line diff-removed">')
                html_lines.append(f'<span class="diff-line-number">{line_num_old}</span>')
                html_lines.append(f'<span class="diff-marker">-</span>')
                html_lines.append(f'<span class="diff-content">{self._escape_html(content)}</span>')
                html_lines.append('</div>')
                line_num_old += 1
            elif line.startswith('+'):
                # Added line
                content = line[1:].rstrip('\n\r')
                html_lines.append(f'<div class="diff-line diff-added">')
                html_lines.append(f'<span class="diff-line-number">{line_num_new}</span>')
                html_lines.append(f'<span class="diff-marker">+</span>')
                html_lines.append(f'<span class="diff-content">{self._escape_html(content)}</span>')
                html_lines.append('</div>')
                line_num_new += 1
            elif line.startswith(' '):
                # Context line
                content = line[1:].rstrip('\n\r')
                html_lines.append(f'<div class="diff-line diff-context">')
                html_lines.append(f'<span class="diff-line-number">{line_num_old}</span>')
                html_lines.append(f'<span class="diff-marker"> </span>')
                html_lines.append(f'<span class="diff-content">{self._escape_html(content)}</span>')
                html_lines.append('</div>')
                line_num_old += 1
                line_num_new += 1
        
        html_lines.append('</div>')  # diff-content
        html_lines.append('</div>')  # diff-container
        
        return '\n'.join(html_lines)
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML characters"""
        return (text.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('"', '&quot;')
                   .replace("'", '&#x27;'))
