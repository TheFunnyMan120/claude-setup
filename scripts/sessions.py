#!/usr/bin/env python
"""Mine this project's Claude Code session transcripts for setup signals.

Reads ~/.claude/projects/<encoded project path>*/*.jsonl (local, read-only) and
summarizes what people actually do: repeated tasks, corrections they keep
giving Claude, commands that get run or fail, files edited most, tools/skills
used, and actions users reject. Output is aggregate + short redacted snippets.

Usage:
  python sessions.py [--project PATH] [--days 90] [--max-sessions 300]
  python sessions.py --list-projects [--days 90]   # for global mode: which projects have history
"""
import argparse
import collections
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from inventory import SECRET_PATTERNS, USER_CLAUDE  # noqa: E402

CORRECTION_RE = re.compile(
    r"(^\s*(no|nope|nah|stop|wait|wrong)\b|\bdon'?t\b|\bdo not\b|\binstead\b|\bnot what i\b|"
    r"\bi (said|told you|asked)\b|\bagain\b|\bremember\b|\balways\b|\bnever\b|\bwhy did you\b|"
    r"\bshould(n'?t| not)? have\b|\buse \S+ (not|instead of)\b|\bthat'?s not\b|\byou forgot\b)", re.I)
STOP = set("""a an the to of and or in on for with this that it is are be was were i you we me my
our your can could would should will just please now then so do does did have has had at as by from
up out if not no yes ok okay hey also like get make go into about what how why when where which
all any some more there here its it's im i'm dont don't lets let's want need think but one look
other know stuff only right being they them thing things work well that's because actually really see
use sure going good still even way got something same new back into over time much very add made
kind bit lot everything anything maybe probably though them those these then than been being""".split())
# MCP servers the desktop app provides itself; they can't be configured or disabled per project
APP_SERVERS = {"Claude_Browser", "Claude_Preview", "visualize", "terminal", "claude-in-chrome", "computer-use"}
SHELL_WORDS = {"for", "if", "while", "until", "do", "done", "then", "else", "elif", "fi", "case", "esac",
               "echo", "cd", "export", "set", "true", "time", "{", "}"}
RUNNABLE_EXT = {"", ".exe", ".py", ".sh", ".js", ".mjs", ".ps1", ".cmd", ".bat"}
SKIP_PREFIXES = ("This session is being continued", "Base directory for this skill", "<command-", "<local-command", "<system-reminder", "<task-notification", "Caveat:",
                 "[Request interrupted", "<bash-", "<user-prompt-submit-hook")


def redact(text):
    for _, rx in SECRET_PATTERNS:
        text = rx.sub("[REDACTED]", text)
    return re.sub(r"(?i)((?:token|secret|password|api[_-]?key)\s*[:=]\s*)\S+", r"\1[REDACTED]", text)


def encoded(p):
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(p).resolve()))


def texts_of(content):
    if isinstance(content, str):
        return [content]
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return out


def norm_words(t):
    t = re.sub(r"https?://\S+|[A-Za-z]:\\\S+|/\S+|`[^`]*`|\d+", " ", t.lower())
    return [w for w in re.findall(r"[a-z][a-z'\-]+", t) if w not in STOP and len(w) > 2]


def lp(p):
    """Windows paths past MAX_PATH (desktop-app scratch workspaces) need the \\\\?\\ prefix."""
    s = os.path.abspath(str(p))
    return Path("\\\\?\\" + s) if os.name == "nt" and len(s) >= 248 and not s.startswith("\\\\?\\") else Path(p)


def mtime(f):
    try:
        return lp(f).stat().st_mtime
    except OSError:
        return 0.0


def split_chain(cmd):
    """Split on ; && || and newlines outside quotes. Heredoc bodies are dropped first."""
    cmd = re.sub(r"<<-?\s*['\"]?\w+['\"]?.*", "", cmd.replace("\\\n", " "), flags=re.S)
    parts, cur, q, i = [], "", None, 0
    while i < len(cmd):
        c = cmd[i]
        if q:
            q = None if c == q else q
        elif c in "\"'":
            q = c
        elif c in ";\n" or cmd[i:i + 2] in ("&&", "||"):
            parts.append(cur)
            cur = ""
            i += 2 if c in "&|" else 1
            continue
        cur += c
        i += 1
    return [p.strip() for p in parts + [cur] if p.strip()]


def bash_key(cmd):
    toks = re.findall(r"\"[^\"]*\"|'[^']*'|\S+", cmd.strip())
    while toks and toks[0] in ("do", "then", "else", "time"):
        toks = toks[1:]
    if not toks:
        return ""
    head = toks[0].strip("\"'").replace("\\", "/").split("/")[-1]
    head = re.sub(r"\.exe$", "", head, flags=re.I)
    if (not re.match(r"^[\w.\-]+$", head) or head in SHELL_WORDS
            or os.path.splitext(head)[1].lower() not in RUNNABLE_EXT):
        return ""
    rest = toks[1:]
    if head in ("python", "python3", "py") and rest[:1] == ["-m"] and len(rest) > 1:
        return f"{head} -m {rest[1]}"
    sub = [t for t in rest[:2] if re.match(r"^[\w:.\-/]+$", t) and not t.startswith(("-", "/", "."))
           and len(t) < 30]
    return " ".join([head] + sub[:1 if head in ("git", "npm", "pnpm", "yarn", "bun", "cargo", "go",
                                                  "docker", "python", "py", "node", "npx", "uv", "make",
                                                  "rojo", "wally", "gh", "kubectl", "railway") else 0])


def shell_keys(cmd, powershell=False):
    """One key per command in a chain (a leading `cd x &&` is skipped by SHELL_WORDS)."""
    keys = [k for k in (bash_key(p) for p in split_chain(cmd)) if k]
    return ["ps: " + k for k in keys] if powershell else keys


def project_cwd(f):
    """The real project path, from the first transcript line that records a cwd."""
    try:
        with lp(f).open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i > 50:
                    break
                cwd = json.loads(line).get("cwd") if '"cwd"' in line else None
                if cwd:
                    return cwd
    except (OSError, ValueError):
        pass
    return None


def list_projects(days):
    base = USER_CLAUDE / "projects"
    cutoff = time.time() - days * 86400
    rows = {}
    for d in (base.iterdir() if base.exists() else []):
        files = [f for f in d.glob("*.jsonl") if mtime(f) >= cutoff] if d.is_dir() else []
        if not files:
            continue
        newest = max(files, key=mtime)
        path = project_cwd(newest) or d.name
        # tool-generated sessions (claude-mem's observer) aren't a project
        if re.search(r"[\\/]\.claude-mem([\\/]|$)", path):
            continue
        # a worktree's sessions belong to its repo
        path = re.split(r"[\\/]\.claude[\\/]worktrees[\\/]", path)[0]
        r = rows.setdefault(path, {"project": path, "sessions": 0, "last_active": 0})
        r["sessions"] += len(files)
        r["last_active"] = max(r["last_active"], mtime(newest))
    out = sorted(rows.values(), key=lambda r: -r["last_active"])
    for r in out:
        r["last_active"] = datetime.fromtimestamp(r["last_active"], timezone.utc).strftime("%Y-%m-%d")
        r["exists"] = Path(r["project"]).exists()
        r["has_suggestions_file"] = (Path(r["project"]) / ".claude" / "setup-suggestions.md").exists()
    json.dump({"projects": out, "days": days}, sys.stdout, indent=1)
    print()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--max-sessions", type=int, default=300)
    ap.add_argument("--list-projects", action="store_true",
                    help="list projects with session history (paths, counts, dates only; reads no prompts)")
    a = ap.parse_args()
    if a.list_projects:
        return list_projects(a.days)
    project = Path(a.project).resolve()
    enc = encoded(project)
    base = USER_CLAUDE / "projects"
    dirs = [d for d in base.glob(enc + "*") if d.is_dir()] if base.exists() else []
    cutoff = time.time() - a.days * 86400
    files = sorted((f for d in dirs for f in d.glob("*.jsonl") if mtime(f) >= cutoff),
                   key=mtime, reverse=True)[: a.max_sessions]
    if not files:
        print(json.dumps({"project": str(project), "sessions": 0,
                          "note": "no transcripts found for this project (new user, other machine, or cleaned up)"}))
        return

    titles, prompts_by_session = [], collections.defaultdict(list)
    corrections, interrupts, rejected = [], 0, collections.Counter()
    bash_runs, bash_fail, tools, skills, agents, slash = (collections.Counter() for _ in range(6))
    edited, fail_examples = collections.Counter(), {}
    tool_use_index = {}
    models, first_ts, last_ts = collections.Counter(), None, None
    seen_uuids = set()  # resumed and forked sessions replay earlier records with the same uuid

    for f in files:
        sid = f.stem
        for line in lp(f).open(encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            uid = d.get("uuid")
            if uid:
                if uid in seen_uuids:
                    continue
                seen_uuids.add(uid)
            t = d.get("type")
            ts = d.get("timestamp")
            if ts:
                first_ts = min(first_ts or ts, ts)
                last_ts = max(last_ts or ts, ts)
            if t == "custom-title" and d.get("customTitle"):
                titles.append(d["customTitle"])
            if d.get("isSidechain"):
                continue
            msg = d.get("message") or {}
            content = msg.get("content")
            if t == "user":
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            txt = json.dumps(b.get("content"))[:600]
                            tu = tool_use_index.get(b.get("tool_use_id"))
                            raw = b.get("content")
                            first = raw if isinstance(raw, str) else " ".join(texts_of(raw))
                            if b.get("is_error") and first.lstrip().startswith("The user doesn't want to"):
                                rejected[tu[0] if tu else "?"] += 1
                            elif b.get("is_error") and tu and tu[0] in ("Bash", "PowerShell") and tu[1]:
                                bash_fail[tu[1]] += 1
                                fail_examples.setdefault(tu[1], redact(re.sub(r"\\n|\s+", " ", txt))[:200])
                origin = (d.get("origin") or {}).get("kind")
                for txt in texts_of(content):
                    s = txt.strip()
                    if not s:
                        continue
                    m = re.search(r"<command-name>/?([\w:\-]+)</command-name>", s)
                    if m:
                        slash[m.group(1)] += 1
                        continue
                    if s.startswith("[Request interrupted"):
                        interrupts += 1
                        continue
                    if s.startswith(SKIP_PREFIXES) or (origin and origin != "human"):
                        continue
                    prompts_by_session[sid].append(s)
                    if CORRECTION_RE.search(s[:400]) and len(s) < 1200:
                        corrections.append(redact(re.sub(r"\s+", " ", s))[:220])
            elif t == "assistant":
                if msg.get("model"):
                    models[msg["model"]] += 1
                for b in content if isinstance(content, list) else []:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    name, inp = b.get("name", "?"), b.get("input") or {}
                    tools[name] += 1
                    key = None
                    if name in ("Bash", "PowerShell"):
                        keys = shell_keys(str(inp.get("command", "")), name == "PowerShell")
                        for k in keys:
                            bash_runs[k] += 1
                        # a chain's exit status is its last command's, so failures are blamed there
                        key = keys[-1] if keys else None
                    elif name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                        p = str(inp.get("file_path", ""))
                        try:
                            p = str(Path(p).resolve().relative_to(project)).replace("\\", "/")
                        except Exception:
                            p = p.replace(str(Path.home()), "~").replace("\\", "/")
                        # worktree edits count toward the real file; scratch and temp files aren't the project
                        p = re.sub(r"^\.claude/worktrees/[^/]+/", "", p)
                        if not re.search(r"(^|/)(AppData/Local/Temp|tmp)/|/scratchpad/", p):
                            edited[p] += 1
                    elif name == "Skill":
                        skills[str(inp.get("skill", "?"))] += 1
                    elif name in ("Agent", "Task"):
                        agents[str(inp.get("subagent_type", "general-purpose"))] += 1
                    tool_use_index[b.get("id")] = (name, key)

    # recurring themes: word bigrams appearing in >= 3 distinct sessions
    bigram_sessions = collections.defaultdict(set)
    word_sessions = collections.defaultdict(set)
    # text pasted/injected verbatim into many sessions is boilerplate, not intent
    seen_in = collections.defaultdict(set)
    for sid, ps in prompts_by_session.items():
        for p in ps:
            seen_in[p[:300]].add(sid)
    boiler = {k for k, v in seen_in.items() if len(v) >= 3 and len(k) >= 150}
    for sid, ps in prompts_by_session.items():
        for p in ps:
            if p[:300] in boiler or len(p) > 2500:
                continue
            w = norm_words(p[:600])
            for x in set(w):
                word_sessions[x].add(sid)
            for bg in set(zip(w, w[1:])):
                bigram_sessions[" ".join(bg)].add(sid)
    n_sessions = len(prompts_by_session) or 1
    themes = sorted(((k, len(v)) for k, v in bigram_sessions.items() if len(v) >= 3),
                    key=lambda x: -x[1])[:25]
    words = sorted(((k, len(v)) for k, v in word_sessions.items() if 3 <= len(v) < 0.9 * n_sessions),
                   key=lambda x: -x[1])[:30]
    openers = collections.Counter()
    for ps in prompts_by_session.values():
        if ps:
            openers[" ".join(norm_words(ps[0])[:4])] += 1

    mcp_by_server, app_by_server = collections.Counter(), collections.Counter()
    for name, c in tools.items():
        if name.startswith("mcp__"):
            server = name.split("__")[1]
            is_app = server in APP_SERVERS or server.startswith("ccd_")
            (app_by_server if is_app else mcp_by_server)[server] += c

    top_edit_dirs = collections.Counter()
    for p, c in edited.items():
        parts = p.split("/")
        top_edit_dirs["/".join(parts[:2]) if len(parts) > 2 else parts[0]] += c

    out = {
        "project": str(project),
        "sessions": len(files),
        "human_prompts": sum(len(v) for v in prompts_by_session.values()),
        "span": [first_ts, last_ts],
        "models": dict(models.most_common(5)),
        "session_titles": list(dict.fromkeys(titles))[-60:],
        "recurring_themes_bigrams": themes,
        "recurring_words": words,
        "common_openers": [(k, c) for k, c in openers.most_common(10) if c > 1 and k],
        "corrections_sample": corrections[-40:],
        "corrections_count": len(corrections),
        "interrupts": interrupts,
        "rejected_tool_calls_by_tool": dict(rejected.most_common(10)),
        "bash_most_run": bash_runs.most_common(30),
        "bash_most_failed": [(k, c, fail_examples.get(k, "")) for k, c in bash_fail.most_common(12)],
        "files_most_edited": edited.most_common(20),
        "areas_most_edited": top_edit_dirs.most_common(12),
        "tools": dict(tools.most_common(25)),
        "mcp_servers_used": dict(mcp_by_server.most_common(40)),
        "app_servers_used": dict(app_by_server.most_common(20)),
        "skills_used": dict(skills.most_common(20)),
        "subagents_used": dict(agents.most_common(15)),
        "slash_commands_used": dict(slash.most_common(20)),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False, default=str)
    print()


if __name__ == "__main__":
    main()
