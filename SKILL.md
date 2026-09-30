---
name: claude-setup
description: Sets up, audits, and improves a project's Claude Code configuration - CLAUDE.md, AGENTS.md, CLAUDE.local.md, the .claude/ folder (settings.json, hooks, skills, agents, commands, rules), .mcp.json, and memory. Learns the codebase (parallel subagents on big repos) and, with permission, past Claude sessions, then scores the setup and fixes it, or builds one from scratch with the hooks, skills, and agents that fit how the person actually works. Use when someone wants to set up Claude Code for a repo (more than a bare /init starter), write, review, audit, clean up, or slim down a CLAUDE.md, asks "is my Claude setup good?", says Claude keeps ignoring instructions, forgets project rules, or context feels bloated, wants hooks, permissions, MCP servers, or secrets in config checked, is migrating from .cursorrules, copilot-instructions.md, or AGENTS.md, asks "what skills, hooks, or agents should I make for this project?" (it bases recommendations on the codebase and past sessions), or asks where project knowledge should live. Also use for a cross-project pass on the user's global setup (~/.claude/CLAUDE.md, rules that repeat across repos), to review pending setup suggestions, or to turn the opt-in learning hook on or off. Also use to tighten a skill or agent description that won't trigger. Not for writing application code, general code review, a single one-off settings change like allowing one command (use update-config), or deep eval loops on one skill (use skill-creator).
argument-hint: "[audit|fix|init|global|review|learn on|off|explain <question>] [path]"
---

# Claude Code setup

**Goal:** leave the project with a Claude Code setup that is accurate to the code, lean in always-loaded context, safe in its permissions, and fitted to how the person works. That means a small CLAUDE.md of real gotchas and commands, hooks for what must always or never happen, and skills and agents for their repeated work.

**Done when:** the user has a scored report with concrete, evidence-backed changes (audit), or the approved changes are written and re-verified (fix/init).

Knowledge lives in reference files. Read only what the current step needs.

| File | Read when |
|---|---|
| [references/codebase-analysis.md](references/codebase-analysis.md) | Understanding the repo: sizing, subagent briefs, gap analysis, recommendations catalog |
| [references/sessions.md](references/sessions.md) | Mining past sessions for repeated tasks, corrections, and failures |
| [references/claude-md.md](references/claude-md.md) | Judging CLAUDE.md, rules, or AGENTS.md content, or deciding where knowledge belongs |
| [references/extensions.md](references/extensions.md) | Reviewing or writing skills, subagents, commands, output styles, plugins, and the context budget (MCP servers, plugin sprawl, listing size) |
| [references/safety.md](references/safety.md) | Settings, permissions, hooks, .mcp.json, secrets |
| [references/scoring.md](references/scoring.md) | Scoring and writing the report |
| [references/global.md](references/global.md) | Global mode: the cross-project pass on the user's own setup |
| [references/learning.md](references/learning.md) | The opt-in learning hook, `review`, and `.claude/setup-suggestions.md` |
| [templates/](templates/) | Creating any new file (CLAUDE.md, settings, rule, skill, agent, hook guard) |

## Non-negotiables

These hold in every mode:
1. **No writes without explicit approval** of the specific changes. Batch approvals cover only the items listed.
2. **Never print, copy, or write a secret value.** Report redacted forms and key names only.
3. **Never loosen safety unasked.** That means no `bypassPermissions`, no broader allows, no `enableAllProjectMcpServers`, and no disabled hooks unless the user asks for that exact change.

## Modes

Parse `$ARGUMENTS`; a path argument sets the project root (default: cwd).

- **audit**: understand, judge, score, report. Change nothing.
- **fix**: audit (or reuse this session's), then apply the approved changes.
- **init**: build a setup from scratch for a project that has none, or only `/init` boilerplate.
- **global**: the user's own setup across projects (promote, demote, contradictions, allowlist, user skills). Heavier: always asks per project and before spawning agents. Follow [global.md](references/global.md).
- **review**: go through `.claude/setup-suggestions.md` with the user. Follow [learning.md#review](references/learning.md#review).
- **learn on | learn off**: install or remove the opt-in learning hook, only on request, after the disclosure in [learning.md#turning-it-on](references/learning.md#turning-it-on).
- **explain `<question>`**: answer one targeted question ("where should X go?", "is this hook safe?") using only the relevant references and files.

With no mode given, choose it yourself and say which you picked. If there's no CLAUDE.md, AGENTS.md, or meaningful `.claude/` content, use **init**. Otherwise use **audit**. If the user points at one artifact (a single skill, agent, or hook), review just that one.

## Workflow

### 1. Inventory

```bash
python "${CLAUDE_SKILL_DIR}/scripts/inventory.py" --project "<project root>"
```
The script lists every file that shapes Claude's context and permissions and flags likely problems. It never prints secrets. Add `--no-user` to skip `~/.claude` when auditing someone else's repo. Its flags are **leads, not verdicts**, so confirm each one before reporting it. If `.claude/setup-suggestions.md` exists, run `python "${CLAUDE_SKILL_DIR}/scripts/learn.py" status` too and fold its pending items into the findings (as evidence, not as done decisions).

### 2. Understand the codebase and the person

- **Code:** follow [codebase-analysis.md](references/codebase-analysis.md). Read small repos yourself. For medium or large repos, launch parallel read-only `Explore` subagents in one message: commands, architecture, conventions, and gotchas/history.
- **Sessions:** ask once, in one line, whether you may scan this project's past Claude sessions. If yes, run `python "${CLAUDE_SKILL_DIR}/scripts/sessions.py" --project "<root>"` and read the output per [sessions.md](references/sessions.md). This is the best evidence of repeated tasks, recurring corrections, and failing or rejected commands. Skip it when there's no history.
- **Setup:** read every always-loaded instruction file in full (user, ancestor, and project CLAUDE.md, `.claude/CLAUDE.md`, CLAUDE.local.md, unscoped rules, and their `@imports`). Skim nested files, scoped rules, and skill/agent frontmatter. Read the flagged settings and hook scripts.

Merge it all into a **project brief** (format in codebase-analysis.md). Judge everything that follows against the brief. A tidy setup that's wrong about the code still scores badly.

### 3. Judge

- **Gap analysis** (brief vs setup): what's missing, wrong, redundant, or misplaced.
- **Line test:** for each CLAUDE.md line, ask "would removing this cause Claude to make a mistake?" Give each finding a destination: keep, cut, rewrite, or move to a rule, skill, hook, settings, or docs.
- **Whole-stack checks:** contradictions and duplication across user, project, local, rules, and AGENTS.md, and instructions that conflict with settings.
- **Recommendations** (at most 5, each tied to evidence from the code or sessions): skills for repeated tasks, hooks for repeated corrections and checks, agents for recurring delegated work, rules for hot areas.

**Stale facts:** the references are a curated knowledge base (docs plus what people learned from real setups), and their judgment stands. Only *facts* go stale: settings keys, hook event names, frontmatter fields. When a finding rests on one of those and the `claude-code-guide` agent or the web is available, check it against the live docs. Live docs win on facts. Never replace reference guidance with doc text.

### 4. Report

Follow [scoring.md](references/scoring.md). Lead with the score and the top fixes. Each finding gives `file:line`, why it matters, and the concrete change. In audit mode, stop here and offer to apply the fixes (all, by severity, or by number).

### 5. Apply (fix and init)

- Back up any file that isn't committed to `~/.claude/backups/claude-setup/<YYYYMMDD-HHMM>/` before editing it, and say where the backup is.
- When moving content, create the destination first, then trim the source. Show where each block went.
- Settings: keep unrelated keys and re-parse the JSON after writing.
- Literal secrets: replace them with `${VAR}` and tell the user to set the variable and **rotate** the key.
- New hooks follow [safety.md#hooks](references/safety.md#hooks) and get one test run with sample input.
- New skills and agents follow [extensions.md](references/extensions.md), including the trigger rules. For a skill that must fire, add a one-line pointer in CLAUDE.md, since a description alone often doesn't trigger it.
- Finish by re-running the inventory and reporting the before and after state.

### init specifics

1. Build the brief (steps 1-2) and collect migration sources (`.cursorrules`, `.cursor/rules/`, `AGENTS.md`, `.github/copilot-instructions.md`, `GEMINI.md`).
2. Ask at most 3 short questions about what the code can't show: gotchas that have bitten them, branch/PR conventions, commands Claude must never run.
3. Draft CLAUDE.md from [templates/CLAUDE.template.md](templates/CLAUDE.template.md) with verified commands and non-derivable facts only, in 30-80 lines. Delete empty sections rather than padding them.
4. Propose `.claude/settings.json` from [templates/settings.json](templates/settings.json), `.gitignore` entries for the local files, and the recommendations that the evidence supports. Create only what the user picks.

For an **empty or brand-new repo** there's nothing to learn from yet. Ask about the stack, how they'll test and deploy, and what must never happen. Write a small starter: known commands, an empty "Gotchas" heading to grow into, baseline settings, and `.gitignore` entries. Suggest rerunning the skill once there's real code and a few sessions.

If teammates use AGENTS.md for other tools, keep it as the source of truth, with a thin CLAUDE.md that does `@AGENTS.md` plus Claude-specific notes.

## Gotchas

Learned from real runs:
- **Heuristic flags need confirming.** For example, a "stale path" may exist relative to a subpackage, and a non-English description may still contain trigger words. Check before reporting.
- **One root cause, one deduction.** `Bash(*)` at user scope makes every narrower Bash finding moot. Report it once, with an "also resolved by #N" line.
- **Tracked `.env` files are the most common serious leak,** and a "stop tracking .env" commit often didn't actually untrack the file. Check `sensitive_files[].tracked`, never the commit message.
- **Relative hook paths fail open.** A guard hook whose script can't be found exits non-2, so the action goes through.
- **The AGENTS.md mode can't be read from files.** Assume the default (CLAUDE.md wins) and state that assumption.
- **Stale git worktrees duplicate files.** `.claude/worktrees/` contains copies of CLAUDE.md and friends. Exclude them from searches and suggest `git worktree remove`.
- **Bloat usually comes from MCP servers and plugins, not CLAUDE.md.** Check `context_budget` against `mcp_servers_used` from the session scan. Recommend "disable here" for servers unused in this project, not uninstalling everywhere.
- **Account and org skills aren't on disk.** To find duplicates, compare against the skill list in your own context, not just `~/.claude/skills`.
- **Windows:** `python3` is often a Store stub, so use `python` or `py`. Paths with spaces break unquoted hooks.
- **Never install the learning hook unasked,** and never as a side effect of fix or init. At most, mention it once in a report when sessions show the same correction recurring.
- **Leave Anthropic's defaults alone.** Don't propose a status line, output style, default model or effort, keybindings, or notification sounds unless the user asks.
- **Don't out-write the model.** Setup advice that restates what Claude does by default is noise. Recommend only what changes its behavior in this repo.

## Ground rules

- References were verified against code.claude.com in September 2026. If live behavior contradicts a reference (an unknown field, a new setting, a startup warning), trust the live behavior. The `claude-code-guide` agent can check the current docs.
- Be specific to this project. The bar is "`npm test` doesn't exist; the script is `test:unit` (package.json:12); fix CLAUDE.md:8", not "consider adding test instructions".
- Shorter is the default direction. A missing section is a finding only if Claude needs that information and can't infer it.
- Respect intentional choices. When a comment or the user explains an oddity, note it instead of "fixing" it.
