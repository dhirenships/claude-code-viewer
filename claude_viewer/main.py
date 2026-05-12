"""FastAPI main application for cocoview."""

import asyncio
import html
import io
import json
import os
import subprocess
import threading
import time
import uuid
from urllib.parse import quote, urlencode
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from .utils.jsonl_parser import JSONLParser
import markdown
from html.parser import HTMLParser
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound
import re
from .statusline_setup import get_lan_ip, read_share_base_url

# Get the package directory
PACKAGE_DIR = Path(__file__).parent

# Try to find static and templates directories
# First try relative to package (for installed package)
STATIC_DIR = PACKAGE_DIR / "static"
TEMPLATES_DIR = PACKAGE_DIR / "templates"

# If not found, try relative to parent (for development)
if not STATIC_DIR.exists():
    STATIC_DIR = PACKAGE_DIR.parent / "static"
if not TEMPLATES_DIR.exists():
    TEMPLATES_DIR = PACKAGE_DIR.parent / "templates"

# Create FastAPI app
app = FastAPI(
    title="cocoview",
    description="Web UI for browsing Claude Code conversation history",
    version="1.1.0"
)

# Setup static files and templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
LIVE_JOBS: Dict[str, Dict[str, Any]] = {}
LIVE_JOBS_LOCK = threading.Lock()
PARSER_CACHE: Dict[str, JSONLParser] = {}

# Initialize parser with custom path from environment
def get_parser():
    """Get JSONLParser instance with configured path."""
    claude_path = os.environ.get("CLAUDE_PROJECTS_PATH")
    if not claude_path:
        # Fallback to default
        claude_path = str(Path.home() / ".claude" / "projects")
    if claude_path not in PARSER_CACHE:
        PARSER_CACHE[claude_path] = JSONLParser(claude_path)
    return PARSER_CACHE[claude_path]

def build_search_filters(
    project_filter: Optional[str],
    role: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    has_code: Optional[str],
    has_tools: Optional[str],
    has_errors: Optional[str],
    has_file_edits: Optional[str],
) -> Dict[str, Any]:
    """Normalize global search filters from query parameters."""
    filters: Dict[str, Any] = {}
    if project_filter:
        filters["project"] = project_filter
    if role and role in {"user", "assistant"}:
        filters["role"] = role
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to
    for key, value in {
        "has_code": has_code,
        "has_tools": has_tools,
        "has_errors": has_errors,
        "has_file_edits": has_file_edits,
    }.items():
        if value:
            filters[key] = True
    return filters

# Pydantic models
class Project(BaseModel):
    name: str
    display_name: str
    path: str
    session_count: int
    sessions: List[str]

class Session(BaseModel):
    id: str
    filename: str
    path: str
    size: int
    modified: str
    message_count: int

class Message(BaseModel):
    line_number: int
    type: str
    role: Optional[str] = None
    content: str
    display_type: str
    has_code: bool = False
    timestamp: Optional[str] = None
    uuid: Optional[str] = None

class ConversationResponse(BaseModel):
    messages: List[Dict[str, Any]]
    total: int
    page: int
    per_page: int
    total_pages: int

class LiveClaudeRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None

class SessionSendRequest(BaseModel):
    message: str
    project_name: Optional[str] = None
    session_id: str

# Custom markdown renderer with syntax highlighting
def render_markdown_with_code(text: str) -> str:
    """Render markdown with syntax highlighting for code blocks"""
    
    # Check if content already contains diff HTML - if so, preserve it
    if '<div class="diff-container">' in text:
        # This is diff content that's already HTML - just process markdown around it
        # but preserve the diff HTML blocks
        
        # Split content by diff containers to process markdown around them
        diff_parts = text.split('<div class="diff-container">')
        processed_parts = []
        
        for i, part in enumerate(diff_parts):
            if i == 0:
                # First part - before any diff, process as markdown
                processed_parts.append(process_markdown_text(part))
            else:
                # This part starts with diff content
                if '</div>' in part:
                    # Find where diff content ends
                    diff_end = part.rfind('</div>') + 6  # Include the closing tag
                    diff_html = '<div class="diff-container">' + part[:diff_end]
                    remaining_text = part[diff_end:]
                    
                    processed_parts.append(diff_html)
                    if remaining_text.strip():
                        processed_parts.append(process_markdown_text(remaining_text))
                else:
                    # Malformed diff HTML, process as regular markdown
                    processed_parts.append(process_markdown_text('<div class="diff-container">' + part))
        
        return ''.join(processed_parts)
    else:
        # Regular content without diffs
        return process_markdown_text(text)

def process_markdown_text(text: str) -> str:
    """Process text as markdown with syntax highlighting"""
    
    # Custom renderer for code blocks
    def highlight_code_block(match):
        language = match.group(1) or 'text'
        code = match.group(2)
        
        try:
            if language.lower() in ['text', 'plain', '']:
                lexer = guess_lexer(code)
            else:
                lexer = get_lexer_by_name(language.lower())
            
            formatter = HtmlFormatter(
                style='github-dark',
                cssclass='highlight',
                linenos=False,
                noclasses=True
            )
            
            highlighted = highlight(code, lexer, formatter)
            return f'<div class="code-block">{highlighted}</div>'
            
        except (ClassNotFound, Exception):
            return f'<pre><code class="language-{language}">{code}</code></pre>'
    
    # Process code blocks first
    code_block_pattern = r'```(\w*)\n(.*?)\n```'
    text = re.sub(code_block_pattern, highlight_code_block, text, flags=re.DOTALL)
    
    # Process inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    # Convert markdown to HTML while preserving Claude's terminal-style soft
    # line breaks. Without nl2br, review lists get reflowed into one paragraph.
    html = markdown.markdown(text, extensions=['tables', 'fenced_code', 'nl2br'])
    
    return html

class SearchHighlightHTMLParser(HTMLParser):
    """Highlight search text in rendered HTML without touching tags."""

    def __init__(self, search: str):
        super().__init__(convert_charrefs=False)
        self.search_pattern = re.compile(re.escape(search), re.IGNORECASE)
        self.parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        self.parts.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs: List[tuple]) -> None:
        self.parts.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(self.search_pattern.sub(
            lambda match: f"<mark>{html.escape(match.group(0))}</mark>",
            data,
        ))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")

    def get_html(self) -> str:
        return "".join(self.parts)

def highlight_rendered_search(html_text: str, search: Optional[str]) -> str:
    search = (search or "").strip()
    if not search:
        return html_text

    parser = SearchHighlightHTMLParser(search)
    parser.feed(html_text)
    parser.close()
    return parser.get_html()

def get_current_project_name() -> str:
    """Return Claude's project directory name for this viewer process cwd."""
    cwd = os.getcwd().rstrip(os.sep)
    return "-" + cwd.lstrip(os.sep).replace(os.sep, "-")

def _live_conversation_url(project_name: str, session_id: str) -> str:
    return f"/conversation/{project_name}/{session_id}?embedded=true"

def _request_port(request: Request) -> Optional[int]:
    if request.url.port:
        return request.url.port

    host = request.headers.get("host", "")
    if ":" in host:
        _, _, port_text = host.rpartition(":")
        try:
            return int(port_text)
        except ValueError:
            return None

    return 443 if request.url.scheme == "https" else 80

def _session_share_url(request: Request, session_id: str) -> str:
    configured_base_url = os.environ.get("CLAUDE_VIEWER_SHARE_BASE_URL") or read_share_base_url()
    if configured_base_url:
        return f"{configured_base_url.rstrip('/')}/v/{session_id[:8]}"

    host = get_lan_ip() or request.url.hostname or "localhost"
    port = _request_port(request)
    netloc = f"{host}:{port}" if port not in {80, 443, None} else host
    return f"{request.url.scheme}://{netloc}/v/{session_id[:8]}"

def _append_live_event(job: Dict[str, Any], event_type: str, data: Dict[str, Any]) -> None:
    data.setdefault("job_id", job["id"])
    with job["condition"]:
        job["events"].append({
            "event": event_type,
            "data": data,
            "created_at": time.time(),
        })
        job["condition"].notify_all()

def _run_live_claude_job(job: Dict[str, Any]) -> None:
    project_name = get_current_project_name()
    job["project_name"] = project_name
    requested_session_id = job.get("requested_session_id")
    session_id = requested_session_id or job["session_id"]
    job["session_id"] = session_id

    cmd = [
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--permission-mode",
        "acceptEdits",
    ]
    if requested_session_id:
        cmd.extend(["--resume", requested_session_id])
    else:
        cmd.extend(["--session-id", session_id])
    cmd.append(job["prompt"])

    job["cmd"] = cmd
    _append_live_event(job, "status", {
        "status": "starting",
        "session_id": session_id,
        "project_name": project_name,
    })

    try:
        process = subprocess.Popen(
            cmd,
            cwd=os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        job["status"] = "failed"
        _append_live_event(job, "error", {
            "status": "failed",
            "message": str(exc),
            "session_id": session_id,
            "project_name": project_name,
        })
        _append_live_event(job, "done", {
            "status": "failed",
            "returncode": None,
            "session_id": session_id,
            "project_name": project_name,
        })
        return

    job["process"] = process
    job["status"] = "running"
    buffer = ""

    def handle_json_row(row: Dict[str, Any]) -> None:
        nonlocal session_id

        row_session_id = row.get("session_id")
        if row_session_id and row_session_id != session_id:
            session_id = row_session_id
            job["session_id"] = session_id

        row_type = row.get("type")
        if row_type == "system" and row.get("subtype") == "init":
            _append_live_event(job, "init", {
                "session_id": row.get("session_id") or session_id,
                "project_name": project_name,
                "model": row.get("model"),
                "cwd": row.get("cwd"),
            })
        elif row_type == "system" and row.get("subtype") == "status":
            _append_live_event(job, "status", {
                "status": row.get("status") or "running",
                "session_id": session_id,
                "project_name": project_name,
            })
        elif row_type == "rate_limit_event":
            _append_live_event(job, "rate_limit", {
                "session_id": session_id,
                "project_name": project_name,
                "rate_limit_info": row.get("rate_limit_info", {}),
            })
        elif row_type == "stream_event":
            stream_event = row.get("event", {})
            if stream_event.get("type") == "content_block_start":
                block = stream_event.get("content_block", {})
                if block.get("type") == "text":
                    _append_live_event(job, "assistant_start", {
                        "index": stream_event.get("index"),
                        "session_id": session_id,
                        "project_name": project_name,
                    })
            elif stream_event.get("type") == "content_block_delta":
                delta = stream_event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    job["assistant_text"] += text
                    _append_live_event(job, "delta", {
                        "text": text,
                        "index": stream_event.get("index"),
                        "session_id": session_id,
                        "project_name": project_name,
                    })
            elif stream_event.get("type") == "message_stop":
                _append_live_event(job, "message_stop", {
                    "session_id": session_id,
                    "project_name": project_name,
                })
        elif row_type == "assistant":
            message = row.get("message", {})
            _append_live_event(job, "assistant_snapshot", {
                "session_id": session_id,
                "project_name": project_name,
                "content": message.get("content", []),
            })
        elif row_type == "result":
            status = "failed" if row.get("is_error") else row.get("subtype", "done")
            _append_live_event(job, "result", {
                "status": status,
                "session_id": row.get("session_id") or session_id,
                "project_name": project_name,
                "conversation_url": _live_conversation_url(project_name, row.get("session_id") or session_id),
                "result": row.get("result", ""),
                "stop_reason": row.get("stop_reason"),
                "duration_ms": row.get("duration_ms"),
                "usage": row.get("usage", {}),
            })

    assert process.stdout is not None
    for chunk in iter(lambda: process.stdout.read(1), ""):
        buffer += chunk
        if "\n" not in buffer:
            continue

        lines = buffer.splitlines(keepends=True)
        if not lines[-1].endswith(("\n", "\r")):
            buffer = lines.pop()
        else:
            buffer = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                handle_json_row(json.loads(line))
            except json.JSONDecodeError:
                _append_live_event(job, "raw", {
                    "text": line,
                    "session_id": session_id,
                    "project_name": project_name,
                })

    if buffer.strip():
        try:
            handle_json_row(json.loads(buffer.strip()))
        except json.JSONDecodeError:
            _append_live_event(job, "raw", {
                "text": buffer.strip(),
                "session_id": session_id,
                "project_name": project_name,
            })

    returncode = process.wait()
    job["returncode"] = returncode
    job["status"] = "done" if returncode == 0 else "failed"
    _append_live_event(job, "done", {
        "status": job["status"],
        "returncode": returncode,
        "session_id": session_id,
        "project_name": project_name,
        "conversation_url": _live_conversation_url(project_name, session_id),
    })

def _format_sse(event: str, data: Dict[str, Any], event_id: int) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data)}\n\n"

def _ps_for_pid(pid: int) -> Optional[Dict[str, str]]:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid=,ppid=,tty=,stat=,command="],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    line = result.stdout.strip()
    if result.returncode != 0 or not line:
        return None

    parts = line.split(None, 4)
    if len(parts) < 5:
        return None

    return {
        "pid": parts[0],
        "ppid": parts[1],
        "tty": parts[2],
        "stat": parts[3],
        "command": parts[4],
    }

def _load_live_claude_registries() -> Dict[str, Dict[str, Any]]:
    sessions_dir = Path.home() / ".claude" / "sessions"
    if not sessions_dir.exists():
        return {}

    live_sessions: Dict[str, Dict[str, Any]] = {}
    for session_file in sessions_dir.glob("*.json"):
        try:
            data = json.loads(session_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue

        session_id = data.get("sessionId")
        pid = data.get("pid")
        if not session_id or not isinstance(pid, int):
            continue

        ps = _ps_for_pid(pid)
        if not ps or "claude" not in ps["command"].lower():
            continue

        data = {**data, "registry_file": str(session_file), "process": ps}
        previous = live_sessions.get(session_id)
        if not previous or (data.get("updatedAt") or 0) > (previous.get("updatedAt") or 0):
            live_sessions[session_id] = data

    return live_sessions

def _load_live_claude_registry(session_id: str) -> Optional[Dict[str, Any]]:
    return _load_live_claude_registries().get(session_id)

def _load_cmux_targets() -> Dict[str, Dict[str, Any]]:
    state_file = Path.home() / "Library" / "Application Support" / "cmux" / "session-com.cmuxterm.app.json"
    if not state_file.exists():
        return {}

    try:
        state = json.loads(state_file.read_text())
    except (OSError, json.JSONDecodeError):
        return {}

    targets: Dict[str, Dict[str, Any]] = {}
    for window_index, window in enumerate(state.get("windows", []), 1):
        workspaces = window.get("tabManager", {}).get("workspaces", [])
        for workspace_index, workspace in enumerate(workspaces, 1):
            for panel in workspace.get("panels", []):
                terminal = panel.get("terminal") or {}
                agent = terminal.get("agent") or {}
                session_id = agent.get("sessionId")
                if not session_id:
                    continue

                panel_id = panel.get("id")
                if not panel_id:
                    continue

                targets[session_id] = {
                    "transport": "cmux",
                    "panel_id": panel_id,
                    "title": panel.get("title") or workspace.get("processTitle") or "",
                    "tty": terminal.get("ttyName") or panel.get("ttyName") or "",
                    "workspace_index": workspace_index,
                    "window_index": window_index,
                }

    return targets

def _load_cmux_target(session_id: str) -> Optional[Dict[str, Any]]:
    return _load_cmux_targets().get(session_id)

def _list_iterm_ttys() -> Dict[str, Dict[str, str]]:
    script = """
set collected to {}
tell application "iTerm2"
  repeat with w in windows
    repeat with t in tabs of w
      repeat with s in sessions of t
        set end of collected to ((tty of s) & " | " & (name of s))
      end repeat
    end repeat
  end repeat
end tell
set AppleScript's text item delimiters to linefeed
return collected as text
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            text=True,
            capture_output=True,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    if result.returncode != 0:
        return {}

    sessions: Dict[str, Dict[str, str]] = {}
    for line in result.stdout.splitlines():
        tty, separator, title = line.partition(" | ")
        if separator and tty:
            sessions[tty] = {"tty": tty, "title": title}
    return sessions

def _list_terminal_ttys() -> Dict[str, Dict[str, str]]:
    script = """
set collected to {}
tell application "Terminal"
  repeat with w in windows
    repeat with tb in tabs of w
      set end of collected to ((tty of tb) & " | " & (custom title of tb))
    end repeat
  end repeat
end tell
set AppleScript's text item delimiters to linefeed
return collected as text
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            text=True,
            capture_output=True,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    if result.returncode != 0:
        return {}

    sessions: Dict[str, Dict[str, str]] = {}
    for line in result.stdout.splitlines():
        tty, separator, title = line.partition(" | ")
        if separator and tty:
            sessions[tty] = {"tty": tty, "title": title}
    return sessions

def _resolve_live_terminal(session_id: str) -> Optional[Dict[str, Any]]:
    registry = _load_live_claude_registry(session_id)
    cmux_target = _load_cmux_target(session_id)
    if cmux_target:
        return {
            **cmux_target,
            "session_id": session_id,
            "registry": registry,
            "live": True,
        }

    if not registry:
        return None

    tty = registry.get("process", {}).get("tty")
    if not tty or tty == "??":
        return {
            "transport": "process",
            "session_id": session_id,
            "registry": registry,
            "live": True,
            "reason": "Claude process is live, but no terminal TTY is attached.",
        }

    tty_path = tty if tty.startswith("/dev/") else f"/dev/{tty}"
    iterm_sessions = _list_iterm_ttys()
    if tty_path in iterm_sessions:
        return {
            "transport": "iterm2",
            "session_id": session_id,
            "tty": tty_path,
            "title": iterm_sessions[tty_path].get("title", ""),
            "registry": registry,
            "live": True,
        }

    terminal_sessions = _list_terminal_ttys()
    if tty_path in terminal_sessions:
        return {
            "transport": "terminal",
            "session_id": session_id,
            "tty": tty_path,
            "title": terminal_sessions[tty_path].get("title", ""),
            "registry": registry,
            "live": True,
        }

    return {
        "transport": "tty",
        "session_id": session_id,
        "tty": tty_path,
        "registry": registry,
        "live": True,
        "reason": "Claude process is live, but the owning terminal app is not supported yet.",
    }

def _send_to_cmux(panel_id: str, message: str) -> None:
    script = """
on run argv
  set targetId to item 1 of argv
  set messageText to item 2 of argv
  tell application "cmux"
    set targetTerm to missing value
    repeat with term in terminals
      if id of term is targetId then
        set targetTerm to term
        exit repeat
      end if
    end repeat
    if targetTerm is missing value then error "target cmux terminal not found"
    input text messageText to targetTerm
    delay 0.05
    perform action "text:\\r" on targetTerm
  end tell
end run
"""
    result = subprocess.run(
        ["osascript", "-e", script, panel_id, message],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "cmux send failed")

def _send_to_iterm(tty: str, message: str) -> None:
    script = """
on run argv
  set targetTty to item 1 of argv
  set messageText to item 2 of argv
  tell application "iTerm2"
    set targetSession to missing value
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          if tty of s is targetTty then
            set targetSession to s
            exit repeat
          end if
        end repeat
        if targetSession is not missing value then exit repeat
      end repeat
      if targetSession is not missing value then exit repeat
    end repeat
    if targetSession is missing value then error "target iTerm2 session not found"
    tell targetSession to write text messageText
  end tell
end run
"""
    result = subprocess.run(
        ["osascript", "-e", script, tty, message],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "iTerm2 send failed")

def _send_to_terminal(tty: str, message: str) -> None:
    script = """
on run argv
  set targetTty to item 1 of argv
  set messageText to item 2 of argv
  tell application "Terminal"
    set targetTab to missing value
    repeat with w in windows
      repeat with tb in tabs of w
        if tty of tb is targetTty then
          set targetTab to tb
          exit repeat
        end if
      end repeat
      if targetTab is not missing value then exit repeat
    end repeat
    if targetTab is missing value then error "target Terminal tab not found"
    do script messageText in targetTab
  end tell
end run
"""
    result = subprocess.run(
        ["osascript", "-e", script, tty, message],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Terminal send failed")

def _public_terminal_target(target: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not target:
        return None

    registry = target.get("registry") or {}
    process = registry.get("process") or {}
    public = {
        "live": target.get("live", False),
        "transport": target.get("transport"),
        "title": target.get("title") or registry.get("name") or "",
        "tty": target.get("tty") or process.get("tty") or "",
        "pid": registry.get("pid"),
        "status": registry.get("status"),
        "updated_at": registry.get("updatedAt"),
        "reason": target.get("reason"),
    }
    if target.get("panel_id"):
        public["panel_id"] = target["panel_id"]
    return public

def _live_registry_revision(registries: Dict[str, Dict[str, Any]]) -> str:
    parts = []
    for session_id, registry in sorted(registries.items()):
        parts.append(
            ":".join([
                session_id,
                str(registry.get("pid") or ""),
                str(registry.get("status") or ""),
                str(registry.get("updatedAt") or ""),
            ])
        )
    return "|".join(parts)

def _build_live_terminal_index() -> Dict[str, Dict[str, Any]]:
    """Return a session-id keyed snapshot of all live Claude terminal targets."""
    registries = _load_live_claude_registries()
    targets: Dict[str, Dict[str, Any]] = {}

    for session_id, cmux_target in _load_cmux_targets().items():
        targets[session_id] = {
            **cmux_target,
            "session_id": session_id,
            "registry": registries.get(session_id),
            "live": True,
        }

    iterm_sessions: Optional[Dict[str, Dict[str, str]]] = None
    terminal_sessions: Optional[Dict[str, Dict[str, str]]] = None

    for session_id, registry in registries.items():
        if session_id in targets:
            continue

        tty = registry.get("process", {}).get("tty")
        if not tty or tty == "??":
            targets[session_id] = {
                "transport": "process",
                "session_id": session_id,
                "registry": registry,
                "live": True,
                "reason": "Claude process is live, but no terminal TTY is attached.",
            }
            continue

        tty_path = tty if tty.startswith("/dev/") else f"/dev/{tty}"

        if iterm_sessions is None:
            iterm_sessions = _list_iterm_ttys()
        if tty_path in iterm_sessions:
            targets[session_id] = {
                "transport": "iterm2",
                "session_id": session_id,
                "tty": tty_path,
                "title": iterm_sessions[tty_path].get("title", ""),
                "registry": registry,
                "live": True,
            }
            continue

        if terminal_sessions is None:
            terminal_sessions = _list_terminal_ttys()
        if tty_path in terminal_sessions:
            targets[session_id] = {
                "transport": "terminal",
                "session_id": session_id,
                "tty": tty_path,
                "title": terminal_sessions[tty_path].get("title", ""),
                "registry": registry,
                "live": True,
            }
            continue

        targets[session_id] = {
            "transport": "tty",
            "session_id": session_id,
            "tty": tty_path,
            "registry": registry,
            "live": True,
            "reason": "Claude process is live, but the owning terminal app is not supported yet.",
        }

    return {
        session_id: public_target
        for session_id, target in targets.items()
        if (public_target := _public_terminal_target(target))
    }

def _annotate_projects_with_live_targets(
    projects: List[Dict[str, Any]],
    live_index: Dict[str, Dict[str, Any]],
) -> None:
    for project in projects:
        live_count = 0
        for session in project.get("sessions", []):
            live_terminal = live_index.get(session.get("id"))
            session["live_terminal"] = live_terminal
            if live_terminal and live_terminal.get("live"):
                live_count += 1
        project["live_session_count"] = live_count

def _filter_projects_to_matching_sessions(
    projects: List[Dict[str, Any]],
    search_results: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return only projects/sessions that produced global search matches."""
    if not search_results:
        return projects

    matching_sessions = {
        (match["project_name"], match["session_id"])
        for match in search_results.get("matching_sessions", [])
    }
    if not matching_sessions:
        return []

    first_match_lines = {}
    for result in search_results.get("results", []):
        key = (result["project_name"], result["session_id"])
        first_match_lines.setdefault(key, result["line_number"])

    filtered_projects = []
    for project in projects:
        sessions = []
        for session in project.get("sessions", []):
            key = (project["name"], session["id"])
            if key not in matching_sessions:
                continue

            session_entry = {**session}
            if key in first_match_lines:
                session_entry["search_line"] = first_match_lines[key]
            sessions.append(session_entry)

        if not sessions:
            continue

        filtered_project = {
            **project,
            "sessions": sessions,
            "session_count": len(sessions),
            "live_session_count": sum(
                1 for session in sessions
                if session.get("live_terminal") and session["live_terminal"].get("live")
            ),
        }
        filtered_projects.append(filtered_project)

    return filtered_projects

# Routes
@app.get("/", response_class=HTMLResponse)
async def root(
    request: Request,
    q: Optional[str] = Query(None),
    project_filter: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    has_code: Optional[str] = Query(None),
    has_tools: Optional[str] = Query(None),
    has_errors: Optional[str] = Query(None),
    has_file_edits: Optional[str] = Query(None),
):
    """Main page showing all projects"""
    parser = get_parser()
    all_projects = parser.get_projects_with_sessions()
    live_index = _build_live_terminal_index()
    _annotate_projects_with_live_targets(all_projects, live_index)
    global_search = (q or "").strip()
    search_filters = build_search_filters(
        project_filter,
        role,
        date_from,
        date_to,
        has_code,
        has_tools,
        has_errors,
        has_file_edits,
    )
    global_search_results = (
        parser.search_messages(global_search, filters=search_filters)
        if global_search else None
    )
    projects = (
        _filter_projects_to_matching_sessions(all_projects, global_search_results)
        if global_search else all_projects
    )
    recent_sessions = [
        {
            **session,
            "project_name": project["name"],
            "project_display_name": project["display_name"],
        }
        for project in projects
        for session in project["sessions"]
    ]
    recent_sessions = sorted(
        recent_sessions,
        key=lambda session: session["modified"],
        reverse=True,
    )

    return templates.TemplateResponse("index.html", {
        "request": request,
        "projects": projects,
        "filter_projects": all_projects,
        "recent_sessions": recent_sessions,
        "live_session_count": sum(project.get("live_session_count", 0) for project in projects),
        "global_search": global_search,
        "global_search_results": global_search_results,
        "search_filters": search_filters,
    })

@app.get("/v/{session_ref}")
@app.get("/s/{session_ref}")
async def session_shortcut(session_ref: str):
    """Redirect a short or full Claude session id to the viewer homepage."""
    parser = get_parser()
    projects_path = Path(parser.claude_projects_path)
    matches = []

    if projects_path.exists():
        for project_entry in projects_path.iterdir():
            if not project_entry.is_dir():
                continue

            for session_file in project_entry.glob("*.jsonl"):
                session_id = session_file.stem
                if session_id == session_ref or session_id.startswith(session_ref):
                    matches.append((project_entry.name, session_id))

    if not matches:
        raise HTTPException(status_code=404, detail="Session not found")

    exact_matches = [match for match in matches if match[1] == session_ref]
    if exact_matches:
        matches = exact_matches

    unique_matches = sorted(set(matches))
    if len(unique_matches) > 1:
        raise HTTPException(status_code=409, detail="Session prefix is ambiguous")

    project_name, session_id = unique_matches[0]
    return RedirectResponse(
        url=f"/?{urlencode({'project': project_name, 'session': session_id})}",
        status_code=302,
    )

@app.get("/api/qr.svg")
async def qr_svg(data: str = Query(..., min_length=1, max_length=1024)):
    """Return a local SVG QR code for a short URL."""
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="QR support is not installed") from exc

    qr_image = qrcode.make(
        data,
        image_factory=SvgPathImage,
        box_size=6,
        border=2,
    )
    output = io.BytesIO()
    qr_image.save(output)
    return Response(
        content=output.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )

@app.get("/api/share-url/{session_id}")
async def get_share_url(request: Request, session_id: str):
    """Return the current LAN share URL for a session."""
    share_url = _session_share_url(request, session_id)
    return {
        "url": share_url,
        "qr_src": f"/api/qr.svg?data={quote(share_url, safe='')}",
    }

@app.get("/api/projects", response_model=List[Project])
async def get_projects():
    """API endpoint to get all projects"""
    parser = get_parser()
    return parser.get_projects()

@app.get("/project/{project_name}", response_class=HTMLResponse)
async def project_view(request: Request, project_name: str):
    """Project page showing all sessions"""
    parser = get_parser()
    sessions = parser.get_sessions(project_name)
    if not sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return templates.TemplateResponse("project_view.html", {
        "request": request,
        "project_name": project_name,
        "display_name": parser._format_project_name(project_name),
        "sessions": sessions
    })

@app.get("/api/sessions/{project_name}", response_model=List[Session])
async def get_sessions(project_name: str):
    """API endpoint to get sessions for a project"""
    parser = get_parser()
    sessions = parser.get_sessions(project_name)
    if not sessions:
        raise HTTPException(status_code=404, detail="Project not found")
    return sessions

async def render_conversation_template(
    request: Request,
    project_name: str,
    session_id: str,
    page: Optional[int],
    per_page: int,
    search: Optional[str],
    message_type: Optional[str],
    highlight: Optional[str] = None,
    target_line: Optional[int] = None,
    show_tools: bool = False,
    embedded: bool = False
):
    """Render a conversation in either full-page or embedded mode."""
    parser = get_parser()
    conversation = parser.get_conversation(
        project_name, session_id, page, per_page, search, message_type, target_line, show_tools
    )

    if not conversation["messages"] and (page is None or page == 1):
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Render markdown content
    for message in conversation["messages"]:
        if message.get("content"):
            rendered_content = render_markdown_with_code(message["content"])
            message["rendered_content"] = highlight_rendered_search(rendered_content, highlight or search)

    return templates.TemplateResponse("conversation.html", {
        "request": request,
        "project_name": project_name,
        "session_id": session_id,
        "conversation": conversation,
        "live_terminal": _public_terminal_target(_resolve_live_terminal(session_id)),
        "share_url": _session_share_url(request, session_id),
        "search": search,
        "highlight": highlight,
        "message_type": message_type,
        "target_line": target_line,
        "show_tools": show_tools,
        "display_name": parser._format_project_name(project_name),
        "embedded": embedded,
    })

@app.get("/conversation/{project_name}/{session_id}", response_class=HTMLResponse)
async def conversation_view(
    request: Request,
    project_name: str,
    session_id: str,
    page: Optional[int] = Query(None, ge=1),
    per_page: int = Query(50, le=200, ge=10),
    search: Optional[str] = Query(None),
    message_type: Optional[str] = Query(None),
    highlight: Optional[str] = Query(None),
    line: Optional[int] = Query(None, ge=1),
    show_tools: bool = Query(False),
    embedded: bool = Query(False)
):
    """Conversation viewer page"""
    return await render_conversation_template(
        request, project_name, session_id, page, per_page, search, message_type, highlight, line, show_tools, embedded
    )

@app.get("/embedded/conversation/{project_name}/{session_id}", response_class=HTMLResponse)
async def embedded_conversation_view(
    request: Request,
    project_name: str,
    session_id: str,
    page: Optional[int] = Query(None, ge=1),
    per_page: int = Query(50, le=200, ge=10),
    search: Optional[str] = Query(None),
    message_type: Optional[str] = Query(None),
    highlight: Optional[str] = Query(None),
    line: Optional[int] = Query(None, ge=1),
    show_tools: bool = Query(False)
):
    """Conversation viewer for the homepage right pane."""
    return await render_conversation_template(
        request, project_name, session_id, page, per_page, search, message_type, highlight, line, show_tools, True
    )

@app.get("/api/conversation/{project_name}/{session_id}", response_model=ConversationResponse)
async def get_conversation(
    project_name: str,
    session_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=200, ge=10),
    search: Optional[str] = Query(None),
    message_type: Optional[str] = Query(None),
    line: Optional[int] = Query(None, ge=1),
    show_tools: bool = Query(False)
):
    """API endpoint to get conversation data"""
    parser = get_parser()
    conversation = parser.get_conversation(
        project_name, session_id, page, per_page, search, message_type, line, show_tools
    )
    
    return ConversationResponse(**conversation)

@app.get("/api/activity")
async def get_activity(
    project: Optional[str] = Query(None),
    session: Optional[str] = Query(None),
):
    """Cheap JSONL activity snapshot for low-CPU UI refresh polling."""
    parser = get_parser()
    projects_path = Path(parser.claude_projects_path)
    total_sessions = 0
    total_size = 0
    latest_mtime_ns = 0
    project_count = 0
    latest_session = None
    active_session = None
    live_registries = _load_live_claude_registries()
    active_registry = live_registries.get(session) if session else None
    active_live_terminal = None
    if active_registry:
        active_live_terminal = {
            "live": True,
            "pid": active_registry.get("pid"),
            "status": active_registry.get("status"),
            "updated_at": active_registry.get("updatedAt"),
            "title": active_registry.get("name") or "",
        }
    live_revision = _live_registry_revision(live_registries)

    if projects_path.exists():
        for project_entry in projects_path.iterdir():
            if not project_entry.is_dir():
                continue

            project_count += 1
            for session_entry in project_entry.glob("*.jsonl"):
                try:
                    stat = session_entry.stat()
                except OSError:
                    continue

                total_sessions += 1
                total_size += stat.st_size
                if stat.st_mtime_ns > latest_mtime_ns:
                    latest_mtime_ns = stat.st_mtime_ns
                    latest_session = {
                        "project": project_entry.name,
                        "session": session_entry.stem,
                        "modified_ns": stat.st_mtime_ns,
                        "size": stat.st_size,
                    }

                if project_entry.name == project and session_entry.stem == session:
                    active_session = {
                        "project": project_entry.name,
                        "session": session_entry.stem,
                        "modified_ns": stat.st_mtime_ns,
                        "size": stat.st_size,
                        "revision": f"{stat.st_mtime_ns}:{stat.st_size}",
                    }

    return {
        "project_count": project_count,
        "total_sessions": total_sessions,
        "latest_mtime_ns": latest_mtime_ns,
        "total_size": total_size,
        "revision": f"{project_count}:{total_sessions}:{latest_mtime_ns}:{total_size}:{live_revision}",
        "latest_session": latest_session,
        "active_session": active_session,
        "live_revision": live_revision,
        "active_live_terminal": active_live_terminal,
    }

@app.post("/api/live/start")
async def start_live_claude(request: LiveClaudeRequest):
    """Start a Claude CLI turn and stream its partial message events."""
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    job_id = str(uuid.uuid4())
    session_id = request.session_id.strip() if request.session_id else None
    initial_session_id = session_id or str(uuid.uuid4())
    job = {
        "id": job_id,
        "prompt": prompt,
        "requested_session_id": session_id,
        "session_id": initial_session_id,
        "project_name": get_current_project_name(),
        "status": "queued",
        "returncode": None,
        "assistant_text": "",
        "events": [],
        "condition": threading.Condition(),
        "created_at": time.time(),
    }

    with LIVE_JOBS_LOCK:
        LIVE_JOBS[job_id] = job

    thread = threading.Thread(target=_run_live_claude_job, args=(job,), daemon=True)
    job["thread"] = thread
    thread.start()

    return {
        "job_id": job_id,
        "session_id": job["session_id"],
        "project_name": job["project_name"],
        "stream_url": f"/api/live/{job_id}/events",
    }

@app.get("/api/session-target/{session_id}")
async def get_session_target(session_id: str):
    """Resolve a Claude session to the terminal we can send input to, if live."""
    target = _resolve_live_terminal(session_id)
    if not target:
        return {
            "live": False,
            "session_id": session_id,
            "reason": "No live Claude process was found for this session.",
        }

    return {
        "session_id": session_id,
        **(_public_terminal_target(target) or {}),
    }

@app.post("/api/session-send")
async def send_session_message(request: SessionSendRequest):
    """Send text to the live terminal currently running a Claude session."""
    message = request.message.strip()
    session_id = request.session_id.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    if not session_id:
        raise HTTPException(status_code=400, detail="Session ID is required")

    target = _resolve_live_terminal(session_id)
    if not target:
        raise HTTPException(status_code=409, detail="No live Claude terminal was found for this session")

    transport = target.get("transport")
    try:
        if transport == "cmux":
            _send_to_cmux(target["panel_id"], message)
        elif transport == "iterm2":
            _send_to_iterm(target["tty"], message)
        elif transport == "terminal":
            _send_to_terminal(target["tty"], message)
        else:
            reason = target.get("reason") or "This terminal type is not supported yet"
            raise HTTPException(status_code=409, detail=reason)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "ok": True,
        "session_id": session_id,
        "project_name": request.project_name,
        "target": _public_terminal_target(target),
    }

@app.get("/api/live/{job_id}/events")
async def stream_live_claude(job_id: str):
    """SSE stream for a running live Claude job."""
    with LIVE_JOBS_LOCK:
        job = LIVE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Live job not found")

    async def event_generator():
        cursor = 0
        while True:
            with job["condition"]:
                events = job["events"][cursor:]
                cursor += len(events)
                done = job["status"] in {"done", "failed"} and not events

            for index, event in enumerate(events, cursor - len(events)):
                yield _format_sse(event["event"], event["data"], index)

            if done:
                break

            await asyncio.sleep(0.1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    parser = get_parser()
    claude_path = os.environ.get("CLAUDE_PROJECTS_PATH", "Not set")
    projects_exist = os.path.exists(claude_path)
    
    return {
        "status": "healthy",
        "version": "1.0.0",
        "claude_projects_path": claude_path,
        "projects_directory_exists": projects_exist,
        "projects_count": len(parser.get_projects()) if projects_exist else 0
    }
