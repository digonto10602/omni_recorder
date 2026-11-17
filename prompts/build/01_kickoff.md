# 01 - Kickoff

Paste this into Claude Code started inside `~/omni_recorder/`.

---

You are the coordinator for this project. Read `CLAUDE.md` fully before doing anything. Its section 1 rules are absolute: work only inside `~/omni_recorder/`, use outside programs without modifying them, install missing system packages yourself under rule 3 and list them at the end of every result, nothing private in the public repo.

Do this:

1. Confirm the agents in `.claude/agents/` are visible (`runner`, `builder`, `repo-keeper`, `audio-engineer`, `speech-engineer`, `script-writer`, `solver`). If an agent's `model` or `effort` setting is not accepted by this Claude Code version, tell me the exact error and the closest valid setting before continuing.
2. Run stage 0 with `runner`. Install whatever is missing without asking me (rule 3) and log it in `reports/INSTALLED.md`. Show me `reports/01_audit.md` in short form. Wait for me only if something is in `reports/NEEDS_USER.md`.
3. Run stages 1 and 1b (`builder`, then `repo-keeper`). Tell me the repo URL.
4. Run stage 2 (`audio-engineer`). When the synthetic test passes, ask me to make one short real Messenger call in Chrome, then check the result.
5. Run stages 3, 4 and 5 in order. Before stage 3, ask me for a 2-3 minute sample recording with a transcript I have corrected by hand, in Bengali. Stage 3 uses it for the Bengali bake-off and the translation test in CLAUDE.md section 4a; show me the measured error rates and the three translation samples and let me pick the translator.
6. Ask me whether I want stage 6 (automatic start and stop). Then do stage 7.

Rules for you:

- Follow the routing and escalation rules in CLAUDE.md section 5. Cheapest capable agent first; two failures move a task up one tier; when Opus agents are stuck, call `solver` and have the others execute its plan.
- One stage at a time. Each stage ends with a numbered report in `reports/`, a passed acceptance check, and a commit through `repo-keeper`.
- Report to me as CLAUDE.md section 7 says: what was asked, what was done, what it means, problems and assumptions, then the "Installed on this system" list, in plain English with technical words defined.
- Stop and ask me whenever a hard rule would have to be bent.
