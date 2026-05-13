# Live Claude Streaming Concept

Status: implemented behind a hidden UI entry point.

## Goal

Show assistant text while Claude is still generating, then fall back to the saved JSONL session once Claude finishes the turn.

## Key Finding

Claude session JSONL files do not persist token deltas as they arrive. They receive completed assistant rows after the turn is done.

Live streaming requires launching Claude from the viewer and reading process stdout:

```bash
claude -p --verbose --output-format stream-json --include-partial-messages ...
```

The useful live event is:

```text
type == "stream_event"
event.type == "content_block_delta"
event.delta.type == "text_delta"
```

## Current Architecture

The code is kept in place for future use:

- `POST /api/live/start` starts a Claude CLI job.
- `GET /api/live/{job_id}/events` streams parsed events over SSE.
- `cocomon/static/js/app.js` appends `delta` events into a temporary live assistant message.
- When the job emits `done`, the UI loads the persisted conversation iframe using the returned `conversation_url`.
- Follow-up prompts can reuse the same session with `--resume`.

## UI State

The home-page Live Claude form is hidden in `cocomon/templates/index.html`.

To re-enable:

1. Remove `live-claude-disabled` from `.top-tools`.
2. Remove `hidden aria-hidden="true"` from `#live-claude-form`.

The supporting backend, JavaScript, and CSS can remain unchanged.

## Behavior Split

- Existing sidebar sessions read completed messages from JSONL only.
- Live Claude prompts started by the viewer stream stdout deltas in real time.
- After each live turn completes, JSONL becomes the source of truth again.

## Verified Experiment

Prompt:

```text
Count down from 1000 to 1, one number per line.
```

Observed through the viewer SSE endpoint and GStack browser:

- Live panel showed partial output during generation.
- The assistant text was visible while still running.
- On completion, the iframe switched to the persisted session.
- Persisted assistant message contained all 1000 number lines.
