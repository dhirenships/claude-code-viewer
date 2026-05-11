"""Install Claude Code statusline integration for Claude Viewer."""

import json
import shlex
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


STATUSLINE_SCRIPT = """#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path


def color(code, text):
    return f"\\033[{code}m{text}\\033[0m" if text else ""


def get_nested(data, *keys, default=""):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def git_branch(cwd):
    if not cwd:
        return ""
    try:
        result = subprocess.run(
            ["git", "-c", "gc.auto=0", "branch", "--show-current"],
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=0.5,
            check=False,
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        data = {}

    cwd = get_nested(data, "workspace", "current_dir")
    sid = get_nested(data, "session_id")
    model = get_nested(data, "model", "display_name")
    pct = get_nested(data, "context_window", "used_percentage", default=0)
    try:
        pct_int = int(pct)
    except (TypeError, ValueError):
        pct_int = 0

    viewer_base = os.environ.get("CLAUDE_VIEWER_BASE_URL", "http://127.0.0.1:6300").rstrip("/")
    viewer_url = f"{viewer_base}/v/{sid[:8]}" if sid else ""

    if pct_int >= 80:
        pct_color = "31"
    elif pct_int >= 50:
        pct_color = "33"
    else:
        pct_color = "32"

    parts = []
    if viewer_url:
        parts.append(color("34", viewer_url))
    if model:
        parts.append(color("1;35", model))
    parts.append(color(pct_color, f"ctx:{pct_int}%"))
    if sid:
        parts.append(color("35", sid[:8]))

    dirname = Path(cwd).name if cwd else ""
    if dirname:
        parts.append(color("36", dirname))

    branch = git_branch(cwd)
    if branch:
        parts.append(color("1;34", "git:(") + color("31", branch) + color("1;34", ")"))

    print(" ".join(parts), end="")


if __name__ == "__main__":
    main()
"""

SHARE_BASE_URL_FILE = Path.home() / ".claude" / "claude-viewer-share-base-url"


@dataclass
class StatuslineInstallResult:
    installed: bool
    script_path: Path
    settings_path: Path
    command: str
    backup_path: Optional[Path] = None
    message: str = ""


def get_lan_ip() -> Optional[str]:
    """Return the Mac's LAN IP, preferring Wi-Fi interface en0."""
    for args in (
        ["ipconfig", "getifaddr", "en0"],
        ["ipconfig", "getifaddr", "en1"],
    ):
        try:
            result = subprocess.run(
                args,
                text=True,
                capture_output=True,
                timeout=1,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        ip = result.stdout.strip()
        if result.returncode == 0 and ip:
            return ip

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def viewer_base_url_for_host(host: str, port: int) -> str:
    """Return the URL users should open for the given bind host and port."""
    display_host = host.strip() or "127.0.0.1"
    if display_host in {"0.0.0.0", "::"}:
        display_host = get_lan_ip() or "127.0.0.1"
    elif display_host == "::1":
        display_host = "[::1]"
    elif ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    return f"http://{display_host}:{port}"


def localhost_base_url_for_port(port: int) -> str:
    """Return the stable local-only URL for Claude's terminal statusline."""
    return f"http://localhost:{port}"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _backup(path: Path) -> Path:
    backup_path = path.with_name(f"{path.name}.claude-viewer-backup-{_timestamp()}")
    shutil.copy2(path, backup_path)
    return backup_path


def install_claude_statusline(
    viewer_base_url: str,
    claude_dir: Optional[Path] = None,
) -> StatuslineInstallResult:
    """Install or update Claude settings so its statusline links to this viewer."""
    claude_dir = (claude_dir or (Path.home() / ".claude")).expanduser()
    claude_dir.mkdir(parents=True, exist_ok=True)

    script_path = claude_dir / "claude-viewer-statusline.py"
    settings_path = claude_dir / "settings.json"
    command = (
        f"CLAUDE_VIEWER_BASE_URL={shlex.quote(viewer_base_url.rstrip('/'))} "
        f"python3 {shlex.quote(str(script_path))}"
    )

    desired_settings = {
        "type": "command",
        "command": command,
        "padding": 2,
    }

    backup_path = None
    script_changed = not script_path.exists() or script_path.read_text() != STATUSLINE_SCRIPT
    if script_changed:
        if script_path.exists():
            _backup(script_path)
        script_path.write_text(STATUSLINE_SCRIPT)
        script_path.chmod(0o755)

    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not parse {settings_path}: {exc}") from exc
    else:
        settings = {}

    current_statusline = settings.get("statusLine")
    settings_changed = current_statusline != desired_settings
    if settings_changed:
        if settings_path.exists():
            backup_path = _backup(settings_path)
        settings["statusLine"] = desired_settings
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    installed = script_changed or settings_changed
    if installed:
        message = f"Claude statusline links installed for {viewer_base_url.rstrip('/')}"
    else:
        message = "Claude statusline links already installed"

    return StatuslineInstallResult(
        installed=installed,
        script_path=script_path,
        settings_path=settings_path,
        command=command,
        backup_path=backup_path,
        message=message,
    )


def write_share_base_url(viewer_base_url: str, path: Path = SHARE_BASE_URL_FILE) -> None:
    """Persist the current LAN/share base URL for all local viewer processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(viewer_base_url.rstrip("/") + "\n")


def read_share_base_url(path: Path = SHARE_BASE_URL_FILE) -> Optional[str]:
    """Read the current LAN/share base URL written by the CLI, if present."""
    try:
        value = path.read_text().strip()
    except OSError:
        return None
    return value or None
