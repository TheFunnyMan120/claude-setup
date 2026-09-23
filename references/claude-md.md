# CLAUDE.md, rules, memory, and where knowledge belongs

Sources: code.claude.com/docs/en/memory, /best-practices, /claude-directory; Anthropic blog "The new rules of context engineering for Claude 5-generation models" (Jul 2026); Gloaguen et al., ETH Zurich, arXiv 2602.11988. Verified Sep 2026.

## Contents
- [Loading model](#loading-model)
- [Size](#size)
- [What belongs in CLAUDE.md](#what-belongs-in-claudemd)
- [Anti-patterns](#anti-patterns)
- [Where knowledge belongs](#where-knowledge-belongs)
- [Rules files](#rules-files)
- [Imports](#imports)
- [AGENTS.md and other tools](#agentsmd-and-other-tools)
- [Auto memory](#auto-memory)
- [Good example](#good-example)

## Loading model

| Scope | Path | Loads | Shared |
|---|---|---|---|
| Managed | Win `C:\Program Files\ClaudeCode\CLAUDE.md`, mac `/Library/Application Support/ClaudeCode/CLAUDE.md`, Linux `/etc/claude-code/CLAUDE.md` | launch | org |
| User | `~/.claude/CLAUDE.md` | launch | just you, all projects |
| Ancestors + project | `CLAUDE.md` or `.claude/CLAUDE.md` in every dir from filesystem root down to cwd | launch | git |
| Local | `CLAUDE.local.md` beside each | launch, after that dir's CLAUDE.md | just you, **must be gitignored** |
| Nested | `<subdir>/CLAUDE.md` below cwd | **on demand**, when Claude reads files in that subdir | git |
| Rules, unscoped | `.claude/rules/**/*.md` without `paths` | launch, same priority as `.claude/CLAUDE.md` | git |
| Rules, scoped | `.claude/rules/**/*.md` with `paths:` | when Claude reads a matching file | git |
| User rules | `~/.claude/rules/` | same logic | just you |

- Files are **concatenated, not overridden**. Nothing has "priority". When two instructions contradict, Claude may pick either one arbitrarily, so a contradiction is always a bug. Fix it by deleting one side, not by adding "this overrides that".
- Block-level HTML comments (`<!-- ... -->`) are stripped before injection. They are fine for notes to human maintainers and cost no context.
- `claudeMdExcludes` (settings, glob on absolute paths) skips unwanted CLAUDE.md files, e.g. in monorepos. Managed CLAUDE.md can't be excluded.
- CLAUDE.md is **context, not enforcement**. Claude can still decide against an instruction. Anything that must never or always happen belongs in a hook or permission rule (see safety.md).
- `/memory` shows which files are loaded. The `InstructionsLoaded` hook event can log why each file loaded, which helps debug "is my rule even loading?".

## Size

- Target **under 200 lines per file**. This is a soft target, not a limit: longer files load in full (files over 4 MiB are skipped), but they cost more context and reduce adherence. Treat "Claude ignores my instructions" as a symptom of bloat before you treat it as a wording problem.
- Measure what always loads: user + ancestors + project + local + unscoped rules + their imports. The inventory script reports `always_loaded_approx_tokens` (chars/4). Rough guide: under 2k tokens is lean, 2-5k is fine if every line earns its place, over 5k needs a split.
- As a file approaches 200 lines, move task- or area-specific content into path-scoped rules or skills. `@imports` and unscoped rules help organization but **save no context**.
- Newer models need fewer rules. Anthropic cut over 80% of Claude Code's own system prompt for Claude 5-generation models with no measurable loss on its internal evals, moving part of it into tool descriptions and skills. Rules that restate default model behavior are dead weight.

## What belongs in CLAUDE.md

Open with 1-3 lines on what the repo is. Spend most of the remaining tokens on **gotchas**.

Include (only if Claude can't infer it from the code):
- Bash commands Claude can't guess: build, test (including how to run a single test), lint, typecheck, dev server, codegen, migrations
- Code style that **differs from** language or framework defaults
- Test instructions and the preferred runner
- Repo etiquette: branch naming, commit/PR conventions, what not to commit
- Project-specific architectural decisions and the *why* behind them
- Environment quirks: required env vars (names only), OS or toolchain oddities, services that must be running
- Gotchas: "X looks like it does Y but actually...", generated files not to edit, flaky areas, traps that have bitten people
- Pointers to deeper docs ("for the payments flow, read docs/payments.md")

Exclude:
- Anything Claude can read from the code, such as dependency lists or what a function does
- Standard language conventions ("use camelCase in JS")
- Detailed API docs. Link to them instead.
- Frequently changing info (current sprint, TODO lists, version numbers that drift)
- Long explanations and tutorials
- File-by-file or folder-by-folder tours
- Self-evident rules ("write clean code", "handle errors properly", "be careful")
- Secrets, tokens, internal URLs with credentials

The core test for every line: **"Would removing this cause Claude to make a mistake?"** If not, cut it.

Write instructions that are specific and checkable: "Use 2-space indentation", not "format code nicely"; "Run `pnpm test:unit -- <file>` for one file", not "run the tests". Use headings and bullets; short imperative lines beat prose.

Emphasis ("IMPORTANT", "YOU MUST") can help with a few truly critical lines. If more than a handful of lines shout, none of them stand out. Shouting in CLAUDE.md is also a sign the rule may belong in a hook.

## Anti-patterns

Each entry gives the symptom, then the fix.

1. **Over-specified or bloated file.** Claude ignores rules and the file keeps growing. Prune hard with the core test, move specifics to rules or skills, and turn must-never rules into hooks.
2. **Unedited `/init` output.** Generic boilerplate, a folder tour, and restated package.json scripts. The ETH Zurich study found LLM-generated context files gave no statistically significant benefit (-0.5% on SWE-bench Lite, -2% on AGENTbench) and raised inference cost by over 20%. Developer-written files did modestly better. Treat `/init` output as a first draft to cut down, never as the finished file.
3. **Memory log.** A "Lessons learned" or "Corrections" section, or dated entries appended session after session. Auto memory now covers personal and machine learnings. Keep in CLAUDE.md only what the whole team needs; distill the rest or let auto memory hold it.
4. **Enforcement by prose.** "NEVER push to main" or "ALWAYS run lint before commit". Use a PreToolUse hook or a deny/ask permission rule for these. Keep one line in CLAUDE.md only if Claude needs the *why*.
5. **Stale instructions.** Commands, scripts, paths, or tools that no longer exist. These are the most harmful lines because Claude trusts them. Check each one against package.json, the Makefile, CI, and the file tree.
6. **Contradictions and duplication** across user, project, local, rules, and AGENTS.md files. Keep one home for each fact.
7. **Personal preferences in the team file.** Editor habits or "call me X" belong in `~/.claude/CLAUDE.md` or `CLAUDE.local.md`.
8. **CLAUDE.local.md committed to git.** It must be gitignored.
9. **Both `./CLAUDE.md` and `./.claude/CLAUDE.md` present.** Both load, which is confusing. Pick one.
10. **Unscoped rules sold as context savings.** A `.claude/rules/` file with no `paths:` loads every session.
11. **Imports used as progressive disclosure.** `@docs/big-guide.md` loads the whole guide at launch. To load it on demand, write a plain-text pointer instead: "Read docs/big-guide.md when working on X".
12. **Tooling duplicated in prose.** Style rules a linter or formatter already enforces. Point to the linter command instead.

## Where knowledge belongs

Decide by *who needs it* and *when*.

| Knowledge | Home |
|---|---|
| Universal to this repo, needed most sessions, short | Project `CLAUDE.md` |
| Your personal preferences across all projects | `~/.claude/CLAUDE.md` |
| Your personal preferences for this repo (sandbox URLs, local paths) | `CLAUDE.local.md` (gitignored) |
| Applies only to certain files or areas (`*.sql`, `frontend/**`, migrations) | `.claude/rules/<topic>.md` with `paths:` |
| Applies to one subtree in a monorepo | `<subdir>/CLAUDE.md` (loads on demand) |
| A procedure or workflow ("how we release", "add an API endpoint") or domain knowledge needed only for some tasks | Skill `.claude/skills/<name>/SKILL.md` |
| Big reference material (API specs, schemas, runbooks) | `docs/` file, pointed to by path from CLAUDE.md or a skill |
| Must always or never happen | Hook or permission rule |
| A different persona or toolset for a sub-task | Subagent `.claude/agents/<name>.md` |
| Learned facts about the user or project for one person or machine | Auto memory (automatic) |
| Env vars, model, permissions | `settings.json` |

## Rules files

```markdown
---
paths:
  - "src/api/**/*.ts"
  - "src/**/*.{ts,tsx}"
---
# API handlers
- Validate input with the zod schemas in src/api/schemas/, never ad hoc.
```

- Found recursively under `.claude/rules/`, so subfolders are fine.
- Brace expansion works. Budget: 1,000 expanded patterns or 4 MiB per rule.
- Check that each glob actually matches files. A dead glob means the rule never loads.

## Imports

- Syntax `@path/to/file` or `@~/.claude/x.md`. Paths are relative to the importing file. Max depth is 4 hops. Imports inside code spans or fences are ignored.
- Importing a file outside the project triggers a one-time approval dialog.
- Imported files load at launch, so they count toward size.
- Check that every import resolves. The inventory script flags broken ones.

## AGENTS.md and other tools

- Claude Code reads `AGENTS.md` only when no `CLAUDE.md` or `CLAUDE.local.md` exists in cwd or above. The user-level and managed files don't count toward that check. The `/config` Project instructions setting changes this: `claude-md-or-agents-md` (default), `claude-md-and-agents-md`, `claude-md`, or `managed-only`. AGENTS.md support needs v2.1.277+ and isn't available on Bedrock, Vertex, or Foundry.
- The Project-instructions mode isn't reliably readable from files. Assume the default unless the user says otherwise, and state that assumption in the report. The user can check it in `/config`.
- If both files exist with the default setting, AGENTS.md is silently ignored. Flag this. The fix is a thin CLAUDE.md containing `@AGENTS.md` plus Claude-specific notes, or merging the two.
- Migration sources to fold in and dedupe: `.cursorrules`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`, `GEMINI.md`, `.windsurfrules`, `.clinerules`. Carry over only content that passes the core test.

## Auto memory

- On by default (`autoMemoryEnabled`, or env `CLAUDE_CODE_DISABLE_AUTO_MEMORY`). Stored per machine at `~/.claude/projects/<path-with-non-alphanumerics-as-dashes>/memory/` and shared across worktrees of the repo. `autoMemoryDirectory` overrides the location.
- `MEMORY.md` is the index. Only its **first 200 lines or 25KB** load each session, and topic files are read on demand.
- Audit for: an index over the limit, orphan topic files not linked from the index, dangling links, facts that contradict CLAUDE.md, and team-relevant facts stuck in one person's memory (promote those to CLAUDE.md).
- Not version-controlled. Anything the team needs must live in CLAUDE.md, rules, or docs.

## Good example

```markdown
# Acme API
Express + Postgres service behind the mobile app. pnpm monorepo; this package is `apps/api`.

## Commands
- `pnpm dev` - API on :4000 (needs `docker compose up db` first)
- `pnpm test -- path/to/file.test.ts` - single test; full suite is slow (~6 min), run only before PR
- `pnpm db:migrate` after pulling; `pnpm db:generate` after editing prisma/schema.prisma

## Gotchas
- `src/generated/` is codegen output - edit prisma/schema.prisma instead.
- Money is integer cents everywhere; `formatPrice()` is the only place that divides.
- Auth middleware order matters: `rateLimit` must precede `auth` (see #412).
- Tests share one DB; never use `.only` or truncate tables outside `tests/setup.ts`.

## Conventions
- Errors: throw `AppError(code, msg)`; never `res.status(500)` directly.
- Branches `feat/<ticket>-slug`; squash-merge; PR title = conventional commit.

## Deeper docs (read when relevant)
- Payments flow: docs/payments.md
- Deploy/runbook: docs/deploy.md
```

About 25 lines, no tour, no generic advice, and every line would prevent a real mistake.
