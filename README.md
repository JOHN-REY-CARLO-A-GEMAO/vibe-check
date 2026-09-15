# vibe-check — Reusable Agent Skill

**Protect vibe-coded projects from context drift, architectural degradation, invisible technical debt, and accidental future rework.**

> Human: "Add this quickly."  
> `/vibe-check` silently asks: "Will this quick decision create expensive problems later?"

Architectural conscience, not a coding blocker. Optimizes for **minimum future regret + maximum velocity.**

---

## Install

**Recommended — via skills (publishable via `npx skills add`):**

```bash
# Install the skill into your project (agent-agnostic)
npx skills add vibe-check
# alternatives
bunx skills add vibe-check
pnpm dlx skills add vibe-check
yarn dlx skills add vibe-check

# Initialize continuity state in your project
python vibe-check/scripts/vibe_check.py sync
```

Manual copy also works:

```bash
# Clone or copy vibe-check/ into your project root
cp -r vibe-check /your/project/vibe-check
python vibe-check/scripts/vibe_check.py sync
```

Requires Python 3.10+ (stdlib only, zero dependencies). The skill is installation-independent — it resolves its own directory via `SKILL_DIR = Path(__file__).resolve().parent.parent` so it works from `~/.agents/skills/`, `.opencode/skills/`, or any custom path.

Published via `vibe-check/` as the skill root; `.skillignore` excludes `.git`, `__pycache__`, `.vibe`, `.env`, `*.pem/*.key`, and `VALIDATION.md` so host state is never shipped.

---

## Quick Start

```bash
# Health check (fast)
python vibe-check/scripts/vibe_check.py

# Forecast the cost of a shortcut
python vibe-check/scripts/vibe_check.py forecast --request "Just hardcode the login for now."

# Debt ledger
python vibe-check/scripts/vibe_check.py debt

# Sync project state (creates .vibe/state.md + lock)
python vibe-check/scripts/vibe_check.py sync

# Deep audit
python vibe-check/scripts/vibe_check.py audit

# What changed since last sync?
python vibe-check/scripts/vibe_check.py diff

# Recover after context loss (new agent)
python vibe-check/scripts/vibe_check.py recover
```

In an AI coding agent that understands skills, just say:

```
/vibe-check
/vibe-check forecast Just hardcode the login for now.
/vibe-check debt
/vibe-check sync
/vibe-check audit
/vibe-check diff
/vibe-check recover
```

Natural language also works: *"Check the vibe"*, *"Will skipping auth cause rework?"*

---

## What It Checks (Health)

- Project structure, recent git changes, dependency drift
- Duplicated logic/symbols, oversized files (>400 lines), coupling
- Hardcoded values/URLs, TODO/FIXME accumulation, hacks
- Inconsistent patterns (multiple state libs, DBs, API styles)
- Business logic leaking into UI, scattered network/auth logic
- Config sprawl, error-handling inconsistency, missing tests
- Undocumented decisions

Output:

```
VIBE CHECK
Overall: HEALTHY / WATCH / AT RISK / CRITICAL
Velocity: ████████░░ 80%
Architecture: ███████░░░ 70%
...
```

---

## Forecast (Most Important)

Analyzes a **requested change together with current architecture**.

```
FORECAST
Requested: Just hardcode the login for now.
Immediate benefit: Saves 2–4 hours
Detected risk: Auth logic touches every layer
Likely future rework: 1–3 days later
Estimated migration surface: 6–15+ files
Regret score: 72/100 — HIGH
Recommendation: You can do this, but isolate behind one boundary file.
Fastest safe alternative: Hardcode behind an interface.
```

**Regret Score:** 0–20 negligible, 21–40 low, 41–60 moderate, 61–80 high, 81–100 severe.

The skill **never blocks**; it says "You can do this. Here's the cost."

---

## Files Created

`.vibe/state.md` — continuity layer (<5KB), decisions, constraints, conventions  
`.vibe/state.json` — machine-readable mirror  
`.vibe/state.lock` — SHA-256 integrity hash  
`.vibe/debt.md` — human-readable ledger (OPEN/MONITORING/RESOLVED/ACCEPTED)  
`.vibe/decisions.md` — architectural decision records

All are plain Markdown/JSON, git-friendly, secrets-filtered.

---

## Debt Prioritization

`Priority = Impact × Likelihood × Migration Cost`

- **P0** dangerous (e.g., hardcoded payment, secrets)
- **P1** high impact
- **P2** worth fixing
- **P3** monitor

Shows top 3–5, not everything.

---

## Philosophy

- **No astronautics:** No microservices for MVPs, no event buses without need.
- **Simplest safe architecture** for the project's *expected next stage*.
- **DO NOW / DO LATER / DON'T DO** recommendations.
- **Human in control** always.

---

## Security

Never persists API keys, passwords, tokens, `.env` values. Sanitizes with `[REDACTED]` before writing state.

---

## Dogfooding

This skill passes its own checks:

```bash
python vibe-check/scripts/vibe_check.py
python vibe-check/scripts/vibe_check.py audit
python vibe-check/scripts/vibe_check.py sync
python -m pytest vibe-check/tests -v
```

---

## Structure

```
vibe-check/
├── SKILL.md
├── README.md
├── scripts/
│   ├── vibe_check.py   # CLI
│   ├── integrity.py    # SHA-256 lock
│   └── utils.py        # scanner + sanitizer
├── templates/
│   ├── state.md
│   ├── debt.md
│   └── decisions.md
├── examples/
│   ├── example-state.md
│   ├── example-debt.md
│   └── example-decisions.md
└── tests/
    ├── test_state.py
    ├── test_debt.py
    ├── test_forecast.py
    ├── test_drift.py
    ├── test_recovery.py
    └── test_security.py
```

---

## License

MIT — use in any vibe-coded project.
