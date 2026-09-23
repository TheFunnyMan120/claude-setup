<!-- Template for init mode. Delete any section with nothing project-specific to say.
     Target 30-80 lines. Every line must pass: "would removing this cause Claude to make a mistake?"
     HTML comments like this one are stripped before Claude sees the file. -->
# <Project name>
<One or two lines: what this is, the stack, and where it runs.>

## Commands
- `<build cmd>`: <note if non-obvious>
- `<test cmd> <single-file form>`: run one test; <full-suite caveat>
- `<lint/typecheck cmd>`
- `<codegen/migration cmd>`: when to run it

## Gotchas
- <Thing that looks like X but is Y>
- <Generated or vendored paths: edit <source> instead>
- <Env/service prerequisite: names only, never values>

## Conventions
<!-- Only where they differ from language or framework defaults or the linter config -->
- <Error handling / logging / naming rule with a concrete example>
- <Branch / commit / PR convention>

## Deeper docs (read when relevant)
- <Area>: <path/to/doc.md>
