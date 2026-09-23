# Understanding the codebase

The setup is only as good as its fit to the code. This phase builds a **project brief**, a compact set of facts about how the repo actually works, and every later step judges against it. In `init` mode the brief becomes the raw material for CLAUDE.md. In `audit` mode it drives the gap analysis: facts Claude needs that are missing from the setup, and setup claims the code contradicts.

## Contents
- [Sizing the effort](#sizing-the-effort)
- [Agent briefs](#agent-briefs)
- [Project brief format](#project-brief-format)
- [Gap analysis](#gap-analysis)
- [Recommendations catalog](#recommendations-catalog)

## Sizing the effort

Count tracked source files (`git ls-files | wc -l`, or the inventory's walk) and top-level packages.

| Repo | Approach |
|---|---|
| Small (under ~150 files, one package) | Do it yourself inline: read manifests, CI, README, entry points, and a few representative files. No subagents. |
| Medium (~150-2,000 files, or 2-3 packages) | 2-3 parallel `Explore` subagents (angles A+B, C, D below). |
| Large or monorepo | One `Explore` subagent per angle (A-D), and for monorepos one extra agent per major package running angles A+C scoped to that package. Cap at about 6 agents. |

Launch all the agents **in a single message** so they run concurrently. Use the `Explore` agent type, which is read-only. If it isn't available, use a general-purpose agent and tell it not to modify anything. Each agent returns findings only, as facts with `file:line` evidence, in under ~400 words. Never let agents print secret values: env var **names** only.

## Agent briefs

Paste a brief into each agent prompt, with the project root and, for a monorepo, the package path.

**A. Commands & toolchain**
> Find how to build, run, test (full suite AND a single test), lint, format, typecheck, run codegen, run migrations, and deploy this project. Check package manifests (scripts), Makefile/justfile/Taskfile, CI workflows (.github/workflows, .gitlab-ci.yml), Dockerfiles, and the README. Report the exact working commands with where each is defined, the package manager and how you know (lockfile), required runtime versions (.nvmrc, .tool-versions, engines), services that must be running (docker compose, local DB), and any command that is dangerous or touches production. Note commands the README mentions that don't exist.

**B. Architecture & layout**
> Map the architecture briefly: entry points, major modules or packages and what each owns, how data flows (request → handler → service → DB, or game loop, or pipeline), external services and APIs used, and where config lives. Identify generated, vendored, or build-output directories that must not be hand-edited, and what regenerates them. Identify the areas where a newcomer would most likely edit the wrong file. Do not produce a file-by-file tour: only facts that change how someone should work.

**C. Conventions & patterns**
> Infer the conventions the code actually follows that differ from language or framework defaults: error handling, logging, naming, module boundaries, state management, test structure and fixtures, import style. Check lint and format configs (eslint, prettier, ruff, rustfmt, selene/stylua, editorconfig) and report what they already enforce, so it doesn't need restating. Report each convention with 1-2 file:line examples, and flag places where the code is inconsistent (e.g. two error-handling styles), naming which one is newer.

**D. Gotchas & history**
> Find the traps. Run `git log --oneline -300` plus `git log --grep='fix\|revert\|hotfix\|oops' -i --oneline -100` and look for repeated fixes to the same area, reverts, and "don't do X" messages. Grep for TODO, FIXME, HACK, XXX, "do not", "don't", "careful", "workaround", "legacy" in comments. Look for env var names read in code (process.env, os.environ, etc.) that aren't documented in any .env.example. Look for flaky or skipped tests, and ordering or initialization dependencies. Report the top 10 gotchas by likely impact, each with evidence. If it isn't a git repo, skip the history part.

For a **Roblox/Luau** project, add to A and B: Rojo/Argon project file mapping (`default.project.json`), Wally/rokit/aftman toolchain, which scripts are server, client, or shared, and how Studio sync works. For **game engines, mobile, or data/ML** projects, have agent B note the build/export pipeline and any assets that must not be hand-edited.

## Project brief format

Merge the agent results into this brief (keep it in your working context; don't write it to disk unless the user asks):

```
Project: <name> - <1 line what/stack>
Package manager / runtime: ...
Commands (verified): build | dev | test | test-one | lint | format | typecheck | codegen | migrate | deploy
Danger: <commands/areas touching prod, destructive scripts>
Layout facts: <generated dirs, package ownership, entry points - only non-obvious ones>
Conventions (non-default): ...
Enforced by tooling already: ...
Gotchas (ranked): 1..10 with evidence
Env vars (names): required vs optional
Workflows seen repeatedly: <release, migration, adding endpoint, adding a game system...>
Sensitive files: ...
```

## Gap analysis

In audit mode, compare the brief with the existing setup and report under **Accuracy & freshness** and **Instruction quality**:

- **Missing:** brief facts Claude would get wrong without being told, and that aren't in any loaded instruction file. The usual suspects are single-test commands, codegen steps, generated directories, prod-danger commands, and the top gotchas. Propose the exact line and its destination: CLAUDE.md, a scoped rule, or a nested CLAUDE.md.
- **Wrong:** instructions contradicted by the brief (commands that don't exist, a changed package manager, a moved directory).
- **Redundant:** instructions that restate something tooling already enforces, or that Claude can read from the code.
- **Misplaced:** package-specific facts in the root file that belong in the package's nested CLAUDE.md or a scoped rule.

In init mode, draft CLAUDE.md from the brief. Commands, danger, and the top gotchas go in first, then the non-default conventions. Leave out everything else.

## Recommendations catalog

Recommend only what the brief gives evidence for. Each recommendation names the signal, the proposal, and the expected payoff. Aim for at most 5, ranked by payoff.

| Signal in the codebase | Recommend |
|---|---|
| Formatter config (prettier, black/ruff, rustfmt, stylua) | PostToolUse hook on `Edit\|Write` that formats the edited file, and drop any formatting prose from CLAUDE.md |
| Fast unit tests exist | Stop hook, or a CLAUDE.md line, to run the relevant tests before finishing. Only hook it if tests take under ~30 s. |
| Prod DB, deploy, or publish commands | Ask/deny permission rules plus a PreToolUse guard (templates/hook-guard.js) |
| Generated or vendored directories | Deny `Edit(./<dir>/**)` plus one gotcha line naming the source of truth |
| `.env*`, keys, credentials | Read denies (templates/settings.json) |
| Monorepo or distinct areas (frontend/backend/bot) | Nested CLAUDE.md per package, or `paths:`-scoped rules |
| A workflow repeated in git history (migrations, releases, adding an endpoint or game system, content pipelines) | A project skill that captures the procedure (templates/SKILL.template.md) |
| Big review surface or security-sensitive code | A read-only reviewer subagent with a `tools: Read, Grep, Glob` allowlist (templates/agent.template.md) |
| Heavy use of an external service with an official MCP server (GitHub, Sentry, Linear, Postgres, Figma) | That MCP server in `.mcp.json` with `${VAR}` secrets, pinned version, and a project scope |
| AGENTS.md or .cursorrules used by teammates on other tools | Single source of truth: AGENTS.md plus a thin CLAUDE.md with `@AGENTS.md` |
| Many one-off allow rules in local settings | Collapse them into a few prefix rules; the `/fewer-permission-prompts` skill can derive them from transcripts |
| Large docs folder | Plain-text pointers in CLAUDE.md ("read docs/x.md when..."), not @imports |

Don't recommend automation the project hasn't earned. A 20-file hobby repo usually needs a 30-line CLAUDE.md and Read denies, not five hooks and three agents.

### Advanced patterns for mature setups

Offer these only when the basics are solid and the sessions show the need:
- **Self-maintaining CLAUDE.md.** A SessionEnd hook launches a background curator agent that reads the transcript and proposes CLAUDE.md edits to a pending file. A SessionStart hook surfaces pending proposals, and the user approves them. The SessionEnd hook must detach (spawn and exit), because SessionEnd hooks get about 1.5 s. It fits long-running projects where corrections pile up.
- **Format guards.** A PreToolUse hook that blocks shell writes to structured files (MEMORY.md, CHANGELOG, lockfiles) so they go through Edit and Write, where a validator hook checks them.
- **Prod guard with a reason.** A PreToolUse hook that blocks commands pointing at production (connection strings, prod hosts, `--prod` flags) and exits 2 with an explanation, plus a one-line *why* in CLAUDE.md.
- **Runbooks as on-demand docs.** `docs/runbooks/*.md` referenced by plain path from CLAUDE.md, loaded only when relevant.
- **Per-package nested CLAUDE.md** in monorepos, with the root file limited to cross-cutting rules.
- **Reviewer agents** (read-only, focused system prompt) that run before PRs, and a `/ship` skill that chains typecheck, test, commit, push, and PR the way the user does it.
