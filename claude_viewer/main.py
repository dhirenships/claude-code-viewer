"""FastAPI main application for Claude Code Viewer."""

import asyncio
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from .utils.jsonl_parser import JSONLParser
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound
import re

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
    title="Claude Code Conversation Viewer",
    description="View, search and browse Claude Code conversation history",
    version="1.0.0"
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
                linenos=False
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
    
    # Convert markdown to HTML
    html = markdown.markdown(text, extensions=['tables', 'fenced_code'])
    
    return html

def get_current_project_name() -> str:
    """Return Claude's project directory name for this viewer process cwd."""
    cwd = os.getcwd().rstrip(os.sep)
    return "-" + cwd.lstrip(os.sep).replace(os.sep, "-")

def _live_conversation_url(project_name: str, session_id: str) -> str:
    return f"/conversation/{project_name}/{session_id}?embedded=true"

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
    projects = parser.get_projects_with_sessions()
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
        "recent_sessions": recent_sessions,
        "global_search": global_search,
        "global_search_results": global_search_results,
        "search_filters": search_filters,
    })

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
            message["rendered_content"] = render_markdown_with_code(message["content"])

    return templates.TemplateResponse("conversation.html", {
        "request": request,
        "project_name": project_name,
        "session_id": session_id,
        "conversation": conversation,
        "search": search,
        "message_type": message_type,
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
    line: Optional[int] = Query(None, ge=1),
    show_tools: bool = Query(False),
    embedded: bool = Query(False)
):
    """Conversation viewer page"""
    return await render_conversation_template(
        request, project_name, session_id, page, per_page, search, message_type, line, show_tools, embedded
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
    line: Optional[int] = Query(None, ge=1),
    show_tools: bool = Query(False)
):
    """Conversation viewer for the homepage right pane."""
    return await render_conversation_template(
        request, project_name, session_id, page, per_page, search, message_type, line, show_tools, True
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
