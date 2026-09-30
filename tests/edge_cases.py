"""Edge cases for the scripts: odd settings shapes, encodings, malformed transcripts, corrupt
state, install into unusual settings, races, CLAUDE_CONFIG_DIR, cloud Stop. Every scenario runs
against a throwaway HOME, so nothing touches your real ~/.claude, and no model is called.

  python tests/edge_cases.py                 # all
  python tests/edge_cases.py . install race  # only tests whose name contains a word
  python tests/edge_cases.py <other checkout> # e.g. compare against a released copy
"""
import json, os, shutil, subprocess, sys, tempfile, time, traceback
from pathlib import Path

REPO = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
PY = sys.executable
RESULTS = []


def sandbox(name):
    root = Path(tempfile.mkdtemp(prefix=f"cs-{name}-"))
    home = root / "home"
    (home / ".claude").mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8")
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.pop("CLAUDE_CODE_REMOTE", None)
    return root, home, env


def run(script, args, env, cwd=None, stdin=None, timeout=60):
    r = subprocess.run([PY, str(SCRIPTS / script), *args], env=env, cwd=cwd, input=stdin,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True)


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  -- {detail}" if detail and not ok else ""), flush=True)


def check(name, fn):
    try:
        res = fn()
        if res is True or res is None:
            record(name, True)
        else:
            record(name, False, str(res)[:600])
    except Exception as e:
        record(name, False, f"harness exception: {type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}")


def ok_json(r):
    if r.returncode != 0 or "Traceback" in r.stderr:
        return f"rc={r.returncode} stderr={r.stderr[-500:]}"
    try:
        return json.loads(r.stdout)
    except ValueError:
        return f"not JSON: {r.stdout[:300]}"


def inv(project, env, *extra):
    return ok_json(run("inventory.py", ["--project", str(project), *extra], env))


# ------------------------------------------------------------------ inventory

def t_inv_basic_shapes():
    root, home, env = sandbox("inv")
    fails = []
    cases = {}
    p = root / "empty"; p.mkdir(); cases["empty non-git dir"] = p
    p = root / "gitnocommit"; p.mkdir(); git(p, "init", "-q"); cases["git repo, no commits"] = p
    p = root / "Proj é 项目 with spaces"; p.mkdir(); (p / "CLAUDE.md").write_text("# é 项目\n- use `npm test`\n", encoding="utf-8"); cases["unicode+spaces path"] = p
    for name, p in cases.items():
        out = inv(p, env)
        if not isinstance(out, dict):
            fails.append(f"{name}: {out}")
    out = run("inventory.py", ["--project", str(root / "does-not-exist")], env)
    if "Traceback" in out.stderr:
        fails.append(f"nonexistent project: traceback {out.stderr[-300:]}")
    return fails or True


def t_inv_settings_variants():
    root, home, env = sandbox("invset")
    variants = {
        "BOM": "\ufeff" + json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}),
        "invalid json": '{"permissions": {"allow": ["Bash(ls:*)",]}',
        "empty file": "",
        "json array": "[]",
        "json null": "null",
        "hooks as list": json.dumps({"hooks": [{"command": "x"}]}),
        "hook event dict": json.dumps({"hooks": {"Stop": {"hooks": [{"type": "command", "command": "x"}]}}}),
        "group without hooks": json.dumps({"hooks": {"Stop": [{"matcher": ""}]}}),
        "hook entry string": json.dumps({"hooks": {"Stop": [{"hooks": ["echo hi"]}]}}),
        "hook command null": json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": None}]}]}}),
        "allow as string": json.dumps({"permissions": {"allow": "Bash(*)"}}),
        "permissions list": json.dumps({"permissions": ["Bash(*)"]}),
        "enabledPlugins list": json.dumps({"enabledPlugins": ["a@b"]}),
        "env non-dict": json.dumps({"env": "FOO=1"}),
        "utf16": None,
    }
    fails = []
    for name, text in variants.items():
        p = root / name.replace(" ", "_"); (p / ".claude").mkdir(parents=True)
        f = p / ".claude" / "settings.json"
        if text is None:
            f.write_bytes(json.dumps({"permissions": {"allow": ["Bash(*)"]}}).encode("utf-16"))
        else:
            f.write_text(text, encoding="utf-8")
        out = inv(p, env, "--no-user")
        if not isinstance(out, dict):
            fails.append(f"{name}: {out}")
        elif name == "BOM":
            s = [x for x in out["settings"] if x["path"].endswith("settings.json")]
            if not s or not s[0].get("allow_rules"):
                fails.append(f"BOM settings not parsed: {s}")
    return fails or True


def t_inv_claude_md_variants():
    root, home, env = sandbox("invmd")
    fails = []
    p = root / "enc"; p.mkdir()
    (p / "CLAUDE.md").write_bytes("# Caf\xe9 rules\n- r\xe8gle\n".encode("cp1252"))
    (p / "AGENTS.md").write_bytes("# agents\n".encode("utf-16"))
    out = inv(p, env, "--no-user")
    if not isinstance(out, dict): fails.append(f"cp1252/utf16: {out}")
    p = root / "imports"; p.mkdir()
    (p / "CLAUDE.md").write_text("@a.md\n@missing.md\n@/abs/nowhere.md\n@~/nothing.md\n@../../../../etc/passwd\n", encoding="utf-8")
    (p / "a.md").write_text("@b.md\n", encoding="utf-8"); (p / "b.md").write_text("@a.md\n@CLAUDE.md\n", encoding="utf-8")
    out = run("inventory.py", ["--project", str(p), "--no-user"], env, timeout=30)
    if out.returncode != 0 or "Traceback" in out.stderr: fails.append(f"import loop: {out.stderr[-300:]}")
    p = root / "dotclaude_is_file"; p.mkdir(); (p / ".claude").write_text("oops", encoding="utf-8")
    out = inv(p, env, "--no-user")
    if not isinstance(out, dict): fails.append(f".claude is a file: {out}")
    p = root / "huge"; p.mkdir(); (p / "CLAUDE.md").write_text("- line\n" * 20000, encoding="utf-8")
    t0 = time.time(); out = inv(p, env, "--no-user")
    if not isinstance(out, dict): fails.append(f"huge: {out}")
    elif time.time() - t0 > 20: fails.append(f"huge CLAUDE.md slow: {time.time()-t0:.1f}s")
    return fails or True


def t_inv_extension_variants():
    root, home, env = sandbox("invext")
    p = root / "ext"; sk = p / ".claude" / "skills"; sk.mkdir(parents=True)
    (sk / "nofm").mkdir(); (sk / "nofm" / "SKILL.md").write_text("no frontmatter here\n", encoding="utf-8")
    (sk / "badyaml").mkdir(); (sk / "badyaml" / "SKILL.md").write_text("---\nname: [unclosed\ndescription: :::\n---\nbody\n", encoding="utf-8")
    (sk / "binary").mkdir(); (sk / "binary" / "SKILL.md").write_bytes(b"\x00\xff\xfe\x00garbage")
    (sk / "emptyfm").mkdir(); (sk / "emptyfm" / "SKILL.md").write_text("---\n---\n", encoding="utf-8")
    (sk / "multiline").mkdir(); (sk / "multiline" / "SKILL.md").write_text("---\nname: multiline\ndescription: >\n  folded\n  text\n---\nx\n", encoding="utf-8")
    ag = p / ".claude" / "agents"; ag.mkdir()
    (ag / "weird.md").write_text("---\ntools: [Read, Grep]\nmodel: 5\n---\n", encoding="utf-8")
    (p / ".mcp.json").write_text('{"mcpServers": ["not", "a", "dict"]}', encoding="utf-8")
    out = inv(p, env, "--no-user")
    if not isinstance(out, dict): return out
    (p / ".mcp.json").write_text('{"mcpServers": {"x": "string-not-dict", "y": {"command": 5, "args": "notalist"}}}', encoding="utf-8")
    out = inv(p, env, "--no-user")
    if not isinstance(out, dict): return f"mcp odd servers: {out}"
    (p / ".mcp.json").write_text('not json', encoding="utf-8")
    out = inv(p, env, "--no-user")
    if not isinstance(out, dict): return f"mcp invalid: {out}"
    return True


def t_inv_no_user_claude():
    root, home, env = sandbox("invnohome")
    shutil.rmtree(home / ".claude")
    p = root / "proj"; p.mkdir()
    out = inv(p, env)
    return True if isinstance(out, dict) else out


def t_inv_worktree():
    root, home, env = sandbox("invwt")
    p = root / "main"; p.mkdir(); git(p, "init", "-q"); (p / "f").write_text("x"); git(p, "add", "."); git(p, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "x")
    git(p, "worktree", "add", "-q", str(root / "wt"))
    out = inv(root / "wt", env, "--no-user")
    return True if isinstance(out, dict) else out


def t_config_dir():
    """CLAUDE_CONFIG_DIR relocates ~/.claude; the scripts should follow it."""
    root, home, env = sandbox("cfgdir")
    cfg = root / "altconfig"; cfg.mkdir()
    (cfg / "CLAUDE.md").write_text("- alt config rule\n", encoding="utf-8")
    env = dict(env, CLAUDE_CONFIG_DIR=str(cfg))
    p = root / "proj"; p.mkdir()
    out = inv(p, env)
    if not isinstance(out, dict): return out
    paths = [i["path"] for i in out["claude_md_stack"]]
    fails = []
    if not any("alt" in json.dumps(i) or str(cfg) in i["path"] or "CLAUDE.md" in i["path"] and i.get("scope") == "user" for i in out["claude_md_stack"]):
        fails.append(f"inventory ignored CLAUDE_CONFIG_DIR: stack={paths}")
    r = run("learn.py", ["install", "--scope", "user"], env)
    if not (cfg / "settings.json").exists():
        fails.append(f"learn install wrote to {'~/.claude' if (home/'.claude'/'settings.json').exists() else '?'} instead of CLAUDE_CONFIG_DIR")
    return fails or True


# ------------------------------------------------------------------ sessions

def enc(p):
    import re
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(p).resolve()))


def write_transcript(home, project, sid, lines, dirname=None):
    d = home / ".claude" / "projects" / (dirname or enc(project))
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    with open(f, "wb") as fh:
        for l in lines:
            fh.write(l if isinstance(l, bytes) else (json.dumps(l) + "\n").encode("utf-8"))
    return f


def urec(text, project, uid=None):
    return {"type": "user", "uuid": uid or os.urandom(8).hex(), "cwd": str(project), "timestamp": "2026-09-30T10:00:00Z",
            "message": {"role": "user", "content": text}}


def t_sessions_malformed():
    root, home, env = sandbox("sess")
    p = root / "proj"; p.mkdir()
    lines = [b"\n", b"not json\n", b"[1,2,3]\n", b'"just a string"\n', b"null\n", b"42\n",
             b'{"type": "user", "message": "not a dict"}\n',
             b'{"type": "user", "message": {"content": {"weird": "dict"}}}\n',
             b'{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": "string input"}]}}\n',
             b'{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": 5}}]}}\n',
             b'{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": null, "content": 5, "is_error": true}]}}\n',
             "{\"type\": \"user\", \"message\": {\"content\": \"no, don't do that caf\xe9\"}}\n".encode("cp1252"),
             urec("don't use npm, use pnpm instead", p),
             b'{"type": "user", "message": {"content": "truncated last line with no newl']
    write_transcript(home, p, "s1", lines)
    out = ok_json(run("sessions.py", ["--project", str(p)], env))
    return True if isinstance(out, dict) else out


def t_sessions_prefix_collision():
    root, home, env = sandbox("prefix")
    a = root / "app"; a.mkdir(); b = root / "app2"; b.mkdir(); c = root / "app-old"; c.mkdir()
    write_transcript(home, a, "sa", [urec("don't touch A", a)])
    write_transcript(home, b, "sb", [urec("don't touch B", b)])
    write_transcript(home, c, "sc", [urec("don't touch C", c)])
    wt = a / ".claude" / "worktrees" / "feat"; wt.mkdir(parents=True)
    write_transcript(home, wt, "swt", [urec("don't touch WT", wt)])
    out = ok_json(run("sessions.py", ["--project", str(a)], env))
    if not isinstance(out, dict): return out
    if out["sessions"] != 2:
        return f"expected 2 sessions (app + its worktree), got {out['sessions']}: {out.get('corrections_sample')}"
    return True


def t_sessions_list_projects_odd():
    root, home, env = sandbox("listp")
    pr = home / ".claude" / "projects"; pr.mkdir(parents=True)
    (pr / "a-file-not-dir").write_text("x")
    (pr / "empty-dir").mkdir()
    (pr / "dir-with-garbage").mkdir(); (pr / "dir-with-garbage" / "x.jsonl").write_bytes(b"\xff\xfe garbage\n")
    out = ok_json(run("sessions.py", ["--list-projects"], env))
    return True if isinstance(out, dict) else out


def t_sessions_unicode_project():
    root, home, env = sandbox("sessuni")
    p = root / "José Pérez 项目"; p.mkdir()
    # Claude's real folder naming for non-ASCII is unknown: store under a name that differs from our encoding
    write_transcript(home, p, "su", [urec("never commit to main", p)], dirname=enc(p).replace("-", "_", 1) + "x")
    out = ok_json(run("sessions.py", ["--project", str(p)], env))
    if not isinstance(out, dict): return out
    return True if out.get("sessions") == 1 else f"transcript not found when folder name differs from our encoding (sessions={out.get('sessions')})"


# ------------------------------------------------------------------ learn: install

def t_learn_install_matrix():
    fails = []
    base = {"model": "opus", "statusLine": {"type": "command", "command": "echo é"},
            "hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "node other.js"}]}]}}
    variants = {"missing": None, "empty": "", "BOM": "\ufeff" + json.dumps(base), "normal": json.dumps(base),
                "hooks list": json.dumps({"hooks": []}), "hooks string": json.dumps({"hooks": "x"}),
                "event dict": json.dumps({"hooks": {"Stop": {"hooks": []}}}),
                "group no hooks": json.dumps({"hooks": {"SessionStart": [{"matcher": "x"}]}}),
                "entry string": json.dumps({"hooks": {"SessionStart": [{"hooks": ["echo"]}]}}),
                "invalid": "{nope"}
    for name, text in variants.items():
        root, home, env = sandbox("inst")
        s = home / ".claude" / "settings.json"
        if text is not None:
            s.write_text(text, encoding="utf-8")
        r = run("learn.py", ["install", "--scope", "user"], env)
        after = s.read_text(encoding="utf-8-sig") if s.exists() else ""
        installed = "claude-setup-learn.py" in after
        if name in ("invalid", "hooks list", "hooks string"):
            if installed or r.returncode == 0 or "not touching" not in r.stderr:
                fails.append(f"{name}: should refuse with nonzero exit (rc={r.returncode})")
            continue
        if not installed:
            fails.append(f"{name}: not installed (rc={r.returncode}, out={r.stdout[:150]} err={r.stderr[:200]})")
            continue
        if name in ("normal", "BOM"):
            d = json.loads(after)
            if d.get("model") != "opus" or d["statusLine"]["command"] != "echo é":
                fails.append(f"{name}: other keys changed")
            if not any("other.js" in h.get("command", "") for g in d["hooks"]["Stop"] for h in g["hooks"]):
                fails.append(f"{name}: existing hook lost")
            if "\\u00e9" in after:
                fails.append(f"{name}: non-ASCII rewritten as \\u escapes")
        # idempotent reinstall + options kept
        run("learn.py", ["install", "--scope", "user", "--daily-cap", "3"], env)
        run("learn.py", ["install", "--scope", "user"], env)
        d = json.loads(s.read_text(encoding="utf-8-sig"))
        cmds = [h.get("command", "") for gs in d["hooks"].values() if isinstance(gs, list) for g in gs if isinstance(g, dict) for h in g.get("hooks", []) if isinstance(h, dict)]
        ours = [c for c in cmds if "claude-setup-learn" in c]
        if len(ours) != 2 or not all("--daily-cap 3" in c for c in ours):
            fails.append(f"{name}: reinstall not idempotent or lost options: {ours}")
        r = run("learn.py", ["uninstall", "--scope", "user"], env)
        after = s.read_text(encoding="utf-8-sig")
        if "claude-setup-learn" in after or (home / ".claude" / "hooks" / "claude-setup-learn.py").exists():
            fails.append(f"{name}: uninstall left traces")
        if name == "normal" and "other.js" not in after:
            fails.append("uninstall removed someone else's hook")
    return fails or True


def t_learn_install_symlinked_settings():
    root, home, env = sandbox("symlink")
    dot = root / "dotfiles"; dot.mkdir()
    real = dot / "settings.json"; real.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
    link = home / ".claude" / "settings.json"
    try:
        os.symlink(real, link)
    except OSError as e:
        print("   (skipped: no symlink permission)")
        return True  # can't create symlinks here (Windows without dev mode); covered on Linux
    run("learn.py", ["install", "--scope", "user"], env)
    if not link.is_symlink():
        return "install replaced the symlinked settings.json with a regular file (breaks dotfile managers)"
    return True if "claude-setup-learn" in real.read_text() else "symlink target not updated"


def t_learn_install_errors_visible():
    root, home, env = sandbox("insterr")
    (home / ".claude" / "settings.json").mkdir()  # a directory where the file should be
    r = run("learn.py", ["install", "--scope", "user"], env)
    if r.returncode == 0:
        return f"install failed silently (rc=0, stdout={r.stdout[:120]!r}, stderr={r.stderr[:120]!r})"
    return True


def t_learn_resolve_missing():
    root, home, env = sandbox("resolve")
    p = root / "proj"; p.mkdir()
    r = run("learn.py", ["resolve", "deadbeef", "--status", "applied", "--cwd", str(p)], env)
    return True if r.returncode != 0 else "resolve of unknown id exited 0"


# ------------------------------------------------------------------ learn: state file

def load_learn(env_home):
    import importlib.util
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(env_home)
    spec = importlib.util.spec_from_file_location("learn_mod_%d" % time.time_ns(), SCRIPTS / "learn.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def prop(**kw):
    base = {"kind": "add", "scope": "project", "destination": "claude_md", "file": "CLAUDE.md", "current": "",
            "proposed": "Use pnpm, not npm.", "strength": "strong", "durable": True, "evidence": "user said so",
            "why": "explicit", "same_as": ""}
    base.update(kw)
    return base


def t_learn_state_roundtrip():
    root, home, env = sandbox("state")
    p = root / "proj"; p.mkdir(); git(p, "init", "-q")
    saved = dict(os.environ)
    try:
        m = load_learn(home)
        items = []
        tricky = ["Diagrams use A --> B arrows (mermaid).", "Close HTML comments with --> never <!--",
                  "Paths like C:\\Users\\x and `code` and **bold**", "Emoji 🚀 and 项目 and é",
                  "Line one\nline two", "Ends with backslash \\", '"quoted" and \'single\'', "<!-- claude-setup:state"]
        for t in tricky:
            m.merge(items, [prop(proposed=t)], "s1", p)
        m.save_items(p, items)
        back, repaired = m.load_state(p)
        if len(back) != len(tricky):
            return f"state roundtrip lost items: wrote {len(tricky)}, read {len(back)} (repaired={repaired})"
        if sorted(i["proposed"] for i in back) != sorted(i["proposed"] for i in items):
            return "state roundtrip changed item text"
        return True
    finally:
        os.environ.clear(); os.environ.update(saved)


def t_learn_state_corrupt():
    root, home, env = sandbox("corrupt")
    p = root / "proj"; (p / ".claude").mkdir(parents=True)
    f = p / ".claude" / "setup-suggestions.md"
    fails = []
    for name, text in {"no state block": "# hand edited\n", "broken json": "<!-- claude-setup:state\n{nope\n-->\n",
                       "items not list": '<!-- claude-setup:state\n{"items": "x"}\n-->\n',
                       "item missing keys": '<!-- claude-setup:state\n{"items": [{"id": "a"}]}\n-->\n',
                       "item wrong types": '<!-- claude-setup:state\n{"items": [{"id": 1, "status": 5, "strength": null, "count": "x", "scope": [], "kind": "add", "destination": "claude_md", "sessions": "s", "evidence": 3, "last_seen": 0, "first_seen": 0}]}\n-->\n',
                       "one-sided conflict": "<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> b\n",
                       "binary": None}.items():
        if text is None:
            f.write_bytes(b"\xff\xfe\x00\x01")
        else:
            f.write_text(text, encoding="utf-8")
        for cmd in (["session-start"], ["status", "--cwd", str(p)], ["reconcile", "--cwd", str(p)]):
            stdin = json.dumps({"cwd": str(p)}) if cmd[0] == "session-start" else None
            r = run("learn.py", cmd, env, cwd=str(p), stdin=stdin)
            if "Traceback" in r.stderr:
                fails.append(f"{name}/{cmd[0]}: traceback {r.stderr[-200:]}")
            if cmd[0] == "status" and r.returncode == 0:
                try:
                    json.loads(r.stdout)
                except ValueError:
                    fails.append(f"{name}/status: no JSON output ({r.stdout[:100]!r})")
        log = home / ".claude" / "claude-setup" / "learn.log"
        if log.exists() and "error:" in log.read_text(encoding="utf-8"):
            fails.append(f"{name}: logged error: " + [l for l in log.read_text(encoding='utf-8').splitlines() if 'error:' in l][-1][-160:])
            log.unlink()
    return fails or True


def t_learn_prefilter_malformed():
    root, home, env = sandbox("prefil")
    p = root / "proj"; p.mkdir()
    lines = [b"[1]\n", b'"s"\n', b"null\n", b'{"type": "user", "message": "str"}\n',
             b'{"type": "user", "message": {"content": [{"type": "tool_result", "content": 5, "is_error": true}]}}\n',
             b'{"type": "assistant", "message": {"content": [{"type": "tool_use", "input": "notdict"}]}}\n',
             "{\"type\": \"user\", \"message\": {\"content\": \"no, don't caf\xe9\"}}\n".encode("cp1252"),
             (json.dumps(urec("from now on always use tabs", p)) + "\n").encode()]
    f = write_transcript(home, p, "pf", lines)
    r = run("learn.py", ["prefilter", "--transcript", str(f)], env)
    if r.returncode != 0 or "Traceback" in r.stderr:
        return f"rc={r.returncode} {r.stderr[-300:]}"
    log = home / ".claude" / "claude-setup" / "learn.log"
    if log.exists() and "error" in log.read_text(encoding="utf-8"):
        return "logged: " + log.read_text(encoding="utf-8")[-300:]
    if "tabs" not in r.stdout:
        return f"good signal lost next to malformed lines: {r.stdout[:300]}"
    return True


def t_learn_session_end_inputs():
    root, home, env = sandbox("sein")
    fails = []
    for name, payload in {"empty": "", "not json": "nope", "list": "[]", "no path": "{}",
                          "path number": '{"transcript_path": 5}', "missing file": json.dumps({"transcript_path": str(root / "nope.jsonl")}),
                          "dir traversal": json.dumps({"transcript_path": "../../x.jsonl"})}.items():
        r = run("learn.py", ["session-end"], env, stdin=payload)
        if r.returncode != 0 or "Traceback" in r.stderr:
            fails.append(f"{name}: rc={r.returncode} {r.stderr[-150:]}")
    return fails or True


def t_learn_home_project():
    """Claude run in the home folder: the project IS ~, and ~/.claude/CLAUDE.md is both global and project."""
    root, home, env = sandbox("homeproj")
    (home / ".claude" / "CLAUDE.md").write_text("- global rule\n", encoding="utf-8")
    saved = dict(os.environ)
    try:
        m = load_learn(home)
        ctx = m.setup_context(home)
        if ctx.count("global rule") > 1:
            return "home-as-project: global CLAUDE.md sent to the model twice"
        return True
    finally:
        os.environ.clear(); os.environ.update(saved)


def t_learn_state_race():
    """Two projects finishing at once both rewrite learn-state.json; neither offset should be lost."""
    root, home, env = sandbox("race")
    saved = dict(os.environ)
    try:
        m = load_learn(home)
        pa, pb = root / "a", root / "b"
        for pp in (pa, pb):
            pp.mkdir()
        fa = write_transcript(home, pa, "ta", [urec("hello there", pa)] * 3)
        fb = write_transcript(home, pb, "tb", [urec("hello there", pb)] * 3)
        import threading
        orig = m.prefilter
        def slow_prefilter(*a, **k):
            r = orig(*a, **k); time.sleep(0.5); return r
        m.prefilter = slow_prefilter
        class A: pass
        def go(t, c):
            a = A(); a.cwd, a.transcript, a.session, a.daily_cap, a.budget, a.expire_days = str(c), str(t), "", 10, 0.25, 30
            m.cmd_analyze(a)
        th = [threading.Thread(target=go, args=(fa, pa)), threading.Thread(target=go, args=(fb, pb))]
        [t.start() for t in th]; [t.join() for t in th]
        st = json.loads((home / ".claude" / "claude-setup" / "learn-state.json").read_text())
        if len(st["offsets"]) != 2:
            return f"lost update in learn-state.json: offsets for {len(st['offsets'])} of 2 transcripts"
        return True
    finally:
        os.environ.clear(); os.environ.update(saved)


def t_learn_venv_python():
    root, home, env = sandbox("venv")
    v = root / "venv"
    subprocess.run([PY, "-m", "venv", "--without-pip", str(v)], capture_output=True)
    vpy = v / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not vpy.exists():
        return True
    subprocess.run([str(vpy), str(SCRIPTS / "learn.py"), "install", "--scope", "user"], env=env, capture_output=True)
    s = (home / ".claude" / "settings.json").read_text(encoding="utf-8")
    if str(v) in s or str(v).replace("\\", "\\\\") in s:
        return "hook command points at a virtualenv's python (breaks when the venv is deleted)"
    return True


def t_inv_hook_paths_with_spaces():
    root, home, env = sandbox("hookspace")
    fails = []
    spaced = root / "John Smith" / ".claude" / "hooks"; spaced.mkdir(parents=True)
    (spaced / "h.py").write_text("print(1)\n")
    gone_py = root / "Python399" / ("python.exe" if os.name == "nt" else "python3")
    cmds = {"spaced": f'"{PY}" "{spaced / "h.py"}" x', "missing interp": f'"{gone_py}" "{spaced / "h.py"}" x'}
    p = root / "proj"; (p / ".claude").mkdir(parents=True)
    (p / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": c} for c in cmds.values()]}]}}), encoding="utf-8")
    out = inv(p, env, "--no-user")
    if not isinstance(out, dict): return out
    hooks = [h for s in out["settings"] for h in s.get("hooks", [])]
    if any("not found" in " ".join(h["issues"]) and "interpreter" not in " ".join(h["issues"]) for h in hooks[:1]):
        fails.append(f"false 'hook script not found' for a path with a space: {hooks[0]['issues']}")
    if not any("interpreter not found" in " ".join(h["issues"]) for h in hooks[1:]):
        fails.append(f"missing interpreter not flagged: {hooks[1:]}")
    return fails or True


def t_learn_hook_via_bash_unicode_home():
    """Claude Code runs hook commands through Git Bash on Windows (sh elsewhere)."""
    root, home, env = sandbox("bashuni")
    uhome = root / "José Pérez"; (uhome / ".claude").mkdir(parents=True)
    env = dict(env, HOME=str(uhome), USERPROFILE=str(uhome))
    r = run("learn.py", ["install", "--scope", "user"], env)
    if r.returncode != 0: return f"install failed: {r.stderr}"
    s = json.loads((uhome / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmd = s["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    p = root / "proj"; p.mkdir()
    sh = shutil.which("bash") or "sh"
    r = subprocess.run([sh, "-c", cmd], input=json.dumps({"cwd": str(p)}), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0 or "Traceback" in r.stderr:
        return f"hook command failed through {sh}: rc={r.returncode} {r.stderr[-300:]}\ncmd={cmd}"
    return True


def t_learn_log_rotation():
    root, home, env = sandbox("logrot")
    sd = home / ".claude" / "claude-setup"; sd.mkdir(parents=True)
    (sd / "learn.log").write_text("x" * 1_100_000)
    run("learn.py", ["session-end"], env, stdin="{}")
    if not (sd / "learn.log.1").exists() or (sd / "learn.log").stat().st_size > 10_000:
        return "learn.log not rotated past 1 MB"
    return True


def t_learn_cloud_stop():
    root, home, env = sandbox("cloud")
    import hashlib
    env = dict(env, CLAUDE_CODE_REMOTE="true", CLAUDE_CODE_ACCOUNT_UUID="acct-1")
    tag = hashlib.sha256(b"acct-1").hexdigest()[:16]
    p = root / "repo"; p.mkdir(); git(p, "init", "-q")
    t = write_transcript(home, p, "c1", [urec("hello", p)])
    payload = json.dumps({"transcript_path": str(t), "cwd": str(p), "session_id": "c1"})
    fails = []
    r = run("learn.py", ["stop", "--only-account", "someone-else"], env, stdin=payload)
    if r.returncode != 0: fails.append(f"other account: rc={r.returncode}")
    r = run("learn.py", ["stop", "--only-account", tag], env, stdin=payload)
    if r.returncode != 0 or "Traceback" in r.stderr: fails.append(f"no-signal stop: rc={r.returncode} {r.stderr[-200:]}")
    # two branches both edited the file: conflict markers; stop should merge them and ask for a commit
    saved = dict(os.environ)
    try:
        m = load_learn(home)
        a_items, b_items = [], []
        m.merge(a_items, [prop(proposed="Rule A")], "s1", p); m.merge(b_items, [prop(proposed="Rule B")], "s2", p)
        m.save_items(p, a_items); A = (p / ".claude" / "setup-suggestions.md").read_text(encoding="utf-8")
        m.save_items(p, b_items); B = (p / ".claude" / "setup-suggestions.md").read_text(encoding="utf-8")
    finally:
        os.environ.clear(); os.environ.update(saved)
    (p / ".claude" / "setup-suggestions.md").write_text(f"<<<<<<< HEAD\n{A}=======\n{B}>>>>>>> other\n", encoding="utf-8")
    (p / ".git" / "info" / "exclude").write_text("")  # built in local mode above; a cloud clone has no exclude
    git(p, "add", "."); git(p, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "c")
    (p / ".claude" / "setup-suggestions.md").write_text(f"<<<<<<< HEAD\n{A}=======\n{B}>>>>>>> other\n", encoding="utf-8")
    r = run("learn.py", ["stop", "--only-account", tag], env, stdin=payload)
    txt = (p / ".claude" / "setup-suggestions.md").read_text(encoding="utf-8")
    if "<<<<<<<" in txt or "Rule A" not in txt or "Rule B" not in txt:
        fails.append("conflict not merged to a clean file with both items")
    if r.returncode != 2 or "Commit it" not in r.stderr:
        fails.append(f"expected exit 2 asking to commit, got rc={r.returncode} {r.stderr[:120]!r}")
    return fails or True


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("t_")]

if __name__ == "__main__":
    only = sys.argv[2:] if len(sys.argv) > 2 else None
    for t in TESTS:
        if only and not any(o in t.__name__ for o in only):
            continue
        check(t.__name__, t)
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed")
    for n, _, d in bad:
        print(f"\n--- {n}\n{d}")
    sys.exit(1 if bad else 0)
