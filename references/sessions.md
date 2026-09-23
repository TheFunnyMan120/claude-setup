# Learning from session history

The codebase shows how the project works. Session transcripts show how the person *works with Claude*: what they ask for over and over, what they keep correcting, which commands Claude runs, fails, or is refused. That is the best evidence for which hooks, skills, agents, and CLAUDE.md lines will actually pay off.

## Consent and privacy

- Transcripts can contain anything the user pasted. **Ask once before mining them**, in one line: "I can also scan your past Claude sessions in this project (N found, stored locally) to spot repeated tasks and corrections. OK?" Skip this step if they decline, or if there are no transcripts (a new user or a different machine), and say that recommendations are based on the code only.
- The script reads only this project's transcripts (`~/.claude/projects/<encoded-path>*/*.jsonl`), redacts secret-shaped strings, and outputs aggregates plus short snippets.
- In the report, **paraphrase** patterns ("you asked to commit and push in 26 sessions"). Don't quote prompts beyond a short phrase. Never copy prompt text into files that get committed.

## Run

```bash
python "${CLAUDE_SKILL_DIR}/scripts/sessions.py" --project "<project root>" --days 90
```

## Reading the signals

| Output field | What it tells you | Typical recommendation |
|---|---|---|
| `recurring_themes_bigrams`, `common_openers`, `session_titles` | Tasks the user starts over and over ("commit push", "update player modal", "deploy") | A **project skill** or slash command for the repeated procedure, e.g. `/ship` that typechecks, commits, pushes, and opens a PR the way they like. Titles are the quickest read of what the project work actually is. |
| `corrections_sample` / `corrections_count` | Things Claude keeps getting wrong. This is the most valuable signal. | A preference or fact correction becomes a **CLAUDE.md line** (or a user CLAUDE.md line if it applies to every project). A "don't do X" correction becomes a **hook or deny rule** if it's about an action. A correction about workflow ("relay first, don't execute until I approve") becomes CLAUDE.md or permission `ask` rules. |
| `interrupts`, `rejected_tool_calls_by_tool` | Actions the user stops or refuses. High `ExitPlanMode` rejection means plans often miss the mark. High `Bash` rejection means specific commands they don't want run. | Add `ask`/`deny` rules for the rejected command families. For frequent plan rejections, add CLAUDE.md guidance on what their plans must cover, or suggest plan mode for big changes. |
| `bash_most_run` | The real toolchain, plus what Claude does constantly | Verify the commands are documented in CLAUDE.md. Frequent typecheck or test runs → a PostToolUse or Stop hook to automate them. Frequent deploy CLI use (`railway`, `vercel`, `fly`, `gh pr`) → a deploy/ship skill, plus ask rules for prod-affecting commands. Many repeated read-only commands → allow rules (or the `/fewer-permission-prompts` skill). |
| `bash_most_failed` + example | Wasted turns: wrong commands, wrong cwd, shell-quoting failures (heredoc EOF errors), a missing tool | Fix the CLAUDE.md command. Add a gotcha line (e.g. "backend commands run from repo root with `--filter`"). On Windows, note which shell to use. A hook-block message here means a guard is working, so don't "fix" it. |
| `files_most_edited`, `areas_most_edited` | Hot spots: where most work happens | Make sure the hot areas have scoped rules or a nested CLAUDE.md with their gotchas. Very large hot files may deserve a short "how this file is organized" note. |
| `skills_used`, `subagents_used`, `slash_commands_used` | What the user relies on, and what's installed but never used | Keep and improve what's used. Offer to prune installed but unused skills and agents (listing tokens). Heavy `/compact` use → the always-loaded context may be heavy, or sessions run long, so check context economy and suggest pointing to docs instead of importing them. Heavy `general-purpose` agent use for the same kind of job → a dedicated subagent with the right tools and a system prompt. |
| `models` | Model mix | Rarely actionable. At most, set a `model` on subagents that could run cheaper. |

## Turning signals into recommendations

1. Cross-check against the codebase brief. A repeated task in sessions plus a matching script or workflow in the repo is a strong skill candidate. A correction that contradicts CLAUDE.md is an accuracy bug.
2. Estimate the payoff: sessions affected × turns saved. Prefer recommendations that fix things happening every week.
3. Draft concretely. For a skill, give the name, a description with triggers, and the steps taken from how the user actually does the task. For a hook, give the event, matcher, and command. For a CLAUDE.md line, give the exact text and its location.
4. Don't over-fit. One heated session isn't a pattern; require about 3 or more sessions, or a large count.
