#!/usr/bin/env node
// PreToolUse guard template. Register in .claude/settings.json:
// {"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command",
//   "command":"node \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard.js","timeout":10}]}]}}
// Exit 2 blocks the tool call and feeds stderr back to Claude. Errors fail closed (block).
let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  try {
    const input = JSON.parse(raw);
    const cmd = String(input?.tool_input?.command ?? "");
    const BLOCK = [/\bgit\s+push\b.*\b(main|master)\b/, /--force\b/]; // <- edit
    const hit = BLOCK.find((re) => re.test(cmd));
    if (hit) {
      process.stderr.write(`Blocked by project hook: command matches ${hit}. Ask the user first.`);
      process.exit(2);
    }
    process.exit(0);
  } catch (e) {
    process.stderr.write(`guard hook error, blocking to be safe: ${e.message}`);
    process.exit(2);
  }
});
