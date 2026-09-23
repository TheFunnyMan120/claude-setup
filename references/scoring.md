# Scoring rubric and report format

## What to collect

The inventory script collects everything below. If you have to collect it by hand, gather:

| Area | Files |
|---|---|
| Instructions | `~/.claude/CLAUDE.md`; every `CLAUDE.md`, `.claude/CLAUDE.md`, and `CLAUDE.local.md` from the filesystem root to the project; nested `**/CLAUDE.md`; `AGENTS.md`; `.claude/rules/**/*.md`; `~/.claude/rules/`; all `@imports` |
| Extensions | `.claude/{skills,agents,commands,output-styles}/`, the same under `~/.claude/`, and `enabledPlugins` |
| Settings | `.claude/settings.json`, `.claude/settings.local.json`, `~/.claude/settings.json`, including hooks and the scripts they call |
| MCP | `.mcp.json`, plus `claude mcp list` if you can run it |
| Memory | `~/.claude/projects/<encoded-path>/memory/MEMORY.md` and topic files |
| Ground truth | package.json/pyproject/Cargo/go.mod scripts, Makefile, CI workflows, README, top-level tree, `.gitignore`, and any `.env*` or key files |
| Migration | `.cursorrules`, `.cursor/rules/`, `.github/copilot-instructions.md`, `GEMINI.md`, `.windsurfrules`, `.clinerules` |

## Categories (100 points)

Score each category from what you actually verified. When a category doesn't apply (for example, no MCP servers), give full marks for its security portion and say so.

| # | Category | Pts | Full marks look like |
|---|---|---|---|
| 1 | **Instruction quality** | 25 | Every line passes "would removing this cause a mistake?". Commands are verified to exist. Gotchas and project-specific decisions dominate. Wording is specific and checkable. There is no tour, no generic advice, and no boilerplate. |
| 2 | **Accuracy & freshness** | 15 | No stale commands, paths, or tools. Nothing contradicts the code, and nothing contradicts across the files in the stack. |
| 3 | **Context economy** | 15 | Each file is under 200 lines and the always-loaded total is lean. Area-specific content sits in scoped rules or nested files, and procedures sit in skills. Imports and unscoped rules aren't posing as savings. The MEMORY.md index is within its limits. There are no unused, duplicated, or wrongly scoped MCP servers or plugins, and the skill/agent listing isn't bloated. |
| 4 | **Enforcement fit** | 10 | Must-always and must-never rules are hooks or permission rules, not prose. Hooks back the rules that matter. |
| 5 | **Permissions & secrets** | 20 | No high-severity items. Secrets have Read denies. There are no literal secrets anywhere. Allow rules are scoped, with no dead or ignored rules. Local files are gitignored. |
| 6 | **Hooks & MCP safety** | 5 | Variables quoted, paths anchored, input validated, hooks fast and fail-safe. MCP servers are pinned and trusted, with secrets expanded from env. |
| 7 | **Extensions quality** | 10 | Skill and agent descriptions trigger reliably (what, when, and within the limits). Bodies are within size limits with working links. Agents follow least privilege. There are no collisions, overlaps, or unused sprawl. |

Deductions, applied within each category:
- **high:** -6 to -10, and cap the total at 69 while any high item is open
- **medium:** -3 to -5
- **low:** -1 to -2

A category can't go below 0. Don't double-count a single root cause across categories. List it once, under its main category.

**Suppressed findings.** When one broad problem makes narrower ones moot (for example `Bash(*)` at user scope makes every `Bash(curl:*)` allow and every missing Bash ask rule irrelevant), deduct once for the root cause. Mention the narrower items in a single "also resolved by fixing #N" line, and bring them back only if the root cause is kept on purpose. The script annotates such flags with "moot while…".

Grades: **A** 90+, **B** 80-89, **C** 70-79, **D** 60-69, **F** under 60.

Calibrate against these reference points. A missing CLAUDE.md in a small, conventional repo isn't an F; it may be a C with an `init` recommendation. A 400-line CLAUDE.md with stale commands, plus `Bash(*)` and an unprotected `.env`, is a D or F.

## Report format

```markdown
# Claude setup audit: <project name>
**Score: 74/100 (C)** · always-loaded context ≈ 3.1k tokens across 4 files · audited <date>

## Top fixes
1. **[high] `.env` readable by Claude:** no Read deny, and `Bash(curl:*)` is allowed. Add `Read(./.env*)` deny. → +8
2. **[high] Stale test command:** CLAUDE.md:14 says `npm test`; the script is `test:unit` (package.json:9). → +5
3. ...

## Scores
| Category | Score | Notes |
|---|---|---|
| Instruction quality | 18/25 | ... |
...

## Findings
### Instruction quality
- **[medium] CLAUDE.md:30-52: folder tour.** Claude can see the tree. Replace with 2 gotcha lines about `legacy/` and `generated/`.
...
(group by category; each finding = severity, file:line, why it matters, concrete change)

## Proposed structure
(only when moving content: a short tree of where each chunk goes)

## What the codebase says you're missing
(gap analysis: facts from the project brief that Claude would get wrong without being told. Give the exact proposed line and where it goes.)

## Recommendations
(up to 5, ranked by payoff; each = signal found in the code → proposal → payoff, e.g. "prettier config + 40 'format' commits → PostToolUse format hook; drop CLAUDE.md:22-25")

## What's already good
(2-4 bullets, so the user knows what not to touch)

---
Reply with "fix all", "fix high", or finding numbers to apply.
```

Keep the report tight. Findings the user can't act on don't belong in it. If there are more than about 25 findings, show the top ones in full and collapse the rest into a table of one-line entries.
