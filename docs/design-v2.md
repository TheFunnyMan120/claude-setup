# Claude Setup v2: design

Status: built in v2.0.0 (`scripts/learn.py`, `references/learning.md`, `references/global.md`). This doc records the decisions and the test results behind them.

v1 works on one project at a time. v2 adds two things:

1. **Global mode**: sets up *you* across projects, not just one repo.
2. **Learning hook**: an optional, opt-in hook that turns corrections from your sessions into suggestions you approve later.

It also adds a smaller change: **a stale-fact check** against the live docs.

## Decisions already made

| Topic | Decision |
|---|---|
| Knowledge base | The curated references (docs plus what people learned from real setups) stay the main source. Live docs only catch stale *facts*. Live docs win on facts, the references win on judgment. |
| Status line, output style, default model/effort, keybindings, notification sounds | Out. These are personal taste, and Anthropic's defaults stay. |
| "Proving it helped" metrics | Dropped for now. |
| Syncing `~/.claude` across machines | Out of scope. Other tools do this. |
| Repo rename | Not needed. |
| Learning hook | Opt-in only, never on by default. Approve-only: it never edits CLAUDE.md or settings itself. |
| Global mode | Asks permission per project. It's heavier (more agents), so it always asks before running. |

---

## 1. Global mode

`/claude-setup global`

### What it does

- **Asks per project.** It lists the projects that have session history and lets you pick which ones to include. Nothing gets read until you choose.
- **Reads each chosen project shallowly:** its setup files, its session signals (reusing `sessions.py`), and its `.claude/setup-suggestions.md`. It does not do a full codebase analysis per repo. That's project mode's job.
- **Finds what only a cross-project view can see:**
  - **Promote:** the same rule or correction in 3+ repos moves to `~/.claude/CLAUDE.md`.
  - **Demote:** a global rule that only ever matters in one repo moves into that repo.
  - **Contradictions** between the global file and a project file.
  - **Global permission allowlist:** commands you approve in every project.
  - **User-level skills:** workflows you repeat across projects. Workflows that happen in only one project stay there.
  - **Tool and MCP suggestions from usage:** you run `gh` constantly, so suggest the GitHub MCP. You have 6 MCP servers and use 1, so disable the rest where they're unused.
  - **Local-only preferences:** "this preference lives only in `~/.claude` on this machine, so cloud sessions never see it. Move it into an account skill or the repo if you want it there."
- **Suggests project edits only where the cross-project view adds something:** duplicates, contradictions, and misplaced rules. For anything deeper it says "run `/claude-setup audit` in that repo."

### Cloud limits (verified in a cloud container, Sep 2026)

- **Carried over:** claude.ai account skills (synced in), connectors, and what's committed in the repo.
- **Not carried over:** local `~/.claude/CLAUDE.md`, auto-memory, and past session transcripts (only the current session's is there).
- So global mode has little to work with in a cloud session. It should say that and explain what it can still do there: the repo's own setup, and the suggestions document.

---

## 2. Learning hook (opt-in)

### Flow

Two triggers. Locally it runs once per session, and in the cloud it runs at turn end (see the test results for why):

```
local:  SessionEnd → hook returns in <0.1 s, hands off to a detached background process
cloud:  Stop (end of a turn) → runs in-session, only if there's something new

  → prefilter script (no model, cheap, ~ms)
      reads the transcript from where it last stopped
      only text the user typed + structural signals
      no new signals → exit 0
  → claude -p --model sonnet --json-schema, no tools, slim system prompt, --max-budget-usd
      input: flagged excerpts + current CLAUDE.md files + open and rejected suggestions
  → merge script
      validates, dedupes, applies strength rules, renders .claude/setup-suggestions.md
  → cloud only: if the file changed, exit 2 → Claude commits and pushes it on the current branch
```

### Prefilter

- **Scans only what the user typed.** It skips Claude's replies, tool output, pasted code blocks, and injected hook or system text. This removes most false alarms ("stop the dev server", a `don't` inside pasted code).
- **Keyword and phrase list:** reuse and extend `CORRECTION_RE` from `sessions.py`.
- **Structural signals catch corrections that use no keyword:**
  - interrupts (`[Request interrupted…`)
  - rejected tool calls
  - the same request rephrased shortly after
  - a message starting with "no," / "not that"

  These are recorded with their position, so the model sees "the user stopped Claude here, right after it did X."
- It skips very short sessions.

### What the model returns

Each item is one of:
- **add:** a new line.
- **change:** the current line (file:line) and the proposed text.
- **remove:** a line that's wrong or dead.
- **conflict:** a correction that contradicts an existing line. It shows both sides and never becomes an automatic add.

Each item also carries:
- **destination:** global CLAUDE.md, project CLAUDE.md, a rule, a hook, a skill, or a permission (using the skill's existing "where knowledge belongs" logic).
- **strength:** strong or weak.
- **durability:** lasting preference vs one-time instruction. One-time instructions are dropped.
- **evidence:** a short paraphrase plus the date. No long quotes.

### The formatting guard

The model never writes the document. It returns JSON against a fixed schema. The merge script:
- rejects invalid output entirely (and logs it) instead of half-writing,
- merges duplicates into one entry with a count and dates,
- is the only thing that renders the document, so the format is identical every time.

### Strength, not "seen twice"

- **Strong goes straight to pending:**
  - explicit "always / never / from now on"
  - repeating yourself within the same session
  - frustration right before an interrupt
  - every conflict
- **Weak waits** until it's seen in a second session.
- **Expiry is optional.** Weak items not seen again within N days (default 30) are dropped. It can be set to never expire.
- **Rejected items are remembered** so they don't come back.

### Where suggestions live: `.claude/setup-suggestions.md`

It's one file, at one path, in every repo, and works the same locally and in the cloud.

- There's a **Project** section and a **Global** section. Global items are recorded here too. When approved, `/claude-setup review` writes them to `~/.claude/CLAUDE.md`.
- **Locally:** gitignored by default, so personal preferences stay out of team repos.
- **In the cloud:** committed, otherwise the file is lost when the container shuts down. The skill says this plainly when the hook is turned on.
- **Cloud plus a shared team repo:** the skill warns that personal suggestions will be committed where teammates can see them.

### Keeping every repo's document in sync

Every repo carries a Global section, so without syncing they go stale. For example, you approve "use pnpm" in repo A, and repos B through F still list it as pending. Two layers keep them current:

1. **Lazy reconcile, every run.** Whenever the hook or `/claude-setup review` touches a document, the merge script first checks it against the *current* config: global CLAUDE.md, project CLAUDE.md, rules, settings. Items that are already applied, or whose target line no longer exists, are marked resolved. No cross-repo writes are needed, because each repo catches up the next time it's touched.
2. **Global mode sweep.** `/claude-setup global` reads every opted-in repo's document, merges the Global sections (the same item in 3 repos is strong evidence), and after approval updates every repo's document so they all agree.

Items get a stable ID (a hash of the normalized text plus the destination), so the same suggestion is recognized across repos.

Added after review:
- **Merge conflicts.** Two cloud branches that both update the file conflict when merged. Every read of the file splits the conflict markers into both versions and unions them by ID (the furthest-along status wins), so the next hook run, `reconcile`, or review writes a clean file. Tested with a real `git merge`: both branches' items were kept, a rejection on one branch survived, and a weak item seen on both became pending.
- **Permission items** close themselves once the rule is in the matching `settings.json`.
- **Installed copies** carry `VERSION`, and `inventory.py` flags outdated ones. `install` keeps previous options.
- **Tracked file locally.** Once the cloud has committed the file, local runs show it as modified. That's documented, not changed: it's how local review results travel back.

### The pending notice

- A SessionStart hook counts pending items and adds a line to context. Claude then mentions it once at the end of its first reply: *"7 setup suggestions pending. Run /claude-setup review to look."*
- Count only, never the contents. Once per session.
- It's a small annoyance by design: the point is that nothing piles up unseen.

### Cost controls

- It's opt-in, and the prefilter means the model only runs on flagged sessions.
- There's a daily cap on model runs.
- **Sonnet only.** The Haiku option was dropped: in testing it was noisier and wasn't cheaper, and poor results would reflect on the product.
- It only calls the model on turns where the prefilter found something new. Those turns end a few seconds later; every other turn costs nothing noticeable.
- **Recursion guard:** the headless run is started with `CLAUDE_SETUP_LEARN_CHILD=1`, and the hook exits at once when it sees that variable. The hook also respects `stop_hook_active`.
- `--max-budget-usd` on every headless run as a hard ceiling.

### Install

- **Not** shipped in the plugin's hooks (plugin hooks turn on at install, and this must be opt-in). `/claude-setup learn on` writes it to settings after explaining what it does, what it costs, and where it writes.
- **Locally:** user-level settings, so it covers every repo.
- **Cloud:** project `.claude/settings.json`, committed, per repo.
- A per-session lock keeps it from running twice when both are present.
- `/claude-setup learn off` removes it cleanly.

---

## 3. Stale-fact check

When the `claude-code-guide` agent or network access is available, audit mode checks the few facts that go stale: settings keys, hook event names, and frontmatter fields. It flags mismatches with the references. It never replaces reference guidance with doc text.

---

## New commands

| Command | What it does |
|---|---|
| `/claude-setup global` | Cross-project pass (asks per project) |
| `/claude-setup review` | Walk through pending suggestions: approve, edit, reject |
| `/claude-setup learn on\|off` | Install or remove the learning hook |

## Test results (cloud container, Claude Code 2.1.285, 2026-09-30)

| Test | Result |
|---|---|
| Structured output from headless Claude | Works: `claude -p … --output-format json --json-schema '<schema>'` returns a `structured_output` field that matches the schema. `--tools ""` plus a short `--system-prompt` cut cost about 5× (a "say hi" run with the default prompt cost $0.048). |
| Sonnet on a sample excerpt | ~3 s, ~$0.01. Correct: turned "from now on always pnpm" plus CLAUDE.md "Use npm" into one strong **conflict**, and dropped "stop the dev server" and "don't touch config.ts today". |
| Haiku on the same excerpt | ~31 s, ~$0.02 (one sample). Found the conflict but also listed the one-time "today" instruction. Confirms the caveat: noisier. It wasn't cheaper in this run. |
| `--bare` for the headless run | **Not usable.** It only accepts an API key; subscription (OAuth) users would fail. Use the normal CLI with a slim prompt instead. |
| Pending notice via SessionStart `additionalContext` | **Works.** The model ended its first reply with exactly: "7 setup suggestions pending - run /claude-setup review". Because the notice is part of Claude's reply, it shows wherever the reply shows: app, web, or terminal. |
| SessionEnd on clean exit, SIGTERM, SIGHUP | Fires in all three cases, and a hook there could commit and push to a git remote. |
| SessionEnd time limit | **Hooks are killed after about 3 s** by default, even on a clean exit. That's too short for a model call. An undocumented env var, `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`, raises it (tested with 15000). A detached `setsid nohup` child keeps running after the CLI exits. That's fine on a laptop, but the child dies with a cloud container. |
| Stop hook order | Hooks for the same event **run in parallel** (two hooks started within 2 ms). |
| Cloud environment's own Stop hook | Cloud sessions ship `~/.claude/stop-hook-git-check.sh`. It exits 2 (Claude can't finish the turn) while there are uncommitted, untracked, or unpushed files, and it requires commits signed as `noreply@anthropic.com`. |

### What changed because of the tests

1. **Stop in the cloud, SessionEnd locally.** SessionEnd gives about 3 s, and in the cloud nothing guarantees the container outlives a detached process. So the cloud runs at Stop, while the session is alive. Locally, SessionEnd hands off to a detached process, which outlives the CLI; that keeps local sessions free of per-turn work.
2. **In the cloud, Claude commits the file, not the hook.** A commit made by a hook script would be unsigned and would show as "Unverified". It could also race the environment's git check, since hooks run in parallel. So when the file changes, our hook exits 2 and asks Claude to commit and push it. Claude's own commits are signed, and the environment's check is then satisfied.
3. **An offset instead of a once-per-session run.** Stop fires every turn, so the prefilter records how far into the transcript it has read. The model only sees new material.
4. **Haiku was dropped** (decision after review).

### Integration tests (after the build)

| Test | Result |
|---|---|
| Stop hook, cloud, run on this design session's own transcript against a CLAUDE.md with "Offer a Haiku model option" and "Run the learning hook on every turn" | 8 s, $0.028. Three strong items: remove the Haiku line, a **conflict** on the every-turn line, and a **global** "no attribution or session links in PRs". |
| Rerun on the same transcript | No model call (offset). Still exits 2 while the file is uncommitted, as intended. |
| `stop_hook_active=true` | Exits 0 (no loop). |
| Local SessionEnd | The hook returned in 0.09 s. The background run finished about 8 s later. The file was added to `.git/info/exclude` and didn't show in `git status`. |
| Reconcile | After the Haiku line was deleted by hand, the Remove item was marked "already in place". |
| Global item applied in the cloud | Refused, and it stays pending. |
| Project install: other account, or not in the cloud | Both are no-ops. |
| Real nested `claude -p` session with the project hooks installed | The user typed "from now on, always write commit messages in lowercase". The Stop hook produced a strong Add, and Claude committed and pushed the file. The first version of the hook message made Claude create a new branch and end on a commit summary. The final wording ("current branch, no new branch, stop without a summary") fixed both: Claude committed on the current branch, pushed, and ended with "Done." |
| Install/uninstall into existing settings | Unrelated permissions and hooks kept, JSON re-parsed. |

## Still unverified

- Whether a real cloud session ever fires SessionEnd before its container is reclaimed. This can't be observed from inside a session, and the cloud design doesn't depend on it.
- Windows: the detached launch uses `DETACHED_PROCESS`. It's written but untested here (this container is Linux).
- How often a heavy user's sessions trip the prefilter, which decides the real cost. It needs a run over real transcripts once the prefilter exists.

## Decisions from review

- **Approved Global items in a cloud session** stay pending until a local session, since `~/.claude` in the cloud is thrown away. The cloud review says so.
- **Expiry** is on by default (weak items, 30 days) and can be turned off.
