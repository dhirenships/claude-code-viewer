# cocoview

A web UI for browsing your [Claude Code](https://docs.anthropic.com/en/docs/claude-code) conversation history.

Search across sessions, read syntax-highlighted code, inspect diffs and tool calls, and watch live Claude sessions update in real time.

![dashboard](screenshots/dashboard-dark.png)

## Install

```bash
pip install cocoview
```

## Usage

```bash
cocoview
```

Opens at [localhost:6300](http://localhost:6300). It reads from `~/.claude/projects/` where Claude Code stores conversation JSONL files.

### Options

```
cocoview --port 8080                  # custom port
cocoview --host 0.0.0.0              # expose on LAN
cocoview --projects-path /other/path  # custom Claude projects dir
cocoview --no-statusline              # skip Claude statusline integration
```

## Features

**Session browser** -- All your Claude Code projects and sessions in a sidebar, sorted by recency. Click to read any conversation.

**Full-text search** -- Search across every session. Filter by project, role, date range, or content type (code, errors, tool use, file edits).

![light mode](screenshots/conversation-light.png)

**Syntax highlighting** -- Code blocks render with language detection and proper highlighting via Pygments.

**Diff viewer** -- File edits from Claude's Edit tool display as green/red line diffs, so you can see exactly what changed.

![diffs and tool output](screenshots/code-view.png)

**Live sessions** -- If Claude Code is running in a terminal, cocoview detects it and streams updates. Works with iTerm2, Terminal.app, and [cmux](https://cmux.app). You can send messages to live sessions directly from the viewer.

**Dark / light theme** -- Toggle in the top-right corner. Preference is saved.

**QR code sharing** -- Each session gets a QR code link for quick access from your phone over LAN.

**Mobile responsive** -- Works on phones and tablets.

## How it works

Claude Code stores every conversation as a JSONL file in `~/.claude/projects/<project-hash>/`. Each line is a JSON object representing a message, tool call, or tool result.

cocoview parses these files, indexes them for search, and serves a web UI with FastAPI.

## Development

```bash
git clone https://github.com/anthropics/cocoview.git
cd cocoview
pip install -e .
cocoview
```

The server auto-reloads on file changes during development.

## Requirements

- Python 3.8+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (to generate conversation history)

## License

MIT
