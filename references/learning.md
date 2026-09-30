# Learning hook (opt-in)

An optional hook that turns corrections from sessions into setup suggestions the user approves later. It **never** edits CLAUDE.md, rules, or settings on its own. Everything goes through `/claude-setup review`.

## Contents
- [How it works](#how-it-works)
- [Turning it on](#turning-it-on)
- [Review](#review)
- [Turning it off](#turning-it-off)
- [Facts it relies on](#facts-it-relies-on)

## How it works

`scripts/learn.py` (stdlib only; `install` copies it into a hooks folder).

1. **Prefilter (no model).** Reads only text the user typed, skipping Claude's replies, tool output, pasted code blocks, quoted lines, and injected hook or system text. It flags correction phrases ("don't", "always", "from now on", "no, …"), interrupts, and rejected tool calls, plus the message right after an interrupt or rejection. It keeps a byte offset per transcript, so nothing is analyzed twice.
2. **Model (Sonnet only).** Runs only if the prefilter found something new. `claude -p --json-schema`, no tools, a short system prompt, `--max-budget-usd` (default $0.25). It gets the flagged excerpts, the current CLAUDE.md files, open suggestions (so it can say `same_as`), and rejected ones (never re-proposed).
3. **Merge script (the only writer).** Validates every item against the schema, drops malformed ones and one-time instructions, dedupes, and renders `.claude/setup-suggestions.md` the same way every time. The machine state is a JSON block at the bottom of that file.

**Kinds:** add, change (quotes the current line), remove, conflict (a correction that contradicts an existing line; never an add).
**Strength:** strong (explicit always/never/from now on, repeated, interrupted over, or any conflict) goes straight to *pending*. Weak goes to *watching* and becomes pending when a second session shows it. Weak items unseen for 30 days expire (`--expire-days 0` turns that off).
**Reconcile:** before every render and at session start, items already reflected in the target file are marked done, so every repo's file stays current.
**Notice:** at session start, if anything is pending, Claude ends its first reply with one line, e.g. "3 setup suggestions pending - run /claude-setup review". The count only, once per session.

| | Local | Cloud |
|---|---|---|
| When | SessionEnd hands off to a detached background process (the hook itself returns in under 0.1 s) | Stop, at the end of a turn, only when there's something new (containers are reclaimed without warning) |
| Installed in | `~/.claude/settings.json` (all repos) | the repo's `.claude/settings.json`, committed |
| Suggestions file | Kept out of git via `.git/info/exclude` (the repo's `.gitignore` is untouched) | Committed: the hook asks Claude to commit and push it on the current branch |
| Runs for | You | Only your account (`--only-account` tag), and only in cloud sessions |

## Turning it on

Only when the user asks. Before installing, say plainly:
- It calls Sonnet on sessions where the prefilter finds a correction. Tested cost is about $0.01-0.03 per run, capped at 10 runs a day and $0.25 per run, and it uses their plan's usage.
- It reads only what they typed, plus interrupts and rejections, and it writes suggestions to `.claude/setup-suggestions.md`.
- **In the cloud:** that file is committed and pushed. **For a shared team repo, warn** that their suggestions (short paraphrases of their corrections) become visible to teammates, and that the hook script and settings entry are committed too (they're inert for teammates).
- There's no cheaper-model option on purpose. In testing, the smaller model was noisier (it kept one-time instructions) and wasn't cheaper.

Then:
- Local: `python "${CLAUDE_SKILL_DIR}/scripts/learn.py" install --scope user`
- Cloud (per repo): `python3 "${CLAUDE_SKILL_DIR}/scripts/learn.py" install --scope project`, then commit `.claude/settings.json` and `.claude/hooks/claude-setup-learn.py`.

Options go on the installed hook commands: `--expire-days N`, `--daily-cap N`, `--budget USD`. Settings changes need a restart (or `/hooks` review) to take effect.

## Review

`/claude-setup review`:
1. `python learn.py reconcile` (marks already-done items and prints the open ones as JSON).
2. Go through pending items first, strongest first. Show each with its evidence and ask: approve, edit, or reject. Offer "approve all strong" for long lists.
3. On approve, make the change at its destination, following the rest of this skill: CLAUDE.md lines per [claude-md.md](claude-md.md), hooks per [safety.md#hooks](safety.md#hooks), skills per [extensions.md](extensions.md). Then `learn.py resolve <id> --status applied`. For a conflict, ask which side wins before editing.
4. On reject: `learn.py resolve <id> --status rejected`. It's remembered and won't come back.
5. **Global items in a cloud session** stay pending (the script refuses `applied` there). Say they'll be offered in the next local session.
6. Then mention the watching items briefly; the user can promote or reject them too.

## Turning it off

`learn.py uninstall --scope user|project` removes only its own hook entries and the copied script, keeping every other setting. It leaves the suggestions file in place; offer to delete it.

## Facts it relies on

Measured on Claude Code 2.1.285 (2026-09-30):
- SessionEnd hooks are killed after about 1.5-3.5 s, even on a clean exit, which is too short for a model call. The detached process outlives it on a laptop but dies with a cloud container.
- Hooks on the same event run in parallel.
- `--bare` only accepts an API key, so subscription users can't use it. The hook uses the normal CLI with a short system prompt instead.
- Cloud sessions ship their own Stop hook that blocks while files are uncommitted or unpushed, and it expects Claude-signed commits. That's why Claude commits the suggestions file, not the hook.
- The session-start notice arrives as part of Claude's reply, so it shows in the app, on the web, and in the terminal.

Debugging: `~/.claude/claude-setup/learn.log` records each run (signal counts, cost, discarded output). `learn.py prefilter --all-projects` shows how many recent sessions would have called the model, which is the best cost estimate.
