# cocomon launch plan

## Where to post

| Platform | Audience | Why | Effort |
|----------|----------|-----|--------|
| r/ClaudeAI | Claude Code users | Direct target audience, high engagement | Low |
| r/LocalLLaMA | Tool-builders, local-first crowd | Appreciates self-hosted dev tools | Low |
| Hacker News (Show HN) | Devtools audience | High visibility, drives GitHub stars | Medium |
| X/Twitter | Claude Code community, Anthropic devrel | Fast reach, taggable | Low |
| Claude Code Discord | Core power users | Niche but high-intent | Low |
| Product Hunt | Broader dev audience | Launch visibility, social proof | Medium |

## Posting order

1. **Day 1**: r/ClaudeAI + X/Twitter (warm audience, fast feedback loop)
2. **Day 1-2**: Claude Code Discord
3. **Day 2-3**: Show HN (after incorporating any early feedback)
4. **Day 3-4**: r/LocalLLaMA
5. **Week 2**: Product Hunt (only if traction builds from earlier posts)

## Posts

### r/ClaudeAI

**Title**: cocomon -- a local command center for your Claude Code sessions

**Body**:

I built a web viewer for Claude Code conversation history. Search across all your sessions, see diffs and tool calls with syntax highlighting, and send messages to live Claude Code sessions from your phone over LAN.

```
pip install cocomon && cocomon
```

Features:
- Full-text search across every session with filters (project, role, date, code/errors/tools/edits)
- Syntax-highlighted code blocks and file-edit diffs
- Live session detection + message sending (iTerm2, Terminal.app, cmux)
- LAN sharing with QR codes -- control Claude from your phone
- Dark mode, mobile responsive

GitHub: https://github.com/gdagitrep/claude-code-viewer

**Attachments**: demo-desktop.gif

---

### Show HN

**Title**: Show HN: Cocoview -- browse and search your Claude Code session history

**Body**:

I use Claude Code daily and wanted a way to search old sessions, review diffs, and control live sessions from my phone. cocomon is a local web UI that reads from `~/.claude/projects/` and serves everything with FastAPI.

- Full-text search across all sessions with filters
- Syntax-highlighted code and line-level diffs for file edits
- Live session status and message sending via terminal integration (iTerm2, Terminal.app, cmux)
- LAN sharing with QR codes for phone access
- Mobile responsive, dark mode

```
pip install cocomon
```

Local-first: binds to localhost by default. Use `--host 0.0.0.0` on trusted networks for LAN access.

https://github.com/gdagitrep/claude-code-viewer

---

### X/Twitter

**Thread**:

> 1/ Built cocomon -- a local web UI for Claude Code sessions.
>
> Search past conversations. Inspect diffs. Send messages to live sessions from your phone.
>
> `pip install cocomon`
>
> [attach demo-desktop.gif]

> 2/ Full-text search across every session. Filter by project, role, date, code, errors, tools, edits.
>
> Dark mode. Mobile responsive. Works on your LAN -- scan the QR code from your phone.
>
> [attach demo-mobile.gif]

> 3/ GitHub: https://github.com/gdagitrep/claude-code-viewer
>
> Tag: @AnthropicAI @alexalbert__ @amanrsanger

---

### Claude Code Discord

**Message**:

Built a local web viewer for Claude Code sessions called cocomon. Lets you search across all your past conversations, inspect diffs and tool calls, and send messages to live sessions from your phone over LAN.

`pip install cocomon`

GitHub: https://github.com/gdagitrep/claude-code-viewer

Works with iTerm2, Terminal.app, and cmux for live session control. Mobile responsive so you can use it from your phone while Claude runs on your machine.

[attach demo-desktop.gif]

---

### r/LocalLLaMA

**Title**: cocomon -- local web UI for browsing Claude Code session history

**Body**:

Not an LLM project per se, but relevant for anyone using Claude Code as a coding agent. cocomon is a self-hosted web viewer that reads Claude Code's conversation JSONL files and serves a searchable UI with FastAPI.

- Search across all sessions with filters
- Syntax-highlighted code and diffs
- Live session control from your browser or phone over LAN
- Fully local, no cloud, no telemetry

```
pip install cocomon && cocomon
```

GitHub: https://github.com/gdagitrep/claude-code-viewer

[attach demo-desktop.gif]

---

### Product Hunt

**Tagline**: A local command center for your Claude Code sessions

**Description**: Search past conversations, inspect code diffs, watch live session status, and send messages to active Claude Code sessions from your desktop or phone over your local network. Fully local, no cloud required.

**Attachments**: demo-desktop.gif, demo-mobile.gif, screenshots

## Pre-launch checklist

- [ ] PyPI package published and installable (`pip install cocomon`)
- [ ] GitHub repo public with README, screenshots, GIFs
- [ ] License file present
- [ ] `cocomon` command works on fresh install
- [ ] Test on macOS + Linux
- [ ] Test mobile view on real iPhone/Android
- [ ] Record a short video (optional, for Product Hunt)
