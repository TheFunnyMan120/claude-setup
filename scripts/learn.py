#!/usr/bin/env python3
"""claude-setup learning hook: turns corrections from Claude sessions into setup
suggestions the user approves later. Opt-in; never edits CLAUDE.md or settings.

Self-contained (stdlib only) because `install` copies it into a hooks folder.

Where it runs:
  local  SessionEnd -> hands the transcript to a detached background process
  cloud  Stop       -> runs in-session at the end of a turn (containers are
                       reclaimed without warning), only when the prefilter
                       found something new since the last check

Pipeline: prefilter (no model) -> claude -p --json-schema (Sonnet) -> merge
script, which is the only writer of .claude/setup-suggestions.md.

Commands (hooks read their JSON input from stdin):
  session-start | session-end | stop                  hook entry points
  analyze --transcript P --cwd D [--session S]       one analysis pass
  prefilter --transcript P [--all-projects]          signals only, no model
  status | reconcile [--cwd D]                       read / tidy suggestions
  resolve ID --status applied|rejected|pending [--cwd D]
  install | uninstall --scope user|project [--cwd D]
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME_CLAUDE = Path.home() / ".claude"
STATE_DIR = HOME_CLAUDE / "claude-setup"
FILE_REL = Path(".claude") / "setup-suggestions.md"
STATE_BEGIN, STATE_END = "<!-- claude-setup:state", "-->"
CHILD_ENV = "CLAUDE_SETUP_LEARN_CHILD"
HOOK_NAME = "claude-setup-learn.py"
VERSION = "2.0.0"  # installed copies carry this; inventory.py flags copies older than the skill's
MODEL = "sonnet"
IS_CLOUD = os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true"

CORRECTION_RE = re.compile(
    r"(^\s*(no|nope|nah|stop|wait|wrong|not that|that'?s not)\b|\bdon'?t\b|\bdo not\b|\binstead\b|"
    r"\bnot what i\b|\bi (said|told you|asked)\b|\bagain\b|\bremember\b|\balways\b|\bnever\b|"
    r"\bfrom now on\b|\bstop (doing|using|adding)\b|\bwhy did you\b|\bshould(n'?t| not)? have\b|"
    r"\buse \S+ (not|instead of)\b|\byou forgot\b|\bI (hate|don'?t like|prefer)\b)", re.I)
SKIP_PREFIXES = ("This session is being continued", "Base directory for this skill", "<command-",
                 "<local-command", "<system-reminder", "<task-notification", "Caveat:", "<bash-",
                 "<user-prompt-submit-hook")
REJECT_PREFIX = ("The user doesn't want to proceed", "The user doesn't want to take this action")
SECRET_RE = [re.compile(p) for p in (
    r"sk-ant-[A-Za-z0-9_\-]{10,}", r"sk-[A-Za-z0-9]{20,}", r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}", r"AKIA[0-9A-Z]{16}", r"xox[baprs]-[A-Za-z0-9\-]{10,}",
    r"AIza[0-9A-Za-z_\-]{30,}", r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]

SYSTEM_PROMPT = """You review excerpts from a Claude Code session and propose changes to the user's Claude Code setup (CLAUDE.md files, rules, hooks, skills, permissions).

Most excerpts are NOT setup material. Return an empty list unless something clearly is. Rules:
- Only lasting preferences or facts count. "Don't touch that file today", "stop the dev server", task steering, and one-off fixes are not durable: set durable=false or leave them out.
- kind: add (new line), change (rewrite an existing line: quote it in `current`), remove (an existing line is wrong or dead), conflict (the user's correction contradicts an existing line: quote the line in `current`, put the user's version in `proposed`; never express a contradiction as an add).
- scope: global if it is about how this person works everywhere (tone, workflow, git habits, communication); project if it is about this codebase.
- destination: claude_md for guidance; hook for anything that must ALWAYS or NEVER happen mechanically (run X after editing, never run Y); permission for commands to allow/deny; skill for a repeated multi-step workflow; rule for guidance scoped to part of the codebase.
- strength: strong when the user was explicit ("always", "never", "from now on"), repeated it in the session, interrupted Claude over it, or it is a conflict. Otherwise weak.
- proposed: the exact line to write, short, imperative, specific. Not a paraphrase of the conversation.
- evidence: a short paraphrase of what happened, no long quotes, no secrets, no personal data.
- same_as: if an item under OPEN SUGGESTIONS already covers this, put its id; otherwise "". Never re-propose anything under REJECTED.
- For permission items, put the exact rule in `proposed`, e.g. "allow Bash(npm test:*)" or "deny Read(./.env)".
- Do not restate what Claude does by default."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {
    "type": "array", "maxItems": 12, "items": {"type": "object", "additionalProperties": False,
        "required": ["kind", "scope", "destination", "file", "current", "proposed", "strength",
                     "durable", "evidence", "why", "same_as"],
        "properties": {
            "kind": {"enum": ["add", "change", "remove", "conflict"]},
            "scope": {"enum": ["project", "global"]},
            "destination": {"enum": ["claude_md", "rule", "hook", "skill", "permission"]},
            "file": {"type": "string"}, "current": {"type": "string"}, "proposed": {"type": "string"},
            "strength": {"enum": ["strong", "weak"]}, "durable": {"type": "boolean"},
            "evidence": {"type": "string"}, "why": {"type": "string"}, "same_as": {"type": "string"}}}}}}


# ---------- small helpers ----------

def now():
    return dt.datetime.now(dt.timezone.utc)


def today():
    return now().strftime("%Y-%m-%d")


def redact(s):
    for rx in SECRET_RE:
        s = rx.sub("[REDACTED]", s)
    return re.sub(r"(?i)((?:token|secret|password|api[_-]?key)\s*[:=]\s*)\S+", r"\1[REDACTED]", s)


def clip(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def norm(s):
    s = re.sub(r"[`*_>#]|^\s*[-+]\s+|^\s*\d+\.\s+", " ", (s or "").lower(), flags=re.M)
    return re.sub(r"\s+", " ", s).strip(" .")


def log(msg):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_DIR / "learn.log", "a", encoding="utf-8") as f:
            f.write(f"{now().isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        pass


def read_stdin_json():
    try:
        data = sys.stdin.read() if not sys.stdin.isatty() else ""
        return json.loads(data) if data.strip() else {}
    except Exception:
        return {}


def project_root(cwd):
    cwd = Path(cwd or os.getcwd()).resolve()
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True,
                             text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd


def account_tag():
    acct = os.environ.get("CLAUDE_CODE_ACCOUNT_UUID", "")
    return hashlib.sha256(acct.encode()).hexdigest()[:16] if acct else ""


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_atomic(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


class Lock:
    """Cross-platform lock file per project; waits up to `wait` seconds, then gives up."""
    def __init__(self, key, wait=120, stale=600):
        self.path = STATE_DIR / f"lock-{hashlib.sha1(key.encode()).hexdigest()[:12]}"
        self.wait, self.stale, self.fd = wait, stale, None

    def __enter__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.wait
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink()
                        continue
                except OSError:
                    pass
                if time.time() >= deadline:
                    return None
                time.sleep(1)

    def __exit__(self, *a):
        if self.fd is not None:
            os.close(self.fd)
            try:
                self.path.unlink()
            except OSError:
                pass


# ---------- prefilter ----------

def texts_of(content):
    if isinstance(content, str):
        return [content]
    return [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]


def strip_pasted(s):
    s = re.sub(r"```.*?```", " [code] ", s, flags=re.S)
    return "\n".join(l for l in s.splitlines() if not l.lstrip().startswith(">"))


def tool_summary(block):
    inp = block.get("input") or {}
    detail = inp.get("command") or inp.get("file_path") or inp.get("description") or ""
    return clip(redact(f"{block.get('name')}: {detail}"), 200)


def prefilter(transcript, offset=0):
    """Scan user-typed text after `offset` (bytes). Returns (signals, new_offset)."""
    p = Path(transcript)
    try:
        size = p.stat().st_size
    except OSError:
        return [], offset
    if offset > size:
        offset = 0
    signals, last_ai, tools_by_id, pending_follow = [], "", {}, None
    start = max(0, offset - 200_000)
    with open(p, "rb") as f:
        f.seek(start)
        if start:
            f.readline()
        pos = f.tell()
        for raw in f:
            if not raw.endswith(b"\n"):
                break
            line_pos, pos = pos, pos + len(raw)
            fresh = line_pos >= offset
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if d.get("isSidechain"):
                continue
            t, msg = d.get("type"), d.get("message") or {}
            content = msg.get("content")
            if t == "assistant":
                for b in content if isinstance(content, list) else []:
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                        last_ai = clip(redact(b["text"]), 300)
                    elif isinstance(b, dict) and b.get("type") == "tool_use":
                        tools_by_id[b.get("id")] = tool_summary(b)
                        last_ai = "(was running) " + tools_by_id[b.get("id")]
                continue
            if t != "user" or d.get("isMeta"):
                continue
            ts = (d.get("timestamp") or "")[:10]
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        txt = " ".join(texts_of(b.get("content"))).strip()
                        if fresh and b.get("is_error") and txt.startswith(REJECT_PREFIX):
                            signals.append({"signal": "rejected_tool_call", "date": ts,
                                            "claude_was": tools_by_id.get(b.get("tool_use_id"), last_ai),
                                            "user": clip(redact(txt), 400)})
                            pending_follow = "after_rejection"
            origin = (d.get("origin") or {}).get("kind")
            for txt in texts_of(content):
                s = txt.strip()
                if not s:
                    continue
                if s.startswith("[Request interrupted"):
                    if fresh:
                        pending_follow = "after_interrupt"
                    continue
                if (origin and origin != "human") or (not origin and s.startswith(SKIP_PREFIXES)):
                    continue
                body = strip_pasted(s)
                hit = CORRECTION_RE.search(body[:1500])
                if fresh and (hit or pending_follow):
                    signals.append({"signal": pending_follow or "keyword", "date": ts,
                                    "claude_was": last_ai, "user": clip(redact(body), 700)})
                pending_follow = None
    return signals[-25:], pos


# ---------- suggestions file ----------

def sugg_path(root):
    return Path(root) / FILE_REL


def parse_state(text):
    i = text.find(STATE_BEGIN)
    if i < 0:
        return None
    j = text.find(STATE_END, i + len(STATE_BEGIN))
    try:
        return json.loads(text[i + len(STATE_BEGIN): j]).get("items", [])
    except ValueError:
        return None


def conflict_sides(text):
    """Split a file with git conflict markers into its two whole-file versions."""
    ours, theirs, side = [], [], None
    for line in text.splitlines():
        if line.startswith("<<<<<<< "):
            side = "ours"
        elif line.startswith("||||||| ") and side:
            side = "base"
        elif line == "=======" and side:
            side = "theirs"
        elif line.startswith(">>>>>>> ") and side:
            side = None
        elif side is None:
            ours.append(line)
            theirs.append(line)
        elif side == "ours":
            ours.append(line)
        elif side == "theirs":
            theirs.append(line)
    return "\n".join(ours), "\n".join(theirs)


RANK = {"watching": 0, "pending": 1, "resolved": 2, "applied": 3, "rejected": 4}


def union(a, b):
    """Combine two histories of the same suggestions, e.g. from two branches."""
    by_id = {i["id"]: dict(i) for i in a}
    for it in b:
        cur = by_id.get(it["id"])
        if not cur:
            by_id[it["id"]] = dict(it)
            continue
        cur["status"] = max(cur["status"], it["status"], key=lambda s: RANK.get(s, 0))
        cur["count"] = max(cur["count"], it["count"])
        cur["sessions"] = list(dict.fromkeys(cur["sessions"] + it["sessions"]))[-20:]
        cur["evidence"] = list(dict.fromkeys(cur["evidence"] + it["evidence"]))[-3:]
        cur["first_seen"] = min(cur["first_seen"], it["first_seen"])
        cur["last_seen"] = max(cur["last_seen"], it["last_seen"])
        if "strong" in (cur["strength"], it["strength"]):
            cur["strength"] = "strong"
        if cur["status"] == "watching" and (cur["strength"] == "strong" or len(cur["sessions"]) >= 2):
            cur["status"] = "pending"
    return list(by_id.values())


def load_state(root):
    """Returns (items, repaired). Git conflict markers are merged, not fatal."""
    p = sugg_path(root)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return [], False
    if "\n<<<<<<< " in "\n" + text:
        sides = [parse_state(t) for t in conflict_sides(text)]
        good = [x for x in sides if x is not None]
        if not good:
            log(f"conflicted state in {p} unreadable on both sides; left as is")
            return [], False
        log(f"merged a git conflict in {p}")
        return union(good[0], good[1]) if len(good) == 2 else good[0], True
    items = parse_state(text)
    if items is None:
        log(f"state block unreadable in {p}; starting fresh")
        return [], False
    return items, False


def load_items(root):
    return load_state(root)[0]


LABEL = {"add": "Add", "change": "Change", "remove": "Remove", "conflict": "Conflict"}


def render_item(it):
    where = it.get("file") or it["destination"]
    head = (f"**[{it['id']}] {LABEL[it['kind']]} · {it['destination']} · {it['strength']} · "
            f"seen {it['count']}× (last {it['last_seen']})**")
    lines = [head]
    if it.get("current"):
        lines.append(f"- Current ({where}): `{it['current']}`")
    if it.get("proposed"):
        lines.append(f"- Proposed: {it['proposed']}")
    if it.get("why"):
        lines.append(f"- Why: {it['why']}")
    for ev in it.get("evidence", [])[-3:]:
        lines.append(f"- Evidence: {ev}")
    return "\n".join(lines)


def save_items(root, items):
    order = {"strong": 0, "weak": 1}
    items.sort(key=lambda i: (order.get(i["strength"], 2), -i["count"], i["id"]))
    out = ["# Claude setup suggestions", "",
           "Written by the claude-setup learning hook. Nothing here is applied until you approve it "
           "with `/claude-setup review`. Edit by running the review, not by hand: the state block at "
           "the bottom is what the hook reads. If git reports a merge conflict here, keep both sides "
           "(or leave the markers): the next hook run or `/claude-setup review` merges them.", ""]
    if IS_CLOUD:
        out += ["_Cloud session: this file is committed so it survives the container. Global items "
                "stay pending until you review them in a local session._", ""]
    for status, title in (("pending", "Pending"), ("watching", "Watching (seen once, weak)")):
        group = [i for i in items if i["status"] == status]
        out += [f"## {title} ({len(group)})", ""]
        for scope in ("project", "global"):
            sub = [i for i in group if i["scope"] == scope]
            if sub:
                out += [f"### {scope.capitalize()}", ""]
                for it in sub:
                    out += [render_item(it), ""]
        if not group:
            out += ["_None._", ""]
    done = {s: sum(1 for i in items if i["status"] == s) for s in ("applied", "rejected", "resolved")}
    out += [f"Applied {done['applied']} · Rejected {done['rejected']} (remembered so they don't "
            f"come back) · Already in place {done['resolved']}", ""]
    out += [STATE_BEGIN, json.dumps({"version": 1, "items": items}, indent=1, ensure_ascii=False),
            STATE_END, ""]
    p = sugg_path(root)
    new = not p.exists()
    write_atomic(p, "\n".join(out))
    if new and not IS_CLOUD:
        exclude_locally(root)


def exclude_locally(root):
    """Keep the file out of git locally without touching the repo's .gitignore."""
    try:
        chk = subprocess.run(["git", "check-ignore", "-q", str(FILE_REL)], cwd=root, timeout=10)
        if chk.returncode == 0:
            return
        gd = subprocess.run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=root,
                            capture_output=True, text=True, timeout=10)
        if gd.returncode != 0:
            return
        ex = Path(root) / gd.stdout.strip()
        ex.parent.mkdir(parents=True, exist_ok=True)
        with open(ex, "a", encoding="utf-8") as f:
            f.write(f"\n# claude-setup learning hook (local only)\n/{FILE_REL.as_posix()}\n")
    except (OSError, subprocess.SubprocessError):
        pass


def target_file(root, it):
    if it["destination"] != "claude_md":
        return None
    if it["scope"] == "global":
        return HOME_CLAUDE / "CLAUDE.md"
    f = (it.get("file") or "").strip()
    if f and not f.startswith(("~", "/")) and ".." not in f and (Path(root) / f).is_file():
        return Path(root) / f
    for cand in ("CLAUDE.md", ".claude/CLAUDE.md"):
        if (Path(root) / cand).is_file():
            return Path(root) / cand
    return None


RULE_RE = re.compile(r"\b(?:Bash|Read|Edit|Write|WebFetch|WebSearch|Glob|Grep|NotebookEdit|mcp__[\w-]+)(?:\([^)]*\))?")


def permission_done(root, it):
    rules = RULE_RE.findall(it.get("proposed") or "")
    if not rules:
        return False
    files = ([HOME_CLAUDE / "settings.json"] if it["scope"] == "global"
             else [Path(root) / ".claude" / "settings.json", Path(root) / ".claude" / "settings.local.json"])
    have = set()
    for f in files:
        perms = (load_json(f, {}) or {}).get("permissions") or {}
        for k in ("allow", "ask", "deny"):
            have.update(perms.get(k) or [])
    return bool(have) and all(r in have for r in rules)


def reconcile(root, items, expire_days=30):
    """Mark items already reflected in the current files; drop stale weak ones."""
    changed = False
    for it in items:
        if it["status"] not in ("pending", "watching"):
            continue
        if it["destination"] == "permission" and permission_done(root, it):
            it["status"], changed = "resolved", True
            continue
        tf = target_file(root, it)
        if not tf or not tf.is_file():
            continue
        text = norm(tf.read_text(encoding="utf-8", errors="replace"))
        prop, cur = norm(it.get("proposed")), norm(it.get("current"))
        done = ((it["kind"] in ("add", "change", "conflict") and prop and prop in text)
                or (it["kind"] == "remove" and cur and cur not in text))
        if done:
            it["status"], changed = "resolved", True
    if expire_days:
        cutoff = (now() - dt.timedelta(days=expire_days)).strftime("%Y-%m-%d")
        keep = [i for i in items if not (i["status"] == "watching" and i["last_seen"] < cutoff)]
        changed = changed or len(keep) != len(items)
        items[:] = keep
    return changed


def quote_missing(root, pr):
    """A remove whose quoted line isn't in the target file is a misquote, not a done item."""
    if pr["kind"] != "remove":
        return False
    tf = target_file(root, pr)
    if not tf or not tf.is_file():
        return False
    return norm(pr["current"]) not in norm(tf.read_text(encoding="utf-8", errors="replace"))


def merge(items, proposals, session, root):
    by_id = {i["id"]: i for i in items}
    added = 0
    for pr in proposals:
        if not pr.get("durable") or quote_missing(root, pr):
            continue
        key = f"{pr['scope']}|{pr['destination']}|{norm(pr['proposed'] or pr['current'])}"
        iid = hashlib.sha1(key.encode()).hexdigest()[:8]
        it = by_id.get(pr.get("same_as") or "") or by_id.get(iid)
        ev = f"{today()}: {clip(redact(pr['evidence']), 160)}"
        if it:
            if it["status"] in ("rejected", "applied", "resolved"):
                continue
            it["count"] += 1
            it["last_seen"] = today()
            if session and session not in it["sessions"]:
                it["sessions"] = (it["sessions"] + [session])[-20:]
            it["evidence"] = (it["evidence"] + [ev])[-3:]
            if pr["strength"] == "strong":
                it["strength"] = "strong"
            if it["strength"] == "strong" or len(it["sessions"]) >= 2:
                it["status"] = "pending"
            continue
        it = {"id": iid, "kind": pr["kind"], "scope": pr["scope"], "destination": pr["destination"],
              "file": clip(pr.get("file"), 120), "current": clip(redact(pr.get("current")), 300),
              "proposed": clip(redact(pr.get("proposed")), 300), "why": clip(redact(pr.get("why")), 200),
              "strength": pr["strength"], "count": 1, "sessions": [session] if session else [],
              "first_seen": today(), "last_seen": today(), "evidence": [ev],
              "status": "pending" if pr["strength"] == "strong" or pr["kind"] == "conflict" else "watching"}
        if it["kind"] == "conflict":
            it["strength"] = "strong"
        items.append(it)
        by_id[iid] = it
        added += 1
    return added


def valid(pr):
    try:
        return (pr["kind"] in LABEL and pr["scope"] in ("project", "global")
                and pr["destination"] in SCHEMA["properties"]["items"]["items"]["properties"]["destination"]["enum"]
                and pr["strength"] in ("strong", "weak") and isinstance(pr["durable"], bool)
                and all(isinstance(pr[k], str) for k in ("file", "current", "proposed", "evidence", "why", "same_as"))
                and (pr["proposed"].strip() or pr["kind"] == "remove")
                and (pr["current"].strip() or pr["kind"] == "add"))
    except (KeyError, TypeError):
        return False


# ---------- model call ----------

def setup_context(root):
    parts = []
    for p in (HOME_CLAUDE / "CLAUDE.md", Path(root) / "CLAUDE.md", Path(root) / ".claude" / "CLAUDE.md"):
        if p.is_file():
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[:250]
            label = "~/.claude/CLAUDE.md (global)" if p.parent == HOME_CLAUDE else str(p.relative_to(root))
            parts.append(f"--- {label}\n" + "\n".join(f"{n + 1}: {l}" for n, l in enumerate(lines)))
    return "\n\n".join(parts) or "(no CLAUDE.md files)"


def build_prompt(root, items, signals):
    open_items = [f"[{i['id']}] {i['kind']} {i['scope']}: {i['proposed'] or i['current']}"
                  for i in items if i["status"] in ("pending", "watching")]
    rejected = [f"[{i['id']}] {i['proposed'] or i['current']}" for i in items if i["status"] == "rejected"]
    sig = "\n\n".join(f"#{n + 1} ({s['signal']}, {s['date']})\nClaude was: {s['claude_was'] or '-'}\n"
                      f"User: {s['user']}" for n, s in enumerate(signals))
    return (f"CURRENT SETUP FILES\n{setup_context(root)}\n\nOPEN SUGGESTIONS\n"
            f"{chr(10).join(open_items) or '(none)'}\n\nREJECTED\n{chr(10).join(rejected) or '(none)'}\n\n"
            f"SESSION EXCERPTS (text the user typed, plus interrupts and rejected tool calls)\n{sig}")


def call_model(prompt, budget):
    exe = shutil.which("claude")
    if not exe:
        log("claude CLI not on PATH; skipped")
        return None
    env = dict(os.environ, **{CHILD_ENV: "1"})
    cmd = [exe, "-p", "--model", MODEL, "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
           "--no-session-persistence", "--tools", "", "--system-prompt", SYSTEM_PROMPT,
           "--max-budget-usd", str(budget)]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=300, env=env,
                           cwd=STATE_DIR)
        out = json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        log(f"model call failed: {type(e).__name__}")
        return None
    log(f"model run: subtype={out.get('subtype')} cost=${out.get('total_cost_usd')}")
    so = out.get("structured_output")
    if not isinstance(so, dict) or not isinstance(so.get("items"), list):
        log("model returned no structured output; discarded")
        return None
    good = [p for p in so["items"] if isinstance(p, dict) and valid(p)]
    if len(good) != len(so["items"]):
        log(f"discarded {len(so['items']) - len(good)} malformed item(s)")
    return good


# ---------- commands ----------

def cmd_analyze(a):
    root = project_root(a.cwd)
    with Lock(str(root), wait=120 if not IS_CLOUD else 30) as lk:
        if lk is None:
            log(f"{root.name}: busy, skipped this pass")
            return 0
        state_p = STATE_DIR / "learn-state.json"
        state = load_json(state_p, {"offsets": {}, "runs": {}})
        key = str(Path(a.transcript).resolve())
        signals, new_off = prefilter(a.transcript, state["offsets"].get(key, 0))
        state["offsets"][key] = new_off
        state["runs"] = {d: n for d, n in state.get("runs", {}).items() if d >= today()}
        if not signals:
            write_atomic(state_p, json.dumps(state))
            return 0
        if state["runs"].get(today(), 0) >= a.daily_cap:
            log(f"daily cap {a.daily_cap} reached; {len(signals)} signal(s) skipped")
            write_atomic(state_p, json.dumps(state))
            return 0
        state["runs"][today()] = state["runs"].get(today(), 0) + 1
        write_atomic(state_p, json.dumps(state))
        items, repaired = load_state(root)
        proposals = call_model(build_prompt(root, items, signals), a.budget)
        if proposals is None:
            return 0
        added = merge(items, proposals, a.session or Path(a.transcript).stem, root)
        reconcile(root, items, a.expire_days)
        if proposals or repaired or sugg_path(root).exists():
            save_items(root, items)
        log(f"{root.name}: {len(signals)} signal(s), {len(proposals)} proposal(s), {added} new")
    return 0


def hook_input_ok(d):
    tp = d.get("transcript_path")
    return tp and Path(tp).suffix == ".jsonl" and ".." not in Path(tp).parts


def only_account_ok(a):
    return not a.only_account or a.only_account == account_tag()


def cmd_session_end(a):
    d = read_stdin_json()
    if os.environ.get(CHILD_ENV) or IS_CLOUD or not hook_input_ok(d):
        return 0
    args = [sys.executable, os.path.abspath(__file__), "analyze", "--transcript", d["transcript_path"],
            "--cwd", d.get("cwd") or os.getcwd(), "--session", str(d.get("session_id") or ""),
            "--expire-days", str(a.expire_days), "--daily-cap", str(a.daily_cap), "--budget", str(a.budget)]
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
          "env": dict(os.environ, **{CHILD_ENV: ""})}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen(args, **kw)  # outlives the ~1.5-3.5 s SessionEnd window
    except OSError as e:
        log(f"could not start background analysis: {e}")
    return 0


def dirty(root):
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--", str(FILE_REL)], cwd=root,
                           capture_output=True, text=True, timeout=10)
        return bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def cmd_stop(a):
    d = read_stdin_json()
    if os.environ.get(CHILD_ENV) or not IS_CLOUD or not only_account_ok(a) or not hook_input_ok(d):
        return 0
    a.transcript, a.cwd, a.session = d["transcript_path"], d.get("cwd"), str(d.get("session_id") or "")
    root = project_root(a.cwd)
    items, repaired = load_state(root)
    if repaired:
        save_items(root, items)
    cmd_analyze(a)
    if sugg_path(root).exists() and dirty(root) and not d.get("stop_hook_active"):
        print(f"claude-setup learning hook: {FILE_REL.as_posix()} was updated. Commit it on the "
              "current branch and push, the same way you push your other work (no new branch). Then "
              "stop without a summary: your earlier reply stands, and the user doesn't need to hear "
              "about this file.", file=sys.stderr)
        return 2
    return 0


def cmd_session_start(a):
    d = read_stdin_json()
    if os.environ.get(CHILD_ENV) or not only_account_ok(a):
        return 0
    root = project_root(d.get("cwd") or a.cwd)
    items, repaired = load_state(root)
    if items and (reconcile(root, items, a.expire_days) or repaired):
        save_items(root, items)
    n = sum(1 for i in items if i["status"] == "pending")
    if n:
        noun = "suggestion" if n == 1 else "suggestions"
        msg = (f"claude-setup: {n} setup {noun} pending. At the very end of your first reply in this "
               f"session, add one line: \"{n} setup {noun} pending - run /claude-setup review\". Say it "
               "once. Never list or describe them, and don't open the file unless the user asks.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
    return 0


def cmd_status(a):
    root = project_root(a.cwd)
    items = load_items(root)
    counts = {s: sum(1 for i in items if i["status"] == s)
              for s in ("pending", "watching", "applied", "rejected", "resolved")}
    print(json.dumps({"file": str(sugg_path(root)), "version": VERSION, "cloud": IS_CLOUD, "counts": counts,
                      "open": [i for i in items if i["status"] in ("pending", "watching")]},
                     indent=1, ensure_ascii=False))
    return 0


def cmd_reconcile(a):
    root = project_root(a.cwd)
    items, repaired = load_state(root)
    if reconcile(root, items, a.expire_days) or repaired:
        save_items(root, items)
    return cmd_status(a)


def cmd_resolve(a):
    root = project_root(a.cwd)
    items = load_items(root)
    it = next((i for i in items if i["id"] == a.id), None)
    if not it:
        print(f"no suggestion with id {a.id}", file=sys.stderr)
        return 1
    if a.status == "applied" and it["scope"] == "global" and IS_CLOUD:
        print("global items can't be applied in a cloud session (~/.claude is discarded with the "
              "container); it stays pending until a local session", file=sys.stderr)
        return 1
    it["status"] = a.status
    save_items(root, items)
    print(f"{a.id} -> {a.status}")
    return 0


def cmd_prefilter(a):
    files = []
    if a.all_projects:
        cutoff = time.time() - a.days * 86400
        files = [f for f in (HOME_CLAUDE / "projects").glob("*/*.jsonl") if f.stat().st_mtime >= cutoff]
    elif a.transcript:
        files = [Path(a.transcript)]
    hits, total = 0, 0
    for f in files:
        sig, _ = prefilter(f, 0)
        total += 1
        hits += bool(sig)
        if not a.all_projects:
            print(json.dumps(sig, indent=1, ensure_ascii=False))
    print(json.dumps({"sessions": total, "sessions_that_would_call_the_model": hits}))
    return 0


def hook_entry(event, cmd):
    h = {"type": "command", "command": cmd}
    if event != "SessionEnd":  # SessionEnd has a ~1.5-3.5 s budget regardless; the script detaches
        h["timeout"] = 300 if event == "Stop" else 30
    return {"hooks": [h]}


OPTION_RE = re.compile(r"--(expire-days|daily-cap|budget) (\S+)")


def option_args(a, existing):
    """Options given now win; otherwise keep what the previous install had."""
    opts = dict(OPTION_RE.findall(existing))
    for flag, val, default in (("expire-days", a.expire_days, 30), ("daily-cap", a.daily_cap, 10),
                               ("budget", a.budget, 0.25)):
        if val != default:
            opts[flag] = str(val)
    return "".join(f" --{k} {v}" for k, v in sorted(opts.items()))


def cmd_install(a, remove=False):
    root = project_root(a.cwd)
    if a.scope == "user":
        settings_p, script_p = HOME_CLAUDE / "settings.json", HOME_CLAUDE / "hooks" / HOOK_NAME
        run = f'"{sys.executable}" "{script_p}"'
        events = {"SessionStart": f"{run} session-start", "SessionEnd": f"{run} session-end"}
    else:
        settings_p, script_p = root / ".claude" / "settings.json", root / ".claude" / "hooks" / HOOK_NAME
        tag = account_tag()
        if not tag and not remove:
            print("project install is for cloud sessions and needs CLAUDE_CODE_ACCOUNT_UUID "
                  "(run it from a cloud session)", file=sys.stderr)
            return 1
        run = f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{HOOK_NAME}"'
        events = {"SessionStart": f"{run} session-start --only-account {tag}",
                  "Stop": f"{run} stop --only-account {tag}"}
    settings = load_json(settings_p, None) if settings_p.exists() else {}
    if not isinstance(settings, dict):
        print(f"{settings_p} is not valid JSON; not touching it", file=sys.stderr)
        return 1
    hooks = settings.setdefault("hooks", {})
    existing = " ".join(h.get("command", "") for gs in hooks.values() for g in gs
                        for h in g.get("hooks", []) if HOOK_NAME in h.get("command", ""))
    opts = option_args(a, existing)
    events = {ev: cmd + opts for ev, cmd in events.items()}
    for ev in list(hooks):
        hooks[ev] = [g for g in hooks[ev] if not any(HOOK_NAME in h.get("command", "")
                                                     for h in g.get("hooks", []))]
        if not hooks[ev]:
            del hooks[ev]
    if not remove:
        for ev, cmd in events.items():
            hooks.setdefault(ev, []).append(hook_entry(ev, cmd))
        script_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(__file__, script_p)
    elif script_p.exists():
        script_p.unlink()
    if not hooks:
        settings.pop("hooks", None)
    write_atomic(settings_p, json.dumps(settings, indent=2) + "\n")
    json.loads(settings_p.read_text(encoding="utf-8"))
    print(json.dumps({"settings": str(settings_p), "script": str(script_p), "version": VERSION,
                      "events": [] if remove else list(events), "options": opts.strip()}))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cwd", default=None)
    common.add_argument("--expire-days", type=int, default=30, help="drop weak unseen items; 0 = never")
    common.add_argument("--daily-cap", type=int, default=10, help="max model runs per day")
    common.add_argument("--budget", type=float, default=0.25, help="max USD per model run")
    common.add_argument("--only-account", default="")
    for name in ("session-start", "session-end", "stop", "status", "reconcile"):
        sub.add_parser(name, parents=[common])
    p = sub.add_parser("analyze", parents=[common])
    p.add_argument("--transcript", required=True)
    p.add_argument("--session", default="")
    p = sub.add_parser("prefilter", parents=[common])
    p.add_argument("--transcript")
    p.add_argument("--all-projects", action="store_true")
    p.add_argument("--days", type=int, default=90)
    p = sub.add_parser("resolve", parents=[common])
    p.add_argument("id")
    p.add_argument("--status", required=True, choices=["applied", "rejected", "pending"])
    for name in ("install", "uninstall"):
        sub.add_parser(name, parents=[common]).add_argument("--scope", required=True,
                                                            choices=["user", "project"])
    a = ap.parse_args()
    fn = {"session-start": cmd_session_start, "session-end": cmd_session_end, "stop": cmd_stop,
          "analyze": cmd_analyze, "status": cmd_status, "reconcile": cmd_reconcile,
          "resolve": cmd_resolve, "prefilter": cmd_prefilter,
          "install": cmd_install, "uninstall": lambda x: cmd_install(x, remove=True)}[a.cmd]
    try:
        return fn(a)
    except Exception as e:  # a hook must never break the session
        log(f"{a.cmd} error: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
