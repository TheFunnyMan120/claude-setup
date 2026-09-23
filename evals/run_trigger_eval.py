"""Live trigger eval for the claude-setup skill.

Runs each prompt in evals/trigger-prompts.md through a fresh `claude -p` session
(plan mode, so nothing is written) in an empty scratch folder, and reports
whether the claude-setup skill fired. Needs a logged-in `claude` CLI.

Usage: python run_trigger_eval.py <empty-scratch-dir>
"""
import json, re, subprocess, sys, concurrent.futures as cf, pathlib, shutil

evals = pathlib.Path.home() / ".claude/skills/claude-setup/evals/trigger-prompts.md"
cwd = sys.argv[1]
pathlib.Path(cwd).mkdir(parents=True, exist_ok=True)
txt = evals.read_text(encoding="utf-8")
pos, neg = txt.split("## Should not fire")
should = re.findall(r"^\d+\. (.+)$", pos, re.M)
shouldnt = [re.sub(r"\s+\(.*\)$", "", p).strip() for p in re.findall(r"^\d+\. (.+)$", neg, re.M)]
CLAUDE = shutil.which("claude") or shutil.which("claude.cmd")


def run(p):
    try:
        r = subprocess.run([CLAUDE, "-p", p, "--permission-mode", "plan", "--max-turns", "3",
                            "--output-format", "stream-json", "--verbose"],
                           cwd=cwd, capture_output=True, text=True, timeout=240,
                           encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
    skills = []
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        for b in ((d.get("message") or {}).get("content") or []) if isinstance((d.get("message") or {}).get("content"), list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill":
                skills.append((b.get("input") or {}).get("skill"))
    if "Failed to authenticate" in out or "Invalid API key" in out or "Please run /login" in out:
        sys.exit("claude CLI is not logged in - run `claude` once interactively (or `claude login`), then rerun this eval.")
    return p, skills, out[-300:] if not skills else ""


jobs = [(p, True) for p in should] + [(p, False) for p in shouldnt]
with cf.ThreadPoolExecutor(5) as ex:
    results = {p: (s, tail) for p, s, tail in ex.map(lambda j: run(j[0]), jobs)}
score = 0
for p, exp in jobs:
    skills, tail = results[p]
    fired = any(s and "claude-setup" in s for s in skills)
    ok = fired == exp
    score += ok
    print(("PASS" if ok else "FAIL"), "should   " if exp else "shouldnt ", "|", p, "| skills:", skills)
print(f"\n{score}/{len(jobs)} correct")
