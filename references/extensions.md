# Skills, subagents, commands, output styles, plugins

Source: code.claude.com/docs/en/skills, /sub-agents, /slash-commands, /output-styles, /plugins. Verified Sep 2026. Frontmatter fields change often, so if a field here is unknown to the installed version, trust the startup warnings.

## Contents
- [Skills](#skills)
- [Writing descriptions that trigger](#writing-descriptions-that-trigger)
- [Subagents](#subagents)
- [Slash commands](#slash-commands)
- [Output styles](#output-styles)
- [Plugins](#plugins)
- [Cross-cutting checks](#cross-cutting-checks)

## Skills

Locations: project `.claude/skills/<name>/SKILL.md`, nested `<subdir>/.claude/skills/...` (active in and below that subdir), user `~/.claude/skills/<name>/SKILL.md`, and plugin `<plugin>/skills/<name>/SKILL.md` (invoked as `/plugin:name`). A loose `skills/foo.md` is not a skill.

Cost model: only `name` and `description` sit in context permanently. The SKILL.md body loads when the skill is invoked and then stays for the rest of the session. Bundled files load only when Claude reads them. Scripts cost context only through their output.

Frontmatter (all optional):
`name` (defaults to the directory name; lowercase with hyphens; `synced` is reserved), `description`, `when_to_use` (appended to description), `argument-hint`, `arguments`, `disable-model-invocation` (true means user-only), `user-invocable` (false hides it from `/`), `allowed-tools` (pre-approved while active), `disallowed-tools`, `model`, `effort`, `context: fork` plus `agent` and `background` (run in a subagent), `hooks`, `paths` (globs limiting activation), `shell` (bash|powershell), `metadata`, `license`, `compatibility`.
Only `name`, `description`, `license`, `compatibility`, `metadata`, and `allowed-tools` are portable (claude.ai upload and the Skills API). Other fields make an upload fail.

Body substitutions: `$ARGUMENTS`, `$0`/`$ARGUMENTS[0]`, named `$arg`, `${CLAUDE_SKILL_DIR}`, `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_SESSION_ID}`. Dynamic context: `` !`cmd` `` injects command output at invocation, and a non-zero exit aborts the skill.

Audit checks:
- `description` + `when_to_use` must not exceed **1,536 chars**, or the listing truncates it.
- Body **under 500 lines**. Move detail into `references/*.md` linked from SKILL.md, keep links one level deep, and give long reference files a contents list.
- Every linked file exists. The script reports `links to missing file`.
- Frontmatter `name` matches the directory. A mismatch causes confusion about which `/name` works.
- `allowed-tools` doesn't pre-approve unrestricted `Bash` or broad write access unless the skill genuinely needs it.
- Side-effecting skills (deploy, send, publish, delete) set `disable-model-invocation: true` so they run only when the user asks.
- Skills that do long exploration with noisy output consider `context: fork`.
- Deterministic, repeatable steps (parsing, validation, file inventory) belong in a bundled script rather than prose instructions, because a script is more reliable and cheaper.
- No duplicated content between a skill and CLAUDE.md. The skill owns the procedure and CLAUDE.md points to it.
- Names don't collide across user, project, and plugin skills or commands. Skills win over commands with the same name.
- The same skill isn't installed twice under different namespaces (for example a user `rbxm-reader` plus a plugin or claude.ai `anthropic-skills:rbxm-reader`). The script only sees on-disk plugins and synced skills, so also compare against the skill list in your own session context, which includes account and org skills. Both copies' descriptions cost listing tokens, and they compete for triggers.
- The skill fits a clear job. Merge overlapping skills and split skills that do unrelated jobs.

## Writing descriptions that trigger

Sources: community measurements (Scott Spence's activation evals, Vercel's agent evals, Seleznov's activation trials) reconciled with Anthropic's skill-creator and prompting docs, Sep 2026.

**Undertriggering is the #1 failure.** Skills that rely only on their description went unused in 56% of Vercel's eval cases, and measured activation ranged from about 20% to 59% depending on model and setup. Choosing between skills is rarely the problem; getting a skill to fire at all is. Score each description on these points:
1. **What plus when, key use case first.** Listings can truncate the end.
2. **Literal vocabulary.** Use the exact words users type: file names (`CLAUDE.md`, `.pptx`), commands (`/init`), tool names, and complaint phrasings ("Claude keeps ignoring..."). Activation depends on exact words: prompts using the skill's own tokens fired about 100% of the time, while indirect phrasings fired about 0%.
3. **Assertive but conditional.** Use "Use when...", "any time X is involved", and "Also use for...". Anthropic's own skill-creator recommends "a little bit pushy".
4. **No shouting or blanket fallbacks.** CRITICAL, MUST, "ALWAYS invoke", and "If in doubt, use this" make Opus 4.5+ and Sonnet 5 overtrigger (per Anthropic's current prompting docs). Community "ALWAYS" templates hit 100% activation but never measured false positives.
5. **Exclusions.** "Not for X; use Y" wherever another installed skill competes for the same words. The official pptx and xlsx skills pair broad triggers with explicit do-not-trigger lists.
6. **Third person, specific.** "Creates and edits .docx with tracked changes", not "Helps with documents" or "I can help you".

**Descriptions aren't enough for skills that must fire.** Add a backup:
- a one-line pointer in CLAUDE.md ("For X, use the /name skill"). Explicit instructions raised Vercel's rate from 53% to 79%.
- or a UserPromptSubmit "forced eval" hook that makes Claude answer YES or NO for each relevant skill before starting work. It reached 84% vs 20% on Haiku 4.5, but adds latency on every prompt, so reserve it for teams with many skills that keep being missed.
- Knowledge needed in almost every session doesn't belong in a skill at all. Put it in CLAUDE.md, where an always-loaded docs index scored 100% in Vercel's evals.

**Body content** (Anthropic's Claude Code team, June 2026, matching practitioner reports):
- State the goal and constraints, not every step ("avoid railroading"). Prescribe exact steps only for fragile or order-sensitive operations, and put those in scripts.
- Include only what changes Claude's defaults, since restating default behavior adds tokens and no value.
- Keep a **Gotchas** section built from real failures. It's the highest-value content in most skills.
- Mark the few non-negotiable steps explicitly, so long workflows don't drop them.

**Testing.** Write 5 or more should-fire prompts (including indirect phrasings) and 3 or more should-not-fire prompts. Run each a few times, because small wording changes swing results. Compare against no skill, or the previous version, blindly. skill-creator automates both trigger optimization and A/B comparison. Every real miss becomes a description fix or a gotcha.

Rewrite pattern: `<Verb>s <objects> <distinctive capability>. Use when <literal trigger 1>, <trigger 2>, or the user says "<common phrasing>". Also use for <adjacent case>. Not for <X> (use <Y>).`

## Subagents

Locations: `.claude/agents/*.md` (project) and `~/.claude/agents/*.md` (user). Also plugins, `--agents` CLI, and managed settings. Precedence when names collide: managed, then CLI, then project, then user, then plugin.

Frontmatter: `name` (required; no `:`, no leading `-`), `description` (required), `tools` (allowlist), `disallowedTools`, `model` (`sonnet|opus|haiku|fable|inherit|<id>`), `effort`, `permissionMode`, `maxTurns`, `skills` (preloaded with full content), `memory` (`user|project|local` → `~/.claude/agent-memory/<name>/`, `.claude/agent-memory/<name>/`, or `.claude/agent-memory-local/<name>/`), `omitClaudeMd`, `mcpServers`, `hooks`, `isolation: worktree`, `background`, `color`, `initialPrompt`.
Plugin subagents ignore `hooks`, `mcpServers`, and `permissionMode`.

Audit checks:
- Both `name` and `description` are present. The description says when to delegate, and "use proactively" signals auto-delegation.
- **Least privilege.** Set a `tools` allowlist. Read-only reviewers or researchers get `Read, Grep, Glob` (plus `Bash` only if needed). An agent with no `tools` inherits everything, including MCP tools.
- `permissionMode: bypassPermissions` on an agent is high severity unless it's sandboxed or isolated.
- `model` fits the job: cheap and fast (haiku or sonnet) for search and triage, strongest for review and architecture. `inherit` is fine.
- The body is a real system prompt: role, process, output format, and what *not* to do. A near-empty body is a finding.
- Preloaded `skills` add their full content to every run. Check that they're needed.
- No two agents overlap enough to confuse delegation.
- Agents that should run in parallel or in isolation use `isolation: worktree` when they edit files.
- Use a subagent when the task needs its own context window (keeping noisy exploration out of the main thread) or a restricted toolset. Use a skill when it's just instructions or knowledge.

## Slash commands

`.claude/commands/*.md` (and `~/.claude/commands/`) become `/filename`, and subfolders namespace them. Commands and skills coexist, but skills are the more capable format (bundled files, auto-invocation control). Check that:
- Each command has a `description` frontmatter so the `/` menu reads well.
- `argument-hint` is set when the command takes arguments.
- It doesn't collide with a skill name (the skill wins).
- A command that has grown supporting material, or that Claude should auto-invoke, should be converted to a skill.

## Output styles

`~/.claude/output-styles/*.md`, `.claude/output-styles/*.md`, and plugin `output-styles/`. Frontmatter: `name`, `description`, `keep-coding-instructions` (default false, which drops Claude Code's software-engineering instructions), and `force-for-plugin` (plugins only). Built-ins: `default`, `Proactive`, `Concise`, `Explanatory`, `Learning`. Selected with `outputStyle` in settings (case-sensitive).
Checks: a custom style used for coding without `keep-coding-instructions: true` silently removes coding guidance. An `outputStyle` value naming a style that doesn't exist is a finding.

## Plugins

Layout: `.claude-plugin/plugin.json` (`name` required; plus `description`, `version`, `author`, `homepage`, `repository`, `license`), `skills/`, `agents/`, `commands/`, `hooks/hooks.json`, `.mcp.json`, `.lsp.json`, `monitors/`, `bin/`, `output-styles/`, `settings.json`.
Enabled via `enabledPlugins` in settings. Marketplaces are added with `claude plugin marketplace add <owner/repo>`. Validate with `claude plugin validate <dir>`.
Checks: plugins from unknown marketplaces carry hooks and MCP servers that run code, so review them like any hook or MCP server. Look for disabled or unused plugins still listed, and for plugin skills that duplicate local ones.
Suggest packaging as a plugin when the user has a set of skills, agents, and hooks they copy between projects or share with a team.

## Cross-cutting checks

- **Inventory bloat.** Dozens of user-level skills or agents with vague descriptions add listing tokens to every session and misfire. Recommend pruning unused ones.
- **Scope.** Project-specific skills or agents living at user level (they show up in every repo), or generic ones copied into many repos. Move them to the right scope.
- **Staleness.** Skills that reference scripts, paths, or tools that no longer exist.
