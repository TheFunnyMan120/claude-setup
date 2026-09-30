# Trigger eval prompts

Run each prompt a few times in a fresh session, in a repo with and without a setup. Check whether `/claude-setup` fires. After changing the description, rerun the whole set and compare the results.

## Should fire
1. can you set up claude code for this repo
2. review my CLAUDE.md, is it any good?
3. claude keeps ignoring the rules I gave it in this project
4. my context feels bloated, what's loading every session?
5. are my hooks and permissions safe?
6. we're moving from cursor, convert .cursorrules for claude
7. where should I put our deploy runbook so claude uses it?
8. what skills or hooks should I make for this project?
9. clean up my .claude folder
10. look across all my projects and tell me what should go in my global CLAUDE.md
11. go through my pending setup suggestions
12. turn on the thing that learns from my corrections

## Should not fire
1. fix the failing test in src/api/users.test.ts
2. review this PR for bugs
3. write a CLAUDE.md-style README for my library's users
4. make a new skill for generating release notes and run evals on it   (skill-creator)
5. allow npm commands without asking   (update-config)

Run it: `python run_trigger_eval.py <empty-scratch-dir>`. It needs a logged-in `claude` CLI and costs one short session per prompt.
