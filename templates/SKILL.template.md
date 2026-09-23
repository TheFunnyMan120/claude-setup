---
name: <kebab-case-name>
description: <Verb>s <objects> <distinctive capability>. Use when <literal trigger 1 - the words people type, file names, commands>, <trigger 2>, or the user says "<common phrasing>". Also use for <adjacent case>. Not for <X> (use <other skill>).
# disable-model-invocation: true   # uncomment for side-effecting skills (deploy, send, delete)
---
<!-- Description rules: key use case first; literal vocabulary; assertive but conditional
     ("Use when..."); no CRITICAL/MUST/"if in doubt" (current models overtrigger on those);
     name what it is NOT for. If this skill must always fire, also add a one-line pointer in
     CLAUDE.md: "For <task>, use the /<name> skill." -->

# <Title>

**Goal:** <what good looks like when this is done>
**Done when:** <observable finish line>

## Non-negotiables
<!-- Only the few steps that must never be skipped (safety, approval, verification). Delete if none. -->
1. <e.g. Run the typecheck before committing>

## Approach
<!-- Goals and constraints, not a script. Exact steps only where order or fragility matters,
     and put those in scripts/. Leave out anything Claude does by default. -->
- <Constraint or decision rule specific to this task>
- Deterministic part: `python "${CLAUDE_SKILL_DIR}/scripts/<x>.py"`

## Gotchas
<!-- The highest-value section. Add one line every time the skill fails in real use. -->
- <Thing that looks like X but is Y>

## References
- [reference.md](reference.md): read when <condition>
