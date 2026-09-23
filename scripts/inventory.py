#!/usr/bin/env python
"""Deterministic inventory + heuristic lint of a Claude Code setup.

Collects every file that shapes Claude's context/behavior for a project
(CLAUDE.md stack, rules, skills, agents, commands, output styles, settings,
.mcp.json, auto memory) and emits measurements plus heuristic flags.

Heuristics are leads, not verdicts: the skill's reviewer must read the
flagged files and apply judgment. Secret values are always redacted.

Usage:
  python inventory.py [--project PATH] [--no-user] [--json]
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
USER_CLAUDE = HOME / ".claude"
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist",
    "build", ".next", ".nuxt", "target", "out", ".cache", "vendor",
    "Library", "Temp", "Packages", ".gradle", ".idea", "coverage",
}
MAX_WALK_FILES = 20000

SECRET_PATTERNS = [
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("stripe_key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer_literal", re.compile(r"Bearer\s+[A-Za-z0-9_\-\.=]{24,}")),
    ("discord_token", re.compile(r"\b[MN][A-Za-z\d]{23,25}\.[\w-]{6}\.[\w-]{27,}")),
]
SECRET_KEY_NAME = re.compile(r"(TOKEN(?!S)|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE_KEY|CREDENTIAL|AUTH_)", re.I)

ENFORCEMENT_RE = re.compile(r"\b(NEVER|ALWAYS|MUST NOT|MUST|DO NOT|DON'T|IMPORTANT|CRITICAL)\b")
VAGUE_RE = re.compile(
    r"(clean code|best practices|be careful|good code|high[- ]quality|properly|"
    r"readable code|maintainable|well[- ]structured|follow conventions|as needed|"
    r"when appropriate|use common sense|write good)", re.I)
IMPORT_RE = re.compile(r"(?:^|\s)@((?:~|\.{1,2})?[/\\]?[\w\-./\\]+\.\w+)")
BACKTICK_PATH_RE = re.compile(r"`([^`\s<>*?{}|$]+/[^`\s<>*?{}|$]*)`")
NPM_RUN_RE = re.compile(r"\b(?:npm|pnpm|yarn|bun) run\s+([\w:\-]*\w)")
MAKE_RE = re.compile(r"\bmake\s+([\w\-.]+)")
RISKY_BASH_PREFIXES = [
    "rm", "sudo", "curl", "wget", "git push", "git reset", "chmod", "chown",
    "dd", "mkfs", "ssh", "scp", "docker", "kubectl", "terraform", "npm publish",
    "powershell", "pwsh", "sh -c", "bash -c", "eval", "python -c", "node -e",
]
IGNORED_PATH_TOOLS = ("Write", "NotebookEdit", "Glob", "MultiEdit")


# ---------------------------------------------------------------- helpers

def read_text(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def rel(p, base):
    try:
        return str(Path(p).resolve().relative_to(Path(base).resolve())).replace("\\", "/")
    except Exception:
        return str(p).replace(str(HOME), "~").replace("\\", "/")


def measure(text):
    lines = text.splitlines()
    return {
        "lines": len(lines),
        "nonblank_lines": sum(1 for l in lines if l.strip()),
        "chars": len(text),
        "approx_tokens": round(len(text) / 4),
    }


def parse_frontmatter(text):
    """Return (dict, body). Uses PyYAML if present, else a small fallback."""
    if not text or not text.lstrip("\ufeff").startswith("---"):
        return {}, text or ""
    t = text.lstrip("\ufeff")
    m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", t, re.S)
    if not m:
        return {"_error": "unterminated frontmatter"}, t
    raw, body = m.group(1), t[m.end():]
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(raw) or {}
        if not isinstance(data, dict):
            return {"_error": "frontmatter is not a mapping"}, body
        return data, body
    except ImportError:
        pass
    except Exception as e:  # yaml present but invalid
        return {"_error": f"invalid YAML: {e.__class__.__name__}"}, body
    data, key = {}, None
    for line in raw.splitlines():
        if re.match(r"^[A-Za-z_][\w\-]*\s*:", line):
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            data[key] = [] if val == "" else val.strip("'\"")
        elif key and line.strip().startswith("- "):
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(line.strip()[2:].strip("'\""))
        elif key and line.startswith((" ", "\t")) and isinstance(data.get(key), str):
            data[key] = (data[key] + " " + line.strip()).strip()
    return data, body


def redact(s):
    s = str(s)
    return s[:4] + "…" + f"[{len(s)} chars redacted]" if len(s) > 8 else "[redacted]"


def scan_secrets(text, where):
    hits = []
    if not text:
        return hits
    for i, line in enumerate(text.splitlines(), 1):
        for name, rx in SECRET_PATTERNS:
            m = rx.search(line)
            if m:
                hits.append({"file": where, "line": i, "kind": name, "match": redact(m.group(0))})
    return hits


def git(args, cwd):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout.strip()
    except Exception:
        return 127, ""


def is_ignored(path, project, git_root):
    if git_root:
        code, _ = git(["check-ignore", "-q", str(path)], project)
        return code == 0
    gi = read_text(Path(project) / ".gitignore") or ""
    name = Path(path).name
    relp = rel(path, project)
    for pat in gi.splitlines():
        pat = pat.strip().lstrip("/")
        if pat and not pat.startswith("#") and (fnmatch.fnmatch(relp, pat) or fnmatch.fnmatch(name, pat)):
            return True
    return False


def is_tracked(path, project, git_root):
    if not git_root:
        return None
    code, out = git(["ls-files", "--error-unmatch", str(path)], project)
    return code == 0


def memory_dir_for(root):
    enc = re.sub(r"[^A-Za-z0-9]", "-", str(Path(root).resolve()))
    return USER_CLAUDE / "projects" / enc / "memory"


# ---------------------------------------------------------------- markdown lint

def lint_instructions(path, text, project, pkg_scripts, make_targets):
    fm, body = parse_frontmatter(text)
    info = {"path": rel(path, project), **measure(text)}
    if fm:
        info["frontmatter"] = {k: v for k, v in fm.items() if k in ("paths", "description", "name", "_error")}
    lines = body.splitlines()
    enforcement, vague, imports, stale, bad_scripts = [], [], [], [], []
    in_fence = False
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if ENFORCEMENT_RE.search(line):
            enforcement.append({"line": i, "text": s[:160]})
        if VAGUE_RE.search(line):
            vague.append({"line": i, "text": s[:160]})
        for m in IMPORT_RE.finditer(line):
            target = m.group(1)
            tp = Path(os.path.expanduser(target)) if target.startswith("~") else (Path(path).parent / target)
            imports.append({"line": i, "target": target, "exists": tp.exists()})
        for m in BACKTICK_PATH_RE.finditer(line):
            cand = m.group(1).rstrip(".,:;)")
            if cand.startswith(("http", "www.", "@", "-", "/", "~")) or "://" in cand:
                continue
            if not re.search(r"\.\w{1,6}$|/$", cand):
                continue
            if not ((Path(path).parent / cand).exists() or (Path(project) / cand).exists()
                    or any(Path(project).glob("*/" + cand)) or any(Path(project).glob("*/*/" + cand))):
                stale.append({"line": i, "path": cand})
        if pkg_scripts is not None:
            for m in NPM_RUN_RE.finditer(line):
                sc = m.group(1)
                if sc not in pkg_scripts and sc not in ("install", "add", "dlx", "exec", "test", "i", "x"):
                    bad_scripts.append({"line": i, "script": sc})
        if make_targets is not None:
            for m in MAKE_RE.finditer(line):
                if m.group(1) not in make_targets:
                    bad_scripts.append({"line": i, "make_target": m.group(1)})
    headings = [l.strip() for l in lines if l.startswith("#")]
    info.update({
        "headings": headings[:40],
        "enforcement_language": enforcement[:40],
        "vague_lines": vague[:25],
        "imports": imports,
        "possibly_stale_paths": stale[:30],
        "unknown_scripts": bad_scripts[:20],
        "html_comment_blocks": len(re.findall(r"<!--", text)),
    })
    flags = []
    if info["lines"] > 200:
        flags.append(f"over 200 lines ({info['lines']})")
    elif info["lines"] > 150:
        flags.append(f"approaching 200 lines ({info['lines']})")
    if len(re.findall(r"^\s*[-*]\s", body, re.M)) == 0 and info["lines"] > 30:
        flags.append("long prose with no bullet structure")
    if any(not im["exists"] for im in imports):
        flags.append("broken @import(s)")
    if re.search(r"(?i)generated by|this file provides guidance to claude code", text) and info["lines"] > 20:
        flags.append("looks like unedited /init output")
    if re.search(r"(?im)^#+\s*(project structure|directory structure|file structure|folder structure)", text):
        flags.append("contains a file-tree tour (usually derivable from code)")
    if re.search(r"(?im)^#+\s*(changelog|history|session log|lessons learned|corrections|notes from)", text):
        flags.append("reads like a memory/correction log")
    if info["nonblank_lines"] == 0:
        flags.append("empty file")
    info["flags"] = flags
    return info


def normalize_line(l):
    return re.sub(r"[^a-z0-9 ]", "", l.lower()).strip()


def find_duplicates(files_text):
    seen, dups = {}, []
    for where, text in files_text:
        for i, line in enumerate(text.splitlines(), 1):
            n = normalize_line(line)
            if len(n) < 30:
                continue
            if n in seen and seen[n][0] != where:
                dups.append({"a": f"{seen[n][0]}:{seen[n][1]}", "b": f"{where}:{i}", "text": line.strip()[:140]})
            else:
                seen.setdefault(n, (where, i))
    return dups[:30]


# ---------------------------------------------------------------- settings / permissions

def split_rule(rule):
    m = re.match(r"^([\w\-*]+)(?:\((.*)\))?$", rule.strip())
    return (m.group(1), m.group(2)) if m else (rule, None)


def spec_to_glob(spec):
    if spec is None:
        return "*"
    return spec.replace(":*", "*").replace(" *", "*")


def covers(broad, narrow):
    bt, bs = split_rule(broad)
    nt, ns = split_rule(narrow)
    if not fnmatch.fnmatch(nt, bt):
        return False
    if bs is None:
        return True
    if ns is None:
        return False
    return fnmatch.fnmatch(ns, spec_to_glob(bs)) or ns == bs


def lint_settings(path, data, project, scope):
    out = {"path": rel(path, project), "scope": scope, "flags": [], "keys": sorted(data.keys())}
    perms = data.get("permissions", {}) or {}
    allow, ask, deny = perms.get("allow", []) or [], perms.get("ask", []) or [], perms.get("deny", []) or []
    out["permissions"] = {"allow": len(allow), "ask": len(ask), "deny": len(deny),
                          "defaultMode": perms.get("defaultMode"),
                          "additionalDirectories": perms.get("additionalDirectories", [])}
    f = out["flags"]
    if perms.get("defaultMode") in ("bypassPermissions",):
        f.append({"sev": "high", "msg": "defaultMode is bypassPermissions"})
    if data.get("skipDangerousModePermissionPrompt"):
        f.append({"sev": "medium", "msg": "skipDangerousModePermissionPrompt is true"})
    for r in allow:
        t, s = split_rule(r)
        if t == "Bash" and (s is None or s.strip() in ("*", ":*", "")):
            f.append({"sev": "high", "msg": f"allow '{r}' approves every shell command"})
        elif t == "Bash" and s:
            head = s.replace(":*", "").replace("*", "").strip()
            for p in RISKY_BASH_PREFIXES:
                if head == p or head.startswith(p + " "):
                    f.append({"sev": "medium", "msg": f"allow '{r}' pre-approves a risky command family"})
                    break
        if t in ("Edit", "Write") and s is None:
            f.append({"sev": "low", "msg": f"allow '{r}' approves edits anywhere in scope"})
        if t == "WebFetch" and s is None:
            f.append({"sev": "low", "msg": "allow 'WebFetch' with no domain restriction"})
        if t.startswith("mcp__") and t.endswith("*"):
            f.append({"sev": "low", "msg": f"allow '{r}' wildcard-approves MCP tools"})
    for r in allow + ask + deny:
        t, s = split_rule(r)
        if t in IGNORED_PATH_TOOLS and s and s.strip() in ("*", "**"):
            f.append({"sev": "low", "msg": f"'{r}' is equivalent to bare '{t}' (redundant spelling)"})
        elif t in IGNORED_PATH_TOOLS and s:
            f.append({"sev": "medium", "msg": f"'{r}' is a path rule on {t}; only Read(...)/Edit(...) path rules are enforced"})
        if t == "Bash" and s and re.search(r"https?://|--?\w", s) and r in deny + ask:
            f.append({"sev": "low", "msg": f"'{r}' constrains Bash arguments; easily bypassed (not a security boundary)"})
    for a in allow:
        for d in deny + ask:
            if covers(d, a):
                f.append({"sev": "low", "msg": f"allow '{a}' is shadowed by '{d}' (deny/ask evaluated first)"})
                break
    if (data.get("enableAllProjectMcpServers")):
        f.append({"sev": "medium", "msg": "enableAllProjectMcpServers auto-approves every server in any .mcp.json"})
    env = data.get("env", {}) or {}
    for k, v in env.items():
        if SECRET_KEY_NAME.search(k) and isinstance(v, str) and len(v) > 8 and "${" not in v and not re.fullmatch(r"[\d.]+|true|false", v, re.I):
            f.append({"sev": "high", "msg": f"env.{k} holds a literal secret-looking value ({redact(v)})"})
    hooks = data.get("hooks", {}) or {}
    hook_list = []
    for event, groups in hooks.items():
        for g in groups or []:
            for h in (g or {}).get("hooks", []) or []:
                cmd = h.get("command") or h.get("url") or h.get("prompt") or ""
                entry = {"event": event, "matcher": g.get("matcher"), "type": h.get("type"),
                         "command": cmd[:200], "timeout": h.get("timeout")}
                issues = []
                if "$CLAUDE_PROJECT_DIR" in cmd and '"$CLAUDE_PROJECT_DIR' not in cmd and "'$CLAUDE_PROJECT_DIR" not in cmd:
                    issues.append("unquoted $CLAUDE_PROJECT_DIR")
                if re.search(r"\b(curl|wget|Invoke-WebRequest|iwr)\b", cmd):
                    issues.append("network call in hook")
                if re.search(r"(^|\s)\.{0,2}/?[\w\-]+/[\w\-./]+\.(sh|py|js|ps1)", cmd) and "$CLAUDE_PROJECT_DIR" not in cmd and not re.search(r"^[\"']?(/|~|[A-Za-z]:)", cmd.strip()):
                    issues.append("relative script path (breaks when cwd changes)")
                if re.search(r"\beval\b|\|\s*(sh|bash)\b", cmd):
                    issues.append("eval / pipe-to-shell")
                if event == "SessionEnd" and (h.get("timeout") or 0) > 2:
                    issues.append("SessionEnd hooks share a ~1.5s budget; long timeout is ineffective unless the script detaches")
                if event in ("UserPromptSubmit", "PreToolUse") and g.get("matcher") in (None, "", "*") and h.get("type") in ("agent", "prompt"):
                    issues.append("model-backed hook on every call (latency/cost)")
                script = re.search(r"([\w\-./\\$\"{}~:]+\.(?:sh|py|js|mjs|ps1))", cmd)
                if script:
                    sp = script.group(1).strip("\"'").replace("$CLAUDE_PROJECT_DIR", str(project)).replace("${CLAUDE_PROJECT_DIR}", str(project)).replace("~", str(HOME))
                    if not Path(sp).is_absolute():
                        sp = str(Path(project) / sp)
                    entry["script_exists"] = Path(sp).exists()
                    if not entry["script_exists"]:
                        issues.append("hook script not found")
                entry["issues"] = issues
                hook_list.append(entry)
    out["hooks"] = hook_list
    out["allow_rules"] = allow[:25] + ([f"... {len(allow) - 25} more"] if len(allow) > 25 else [])
    out["ask_rules"] = ask[:40]
    out["deny_rules"] = deny
    for k in ("model", "outputStyle", "autoMemoryEnabled", "claudeMdExcludes", "sandbox",
              "enabledPlugins", "disableAllHooks", "includeCoAuthoredBy", "enabledMcpjsonServers",
              "disabledMcpjsonServers"):
        if k in data:
            v = data[k]
            out.setdefault("notable", {})[k] = v if not isinstance(v, dict) or len(json.dumps(v)) < 400 else "(large object)"
    return out


def lint_mcp(path, data, project):
    out = {"path": rel(path, project), "servers": [], "flags": []}
    for name, cfg in (data.get("mcpServers") or {}).items():
        cfg = cfg or {}
        s = {"name": name, "type": cfg.get("type") or ("stdio" if "command" in cfg else "?"),
             "command": " ".join([str(cfg.get("command", ""))] + [str(a) for a in cfg.get("args", [])])[:160] or None,
             "url": cfg.get("url"), "issues": []}
        for section in ("env", "headers"):
            for k, v in (cfg.get(section) or {}).items():
                if isinstance(v, str) and v and "${" not in v and (SECRET_KEY_NAME.search(k) or any(rx.search(v) for _, rx in SECRET_PATTERNS)):
                    s["issues"].append(f"{section}.{k} is a literal secret ({redact(v)}); use ${{VAR}} expansion")
        url = cfg.get("url") or ""
        if url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
            s["issues"].append("remote server over plain http")
        args = [str(a) for a in cfg.get("args", [])]
        if cfg.get("command") in ("npx", "bunx", "uvx", "pnpm") or (args and args[0] in ("dlx",)):
            pkgs = [a for a in args if not a.startswith("-") and a not in ("dlx",)]
            if pkgs and ("@latest" in pkgs[0] or not re.search(r"@\d", pkgs[0])):
                s["issues"].append(f"unpinned package '{pkgs[0]}' fetched at launch (supply-chain risk)")
        out["servers"].append(s)
    return out


# ---------------------------------------------------------------- extensions

def lint_skill(skill_md, project, scope):
    text = read_text(skill_md) or ""
    fm, body = parse_frontmatter(text)
    d = Path(skill_md).parent
    desc = str(fm.get("description") or "")
    wtu = str(fm.get("when_to_use") or "")
    info = {"name": fm.get("name") or d.name, "dir": d.name, "scope": scope, "path": rel(skill_md, project),
            "body_lines": len(body.splitlines()), "description_chars": len(desc) + len(wtu),
            "description": desc[:300], "flags": []}
    f = info["flags"]
    if "_error" in fm:
        f.append(fm["_error"])
    if not desc:
        f.append("missing description (Claude cannot auto-invoke reliably)")
    elif len(desc) < 60:
        f.append("very short description; add what it does AND when to use it")
    if len(desc) + len(wtu) > 1536:
        f.append("description+when_to_use over 1536 chars (truncated in listings)")
    mostly_ascii = sum(c.isascii() for c in desc) > 0.8 * max(len(desc), 1)
    if desc and mostly_ascii and not re.search(r"(?i)\b(use (when|this|for|whenever)|trigger|when the user|invoke)", desc + " " + wtu):
        f.append("description lacks 'when to use' trigger language")
    if re.search(r"(CRITICAL|MUST|ALWAYS invoke|NEVER)|(?i:if in doubt)", desc):
        f.append("description uses shouting/blanket-fallback wording (CRITICAL/MUST/'if in doubt'): overtriggers on current models; use conditional 'Use when...' + exclusions")
    if desc and not re.search(r"`|\.[a-z]{2,5}|/[a-z]|\"|'[^']{4,}'|“", desc):
        f.append("description has no literal trigger tokens (file names, commands, quoted phrasings); activation depends heavily on exact words")
    if re.search(r"(?i)^\s*(i |i'm |i can|you can)", desc):
        f.append("description written in first/second person; use third person")
    if info["body_lines"] > 500:
        f.append(f"SKILL.md body over 500 lines ({info['body_lines']}); split into reference files")
    if fm.get("name") and str(fm["name"]) != d.name and ":" not in str(fm["name"]):
        f.append(f"frontmatter name '{fm['name']}' differs from directory '{d.name}'")
    for m in re.finditer(r"\]\(([^)#\s]+)\)", body):
        target = m.group(1)
        if "://" in target or target.startswith("mailto:"):
            continue
        if not (d / target).exists():
            f.append(f"links to missing file '{target}'")
    if fm.get("allowed-tools") and re.search(r"\bBash\b(?!\()", str(fm.get("allowed-tools"))):
        f.append("allowed-tools pre-approves unrestricted Bash")
    return info


def lint_agent(path, project, scope):
    text = read_text(path) or ""
    fm, body = parse_frontmatter(text)
    desc = str(fm.get("description") or "")
    info = {"name": fm.get("name"), "scope": scope, "path": rel(path, project), "tools": fm.get("tools"),
            "model": fm.get("model"), "permissionMode": fm.get("permissionMode"),
            "description_chars": len(desc), "body_lines": len(body.splitlines()), "flags": []}
    f = info["flags"]
    if "_error" in fm:
        f.append(fm["_error"])
    if not fm.get("name"):
        f.append("missing required 'name'")
    if not desc:
        f.append("missing required 'description'")
    elif not re.search(r"(?i)(use (when|this|for|proactively)|when the user|after|before)", desc):
        f.append("description lacks delegation trigger ('Use when…' / 'use proactively')")
    if not fm.get("tools") and not fm.get("disallowedTools"):
        f.append("no tools restriction (inherits every tool incl. MCP)")
    if fm.get("permissionMode") == "bypassPermissions":
        f.append("permissionMode: bypassPermissions")
    if info["body_lines"] < 5:
        f.append("near-empty system prompt body")
    return info


def lint_simple_md(path, project, scope, kind):
    text = read_text(path) or ""
    fm, body = parse_frontmatter(text)
    info = {"name": Path(path).stem, "scope": scope, "kind": kind, "path": rel(path, project),
            "lines": len(text.splitlines()), "description": str(fm.get("description") or "")[:200], "flags": []}
    if kind == "command" and not fm.get("description"):
        info["flags"].append("no description frontmatter (shows poorly in / menu)")
    if "_error" in fm:
        info["flags"].append(fm["_error"])
    return info


# ---------------------------------------------------------------- main

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.getcwd())
    ap.add_argument("--no-user", action="store_true", help="skip ~/.claude user-level files")
    ap.add_argument("--json", action="store_true", help="emit JSON (default: compact JSON too, pretty)")
    args = ap.parse_args()
    project = Path(args.project).resolve()
    code, git_root = git(["rev-parse", "--show-toplevel"], project)
    git_root = Path(git_root).resolve() if code == 0 and git_root else None
    root = git_root or project

    report = {"project": str(project), "git_root": str(git_root) if git_root else None,
              "is_git_repo": bool(git_root), "claude_md_stack": [], "nested_claude_md": [],
              "agents_md": [], "rules": [], "skills": [], "agents": [], "commands": [],
              "output_styles": [], "settings": [], "mcp": [], "auto_memory": None,
              "gitignore": {}, "secrets": [], "duplicates": [], "migration_sources": [],
              "project_signals": {}}

    pkg = project / "package.json"
    pkg_scripts = None
    if pkg.exists():
        pkg_scripts = set()
        for pj in [pkg, *project.glob("*/package.json"), *project.glob("*/*/package.json")]:
            if "node_modules" in pj.parts:
                continue
            try:
                pkg_scripts |= set((json.loads(read_text(pj)) or {}).get("scripts", {}).keys())
            except Exception:
                pass
    mk = project / "Makefile"
    make_targets = set(re.findall(r"^([\w\-.]+):", read_text(mk) or "", re.M)) if mk.exists() else None
    signals = {}
    for marker in ("package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod",
                   "pom.xml", "build.gradle", "Gemfile", "composer.json", "Makefile", "Dockerfile",
                   "default.project.json", "wally.toml", "rokit.toml", "aftman.toml", "selene.toml",
                   "tsconfig.json", ".github/workflows", "README.md", "docs"):
        if (project / marker).exists():
            signals[marker] = True
    if pkg_scripts:
        signals["npm_scripts"] = sorted(pkg_scripts)[:30]
    report["project_signals"] = signals

    loaded_texts = []

    def add_stack(p, scope):
        t = read_text(p)
        if t is None:
            return
        info = lint_instructions(p, t, project, pkg_scripts, make_targets)
        info["scope"] = scope
        report["claude_md_stack"].append(info)
        loaded_texts.append((info["path"], t))
        report["secrets"].extend(scan_secrets(t, info["path"]))

    if not args.no_user:
        add_stack(USER_CLAUDE / "CLAUDE.md", "user")
    # ancestors (root -> project), then project-level files
    ancestors = list(reversed(project.parents))
    for a in ancestors:
        for name in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"):
            p = a / name
            if p.exists() and p.resolve() != (USER_CLAUDE / "CLAUDE.md").resolve():
                add_stack(p, "ancestor")
    for name, scope in (("CLAUDE.md", "project"), (".claude/CLAUDE.md", "project"), ("CLAUDE.local.md", "local")):
        p = project / name
        if p.exists():
            add_stack(p, scope)
    if (project / "CLAUDE.md").exists() and (project / ".claude/CLAUDE.md").exists():
        report["claude_md_stack"][-1].setdefault("flags", []).append("both ./CLAUDE.md and ./.claude/CLAUDE.md exist")

    # walk project for nested CLAUDE.md, AGENTS.md, migration sources, .env files
    env_files, walked = [], 0
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") or d in (".claude", ".github", ".cursor")]
        walked += len(filenames)
        if walked > MAX_WALK_FILES:
            report["walk_truncated"] = True
            break
        dp = Path(dirpath)
        if dp == project / ".claude":
            dirnames[:] = [d for d in dirnames if d not in ("worktrees", "backups", "agent-memory-local")]
        for fn in filenames:
            p = dp / fn
            parts = dp.relative_to(project).parts
            top_level = dp == project or (parts == (".claude",))
            if fn in ("CLAUDE.md", "CLAUDE.local.md") and not top_level and (not parts or parts[0] != ".claude"):
                t = read_text(p) or ""
                info = lint_instructions(p, t, project, pkg_scripts, make_targets)
                report["nested_claude_md"].append(info)
                report["secrets"].extend(scan_secrets(t, info["path"]))
            elif fn == "AGENTS.md":
                report["agents_md"].append({"path": rel(p, project), **measure(read_text(p) or "")})
            elif fn in (".cursorrules", "copilot-instructions.md", ".windsurfrules", "GEMINI.md", ".clinerules") or (dp.name == "rules" and dp.parent.name == ".cursor"):
                report["migration_sources"].append(rel(p, project))
            if fn == ".env" or (fn.startswith(".env.") and not fn.endswith((".example", ".sample", ".template"))) or fn.endswith((".pem", ".key", ".p12", ".pfx")) or fn in ("credentials.json", "service-account.json", "id_rsa"):
                env_files.append(rel(p, project))
    report["sensitive_files"] = env_files[:40]

    # rules
    rules_dirs = [(project / ".claude" / "rules", "project")]
    if not args.no_user:
        rules_dirs.append((USER_CLAUDE / "rules", "user"))
    for rd, scope in rules_dirs:
        if rd.exists():
            for p in sorted(rd.rglob("*.md")):
                t = read_text(p) or ""
                info = lint_instructions(p, t, project, pkg_scripts, make_targets)
                info["scope"] = scope
                fm, _ = parse_frontmatter(t)
                info["path_scoped"] = bool(fm.get("paths"))
                if fm.get("paths"):
                    pats = fm["paths"] if isinstance(fm["paths"], list) else [fm["paths"]]
                    info["paths"] = pats
                    matched = any(any(True for _ in project.glob(pp.split("{")[0])) for pp in pats if isinstance(pp, str))
                    if not matched:
                        info["flags"].append("paths glob matches no files currently in the project")
                else:
                    info["flags"].append("no `paths` frontmatter: loads every session (no context saving)")
                report["rules"].append(info)
                loaded_texts.append((info["path"], t)) if not info["path_scoped"] else None
                report["secrets"].extend(scan_secrets(t, info["path"]))

    # skills / agents / commands / output styles
    bases = [(project / ".claude", "project")]
    if not args.no_user:
        bases.append((USER_CLAUDE, "user"))
    for base, scope in bases:
        sd = base / "skills"
        if sd.exists():
            for p in sorted(sd.glob("*/SKILL.md")):
                report["skills"].append(lint_skill(p, project, scope))
            for p in sorted(sd.iterdir()):
                if p.is_dir() and p.name != "synced" and not (p / "SKILL.md").exists():
                    report["skills"].append({"name": p.name, "scope": scope, "path": rel(p, project),
                                             "flags": ["directory has no SKILL.md (not loaded)"]})
            for p in sorted(sd.glob("*.md")):
                report["skills"].append({"name": p.stem, "scope": scope, "path": rel(p, project),
                                         "flags": ["loose .md in skills/ (skills must be <name>/SKILL.md)"]})
        ad = base / "agents"
        if ad.exists():
            for p in sorted(ad.glob("*.md")):
                report["agents"].append(lint_agent(p, project, scope))
        cd = base / "commands"
        if cd.exists():
            for p in sorted(cd.rglob("*.md")):
                report["commands"].append(lint_simple_md(p, project, scope, "command"))
        od = base / "output-styles"
        if od.exists():
            for p in sorted(od.glob("*.md")):
                report["output_styles"].append(lint_simple_md(p, project, scope, "output-style"))
    names = {}
    for s in report["skills"] + report["commands"]:
        names.setdefault(s["name"], []).append(s["path"])
    report["name_collisions"] = {k: v for k, v in names.items() if len(v) > 1}

    # skills also shipped by installed plugins or synced from claude.ai (same capability loaded twice)
    provided = {}
    if not args.no_user:
        enabled = {}
        try:
            enabled = (json.loads(read_text(USER_CLAUDE / "settings.json") or "{}") or {}).get("enabledPlugins", {}) or {}
        except Exception:
            pass
        try:
            installed = (json.loads(read_text(USER_CLAUDE / "plugins" / "installed_plugins.json") or "{}") or {}).get("plugins", {})
        except Exception:
            installed = {}
        for key, entries in installed.items():
            if enabled.get(key) is False:
                continue
            for e in entries or []:
                ip = Path(e.get("installPath", ""))
                for p in ip.glob("skills/*/SKILL.md"):
                    provided.setdefault(p.parent.name, set()).add(key.split("@")[0])
        for p in (USER_CLAUDE / "skills" / "synced").glob("*/SKILL.md"):
            provided.setdefault(p.parent.name, set()).add("synced (claude.ai)")
    report["duplicated_by_plugins"] = {s["name"]: sorted(provided[s["name"]]) for s in report["skills"]
                                       if s["name"] in provided}

    # settings
    settings_files = [(project / ".claude" / "settings.json", "project"),
                      (project / ".claude" / "settings.local.json", "local")]
    if not args.no_user:
        settings_files += [(USER_CLAUDE / "settings.json", "user"), (USER_CLAUDE / "settings.local.json", "user-local")]
    for p, scope in settings_files:
        if p.exists():
            t = read_text(p) or ""
            report["secrets"].extend(scan_secrets(t, rel(p, project)))
            try:
                report["settings"].append(lint_settings(p, json.loads(t), project, scope))
            except json.JSONDecodeError as e:
                report["settings"].append({"path": rel(p, project), "scope": scope,
                                           "flags": [{"sev": "high", "msg": f"invalid JSON: {e}"}]})
    all_deny = [r for s in report["settings"] for r in s.get("deny_rules", [])]
    unprotected = []
    for ef in report["sensitive_files"]:
        name = Path(ef).name
        if not any(split_rule(d)[0] == "Read" and (fnmatch.fnmatch(ef, spec_to_glob(split_rule(d)[1]).lstrip("./")) or name in (split_rule(d)[1] or "")) for d in all_deny):
            unprotected.append(ef)
    report["sensitive_files_without_read_deny"] = unprotected

    # sensitive files: git-tracked? secret-looking keys? (names + value lengths only, never values)
    details = []
    for ef in report["sensitive_files"]:
        p = project / ef
        d = {"path": ef, "tracked": is_tracked(p, project, git_root), "secret_keys": []}
        if Path(ef).name.startswith(".env"):
            for line in (read_text(p) or "").splitlines():
                m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][\w]*)\s*=\s*(.*)$", line)
                if m and SECRET_KEY_NAME.search(m.group(1)):
                    v = m.group(2).strip().strip("'\"")
                    if v:
                        d["secret_keys"].append(f"{m.group(1)} (len {len(v)})")
        if d["tracked"]:
            d["flag"] = ("high: git-tracked file with secret-looking keys; untrack + rotate"
                         if d["secret_keys"] or not Path(ef).name.startswith(".env") else
                         "medium: git-tracked env file (no secret-looking keys found)")
        details.append(d)
    report["sensitive_files"] = details
    bare_bash = [s["path"] for s in report["settings"] if any(
        "approves every shell command" in fl.get("msg", "") for fl in s.get("flags", []))]
    if bare_bash:
        for s in report["settings"]:
            for fl in s.get("flags", []):
                if "risky command family" in fl.get("msg", ""):
                    fl["msg"] += f" (moot while unrestricted Bash is allowed in {', '.join(bare_bash)}; same root cause)"

    # .mcp.json
    mp = project / ".mcp.json"
    if mp.exists():
        t = read_text(mp) or ""
        report["secrets"].extend(scan_secrets(t, rel(mp, project)))
        try:
            report["mcp"].append(lint_mcp(mp, json.loads(t), project))
        except json.JSONDecodeError as e:
            report["mcp"].append({"path": ".mcp.json", "flags": [f"invalid JSON: {e}"]})

    # auto memory
    md = memory_dir_for(root)
    if md.exists():
        idx = md / "MEMORY.md"
        t = read_text(idx) or ""
        files = [p for p in md.glob("*.md") if p.name != "MEMORY.md"]
        linked = set(re.findall(r"\]\(([^)]+\.md)\)", t))
        report["auto_memory"] = {
            "dir": rel(md, project), "index_lines": len(t.splitlines()), "index_bytes": len(t.encode()),
            "topic_files": len(files),
            "orphans": [p.name for p in files if p.name not in linked][:30],
            "dangling_links": [l for l in linked if not (md / l).exists()][:30],
            "flags": (["MEMORY.md over 200 lines / 25KB: tail not loaded"] if len(t.splitlines()) > 200 or len(t.encode()) > 25000 else []),
        }

    # gitignore hygiene
    for name in ("CLAUDE.local.md", ".claude/settings.local.json"):
        p = project / name
        if p.exists():
            g = {"ignored": is_ignored(p, project, git_root), "tracked": is_tracked(p, project, git_root)}
            if g["tracked"]:
                g["flag"] = "medium: personal file is committed; git rm --cached + add to .gitignore"
            elif git_root and not g["ignored"]:
                g["flag"] = "low: not gitignored; will be committed by the next `git add .`"
            report["gitignore"][name] = g
    has_claude_md = any(i.get("scope") in ("project", "local", "ancestor") and i.get("nonblank_lines")
                        for i in report["claude_md_stack"])
    for a in report["agents_md"]:
        if has_claude_md and "/" not in a["path"]:
            imported = any(im["target"].endswith("AGENTS.md") for i in report["claude_md_stack"] for im in i.get("imports", []))
            a["flag"] = ("ok: imported from CLAUDE.md" if imported else
                         "AGENTS.md is ignored by Claude under the default Project-instructions setting because CLAUDE.md exists; "
                         "other agents (Codex, Cursor) still follow it, so check it for drift/contradictions")
    for name in (".claude/settings.json", ".mcp.json", "CLAUDE.md"):
        p = project / name
        if p.exists() and git_root:
            report["gitignore"][name] = {"tracked": is_tracked(p, project, git_root),
                                         "note": "should normally be committed"}

    report["duplicates"] = find_duplicates(loaded_texts)
    total = sum(i["approx_tokens"] for i in report["claude_md_stack"]) + \
        sum(r["approx_tokens"] for r in report["rules"] if not r.get("path_scoped"))
    mem = report.get("auto_memory")
    if mem:
        mem_tokens = round(min(mem["index_bytes"], 25000) / 4)
        mem["approx_tokens_loaded"] = mem_tokens
        total += mem_tokens
    report["always_loaded_approx_tokens"] = total
    report["always_loaded_note"] = "CLAUDE.md stack + unscoped rules + MEMORY.md index (chars/4); excludes imports, skill/agent listings, MCP tools"

    json.dump(report, sys.stdout, indent=1 if not args.json else None, default=str, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
