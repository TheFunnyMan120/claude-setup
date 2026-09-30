# Settings, permissions, hooks, MCP, secrets

Source: code.claude.com/docs/en/settings, /permissions, /hooks, /mcp. Verified Sep 2026.

## Contents
- [Settings files](#settings-files)
- [Permission evaluation](#permission-evaluation)
- [Permission hygiene checks](#permission-hygiene-checks)
- [Secrets](#secrets)
- [Hooks](#hooks)
- [MCP](#mcp)
- [Baseline settings](#baseline-settings)

## Settings files

Precedence, highest first: **managed** (org policy, can't be overridden), then CLI flags, then `.claude/settings.local.json` (personal and gitignored), then `.claude/settings.json` (team, committed), then `~/.claude/settings.json` (user). Scalar keys are overridden by the higher scope. Arrays such as permission lists and `claudeMdExcludes` merge across scopes. `~/.claude.json` is separate global state (trust dialogs, per-project data) and is not a settings file.

Notable keys: `permissions.{allow,ask,deny,defaultMode,additionalDirectories}`, `env`, `hooks`, `disableAllHooks`, `model`, `effortLevel`, `outputStyle`, `statusLine`, `sandbox.{enabled,excludedCommands,...}`, `autoMemoryEnabled`, `autoMemoryDirectory`, `claudeMdExcludes`, `enabledPlugins`, `enableAllProjectMcpServers`, `enabledMcpjsonServers`, `disabledMcpjsonServers`, `attribution` / `includeCoAuthoredBy`, `skipDangerousModePermissionPrompt`.
Permission modes: `default`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions`, `manual`.

Git hygiene:
- `.claude/settings.local.json` and `CLAUDE.local.md` are **gitignored and untracked**. If they're tracked, the fix is `git rm --cached <file>` plus a .gitignore entry, then check whether they held anything sensitive.
- `.claude/settings.json`, `.mcp.json`, `CLAUDE.md`, `.claude/rules|skills|agents|commands` are normally committed.
- Personal allow-lists that accumulate from clicking "always allow" belong in local settings, not in the team file.

## Permission evaluation

- Order is **deny, then ask, then allow**. The first match wins, and specificity doesn't change the order. A narrow allow cannot carve an exception out of a broader deny or ask. An allow covered by a deny or ask is **dead**; the script flags likely cases.
- A deny at any scope beats an allow at any other scope. A managed deny can't be overridden, even by `--allowedTools`. PreToolUse hooks cannot override deny rules either.
- Rule syntax: `Tool` or `Tool(specifier)`. For Bash, `Bash(npm run test:*)` matches by prefix. For files, `Read(./path)`, `Edit(./src/**)`, `Read(~/.ssh/**)`, `Read(//abs/path)`. For web, `WebFetch(domain:example.com)`. For MCP, `mcp__server__tool` or `mcp__server`.
- **Only `Read(...)` and `Edit(...)` path rules are enforced for file tools.** Path rules on `Write`, `NotebookEdit`, `Glob`, or legacy `MultiEdit` are accepted and then ignored (v2.1.210+ warns at startup). Rewrite them as `Edit(...)` (which covers writes) or `Read(...)`.
- A Read deny covers Claude's file tools only. `cat .env` through Bash still works unless the sandbox or a hook blocks it.

## Permission hygiene checks

Severity: **high** means the user can lose data or leak secrets now. **Medium** means a real gap. **Low** means cleanup.

| Check | Sev |
|---|---|
| `defaultMode: bypassPermissions`, or `skipDangerousModePermissionPrompt: true`, outside a sandbox or container | high |
| `Bash`, `Bash(*)`, or `Bash(:*)` in allow, which approves every shell command | high |
| Allow on destructive or exfiltration families: `rm`, `sudo`, `git push`, `git reset --hard`, `curl`, `wget`, `ssh`, `scp`, `docker`, `kubectl`, `terraform`, `npm publish`, `sh -c`, `bash -c`, `eval`, `python -c`, `node -e`, `powershell` | medium |
| A secret file (`.env` with secret-looking keys, key or credential file) **tracked in git**. The script reports `sensitive_files[].tracked` and `secret_keys`. It's high even when a later commit "removed" it: check `git log --all -- <file>` and whether the remote is public. Fix: `git rm --cached`, .gitignore it, **rotate** every listed key. | high |
| `.env*`, `*.pem`, `*.key`, `id_rsa`, `credentials.json`, or `secrets/` present with no `Read(...)` deny | medium |
| Ignored path rules on Write, Glob, NotebookEdit, or MultiEdit | medium |
| Deny/ask rules that try to constrain Bash *arguments* (`Bash(curl http://github.com/ *)`) treated as security. They're bypassed by option reordering, a different protocol, redirects, variables, absolute binary paths, `sh -c`, or `git -C`. Relabel them as behavior shaping. For real control, deny curl and wget and use `WebFetch(domain:...)`, the sandbox network allowlist, or a validating PreToolUse hook. | low→medium |
| Dead allows shadowed by deny or ask | low |
| Hundreds of one-off allow entries (`Bash(git commit -m "fix typo")`) from clicking through prompts. Collapse them into a few prefix rules and move them to local settings. | low |
| `Edit` allowed with no path, or `additionalDirectories` covering home or drive roots | low→medium |
| `WebFetch` allowed with no domain | low |
| `mcp__*` wildcard allow | low |

For MCP servers and web access that can pull in untrusted content, prompt injection is the risk. Broad Bash plus network access together is the dangerous combination.

## Secrets

- To inspect an env file, never print values. Use the script's `sensitive_files[].secret_keys` (key names and value lengths), or run `python -c "import re,sys;[print(m.group(1),len(m.group(2))) for l in open(sys.argv[1]) if (m:=re.match(r'\s*([A-Za-z_]\w*)\s*=\s*(.*)',l))]" <file>`.
- Never put a literal secret in `settings*.json` `env`, `.mcp.json` `env`/`headers`, CLAUDE.md, rules, skills, or hooks. Reference it through `${VAR}` expansion (`.mcp.json` supports `${VAR}` and `${VAR:-default}` in `command`, `args`, `env`, `url`, `headers`) or keep it in a gitignored env file loaded by the shell.
- A found secret counts as compromised, especially if the file is or ever was committed. Recommend rotating it and checking history with `git log -p -S '<prefix>' -- <file>`. Report only the redacted form.
- Credential env vars such as `ANTHROPIC_API_KEY`, `AWS_BEARER_TOKEN_BEDROCK`, and `NPM_TOKEN` expand to empty in remote MCP `url`/`headers` by design, so a config that relies on them there is broken.

## Hooks

Config lives under `hooks` in any settings file, in plugin `hooks/hooks.json`, and in skill or agent frontmatter.
```json
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "node \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard.js", "timeout": 10}]}]}}
```
Types: `command`, `http`, `mcp_tool`, `prompt`, `agent`. Main events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PostToolUseFailure`, `Stop`, `SubagentStop`, `PreCompact`, `SessionEnd`, `Notification`, `InstructionsLoaded`, `ConfigChange`, `FileChanged`, among others. Matchers take regexes on the tool name (`Edit|Write`, `mcp__github__.*`) for tool events, and on the source for SessionStart (`startup|resume|clear|compact`).
Exit codes: **0** means proceed (stdout is added to context for SessionStart and UserPromptSubmit). **2** means block, and stderr is fed back to Claude. Any other code is a non-blocking error unless stdout is valid JSON. PreToolUse JSON: `hookSpecificOutput.permissionDecision` = `allow|deny|ask|defer`, plus `permissionDecisionReason`.
Timeouts: command hooks default to 10 min (30 s for UserPromptSubmit), prompt hooks to 30 s, agent hooks to 60 s. SessionEnd hooks are killed after roughly 1.5-3.5 s (measured ~3.4 s on 2.1.285), even on a clean exit, so anything slow there must detach, and a detached process dies with a cloud container. Hooks on the same event run in parallel, not in order.

Hooks run arbitrary code with the user's full permissions, automatically. Review each one like production code:
- **Quote** every variable (`"$CLAUDE_PROJECT_DIR"`, `"$file"`), because paths contain spaces (for example `My Project`).
- **Absolute or anchored paths.** Use `"$CLAUDE_PROJECT_DIR"/.claude/hooks/x.sh`, not `.claude/hooks/x.sh`. Hooks run in Claude Code's current directory, which can drift (for example when a session starts in a subfolder), and the docs recommend anchoring with `$CLAUDE_PROJECT_DIR`. For a guard hook, a missing script means an interpreter error (exit 1, non-blocking), so the guard silently **fails open**. Rate that medium. For convenience hooks it's low.
- **Validate stdin JSON.** Don't `eval` it and don't interpolate it into a shell command. Reject `..` path traversal.
- **Skip sensitive files.** Never read, echo, or upload `.env`, keys, or `.git/` internals.
- **No network calls** unless that's the hook's purpose. Never pipe downloaded content to a shell.
- **Fast.** PreToolUse and UserPromptSubmit hooks run on every call, so broad matchers (`*`) combined with slow scripts, or with `prompt`/`agent` hook types, add latency and cost to everything.
- **Fail safe.** A guard hook that crashes exits non-2, which *allows* the action. Wrap critical guards so that errors deny.
- The script must exist and be executable on this OS. Watch for bash-only hooks on Windows machines without Git Bash, and PowerShell hooks on mac or Linux.
- Hooks from plugins or cloned repos deserve the same review, since they run as soon as the project is trusted.

Good hook candidates for CLAUDE.md rules that say NEVER or ALWAYS:
| CLAUDE.md prose | Deterministic replacement |
|---|---|
| "Never edit generated files" | Deny `Edit(./src/generated/**)` |
| "Never read .env" | Deny `Read(./.env*)`, plus the sandbox for Bash |
| "Always run prettier after editing" | PostToolUse on `Edit\|Write` that runs the formatter on the file |
| "Never push to main" / "never force push" | Ask or deny `Bash(git push:*)`, plus a PreToolUse hook that checks the branch |
| "Run tests before finishing" | Stop hook that runs fast tests and exits 2 with failures |
| "Never touch the prod DB" | PreToolUse hook that pattern-matches the connection string or host |

Keep a one-line *why* in CLAUDE.md only if it helps Claude plan. The enforcement itself lives in the hook or rule.

## MCP

- `.mcp.json` at the project root holds project scope and is committed. Local and user scopes live in `~/.claude.json`, added with `claude mcp add --scope user|local`. Plugins can ship `.mcp.json`.
- Project servers require approval once the workspace is trusted. `enableAllProjectMcpServers: true` auto-approves anything a future commit adds to `.mcp.json` (medium). Prefer an explicit `enabledMcpjsonServers` list. Reset approvals with `claude mcp reset-project-choices`.
- Checks for each server: no literal secrets in `env` or `headers` (use `${VAR}`). Remote servers use https. `npx`/`uvx` packages are pinned to a version, because unpinned or `@latest` is a supply-chain risk. The source is known and trusted. The server is actually used (each one adds tool definitions and context, even with tool search or deferral).
- Servers that fetch external content (web, email, tickets) are prompt-injection vectors. Pair them with tight permissions and don't also grant broad Bash.
- Output over 10k tokens triggers a warning, and the default cap is 25k (`MAX_MCP_OUTPUT_TOKENS`).

## Baseline settings

A sensible default for most repos. Adapt it; don't paste it blindly.
```json
{
  "permissions": {
    "deny": ["Read(./.env)", "Read(./.env.*)", "Read(./**/*.pem)", "Read(./**/*.key)", "Read(./secrets/**)"],
    "ask": ["Bash(git push:*)", "Bash(rm -rf:*)", "Bash(git reset --hard:*)"],
    "allow": ["Bash(<pkg> test:*)", "Bash(<pkg> run lint:*)", "Bash(git status)", "Bash(git diff:*)", "Bash(git log:*)"]
  }
}
```
If the team has `.env.example`, keep it readable. `Read(./.env.*)` also matches it, so replace that rule with explicit `.env.local` and `.env.production` entries.
