#!/usr/bin/env python3
# vibe-check: allow-large-file - entrypoint is intentionally single-file for portability (see decisions.md)
"""
Vibe Check - Architectural Conscience for Vibe-Coded Projects
CLI entrypoint for /vibe-check skill
Supports: health, forecast, debt, sync, audit, diff, recover
"""
import re
import sys
import json
import argparse
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Tuple

# Python version check — produce clear error if unavailable
if sys.version_info < (3, 10):
    print("Python >=3.10 is required for vibe-check. Install Python or run via host agent's python.", file=sys.stderr)
    sys.exit(1)

# Installation-independent skill directory — works from ~/.agents/skills/, .opencode/skills/, etc.
try:
    SKILL_DIR = Path(__file__).resolve().parent.parent
except:
    SKILL_DIR = Path.cwd() / "vibe-check"

# Allow running as script or module
try:
    from utils import scan_repo, render_bar, sanitize_for_state, sanitize_output, ensure_vibe_dir, find_project_root, load_config, is_skill_file, detect_drift_details
    from integrity import write_lock, verify_lock, hash_file
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from utils import scan_repo, render_bar, sanitize_for_state, sanitize_output, ensure_vibe_dir, find_project_root, load_config, is_skill_file, detect_drift_details
    from integrity import write_lock, verify_lock, hash_file

# Helpers

def vibe_dir_for(root: Path) -> Path:
    return root / ".vibe"

def state_paths(root: Path):
    v = vibe_dir_for(root)
    return v / "state.md", v / "state.json", v / "state.lock", v / "debt.md", v / "decisions.md"

def check_integrity(root: Path) -> tuple[bool, str]:
    """Verify state integrity for any command — repository is source of truth"""
    state_md, _, lock_path, _, _ = state_paths(root)
    if not state_md.exists() or not lock_path.exists():
        return True, ""  # No state yet is not an error
    valid, cur, msg = verify_lock(state_md, lock_path)
    if not valid:
        return False, msg
    return True, "VALID"

def integrity_warning(root: Path) -> str:
    """Spec-exact integrity warning block, or "" when state is valid/missing."""
    valid, _ = check_integrity(root)
    if not valid:
        return ("Integrity: INVALID\n"
                "Warning: The persisted Vibe State has changed since its integrity record was created.\n"
                "Repository state remains authoritative.\n")
    return ""

def safe_display(text: str) -> str:
    """Sanitize text for display: redact secrets, filter prompt-injection patterns."""
    return sanitize_output(text)


def frame_data(text: str) -> str:
    """Display repository-controlled text as DATA (spec: framed with `Repository content:`).

    Sanitization/injection filtering is preserved via safe_display; the framing
    marks the value as data so host agents never treat it as instructions.
    """
    return "Repository content: " + safe_display(text)

def _ensure_vibe_file(path: Path, template_name: str, fallback: str):
    """Copy one skill template into .vibe/, or write the fallback if unavailable."""
    if path.exists():
        return
    # Prefer skill template file if it exists (installation-independent)
    tmpl = SKILL_DIR / "templates" / template_name
    if tmpl.exists():
        try:
            path.write_text(tmpl.read_text(encoding='utf-8'), encoding='utf-8')
            return
        except:
            pass
    path.write_text(fallback, encoding='utf-8')

def ensure_templates(root: Path):
    """Ensure .vibe files exist with templates if not"""
    vibe = ensure_vibe_dir(root)
    state_md, state_json, lock, debt_md, decisions_md = state_paths(root)
    _ensure_vibe_file(debt_md, "debt.md", """# Technical Debt Ledger

This file tracks intentional shortcuts that could affect future development.
Only meaningful debt is recorded - not every minor imperfection.

## How to use
- Status: OPEN, MONITORING, RESOLVED, ACCEPTED
- Priority is calculated as Impact × Likelihood × Migration Cost

---
""")
    _ensure_vibe_file(decisions_md, "decisions.md", """# Architectural Decisions

Records important decisions that affect future implementation.

---
""")
    return vibe

def compute_health_scores(scan) -> Dict[str, int]:
    """Compute scores 0-100 for each dimension — uses configurable thresholds from .vibe/config.json"""
    cfg = getattr(scan, 'config', {}) or {}
    # Configurable thresholds with defaults
    todo_warn = cfg.get("todo_warning_threshold", 20)
    # Start high
    velocity = 90
    architecture = 85
    maintainability = 85
    continuity = 90

    # Velocity deductions: large files, todos, coupling
    if scan.large_files:
        velocity -= min(20, len(scan.large_files)*5)
        architecture -= min(15, len(scan.large_files)*4)
    if scan.todo_count > todo_warn:
        velocity -= 10
        maintainability -= 10
    if scan.todo_count > todo_warn * 2.5:
        velocity -= 10
        maintainability -= 15
    if scan.coupling_score > 50:
        velocity -= 10
        architecture -= 10
    if len(scan.duplication_candidates) > 3:
        velocity -= 10
        maintainability -= 15
    if scan.config_file_count > 8:
        velocity -= 5
        maintainability -= 5
    if scan.hardcoded_count > 30:
        maintainability -= 10
    if scan.secrets_detected > 0:
        architecture -= 15

    # Architecture based on pattern consistency and drift
    if scan.architecture_pattern in ["mixed / evolving"]:
        architecture -= 15
    if len(scan.state_mgmt) > 2:
        architecture -= 15  # multiple competing state libs
        continuity -= 15
    if len(scan.database_hints) > 2:
        architecture -= 10
    if scan.coupling_score > 70:
        architecture -= 15

    # Maintainability
    if scan.total_lines > 20000 and scan.large_files:
        maintainability -= 15
    if scan.duplication_candidates:
        maintainability -= min(20, len(scan.duplication_candidates)*5)
    if scan.todo_count > 10:
        maintainability -= 5

    # Context Continuity - based on git consistency, state file existence
    vibe = scan.root / ".vibe"
    has_state = (vibe / "state.md").exists()
    has_debt = (vibe / "debt.md").exists()
    if not has_state:
        continuity -= 15
    if not has_debt:
        continuity -= 5
    if scan.has_git and scan.git_status:
        changed_lines = scan.git_status.count("\n") + 1 if scan.git_status else 0
        if changed_lines > 10:
            continuity -= 10
    if len(scan.state_mgmt) > 1:
        continuity -= 10
    if scan.todo_count > 30:
        continuity -= 5

    # Technical Debt percent: higher means more debt
    debt_percent = 15
    debt_percent += min(40, scan.todo_count)  # 1 per todo up to 40
    debt_percent += len(scan.large_files)*3
    debt_percent += len(scan.duplication_candidates)*5
    debt_percent += min(20, scan.hardcoded_count//2)
    if scan.secrets_detected:
        debt_percent += 10
    # clamp
    def clamp(v): return max(5, min(95, v))
    return {
        "velocity": clamp(velocity),
        "architecture": clamp(architecture),
        "maintainability": clamp(maintainability),
        "continuity": clamp(continuity),
        "debt": clamp(debt_percent)  # debt level where lower is better, but we cap
    }

def overall_label(scores: Dict[str,int], scan) -> Tuple[str, str, str, str]:
    avg = (scores["velocity"] + scores["architecture"] + scores["maintainability"] + scores["continuity"]) / 4
    debt = scores["debt"]
    # adjust avg down if debt high
    adjusted = avg - (debt - 20)*0.3
    if adjusted >= 80 and debt < 40:
        return "HEALTHY", "Low", "Keep going. Your velocity is protected.", "LOW"
    elif adjusted >= 65 and debt < 60:
        return "WATCH", "Medium", "Small fixes now will prevent bigger slowdowns.", "MEDIUM"
    elif adjusted >= 45 or debt >= 60:
        return "AT RISK", "High", "Address the main risk before adding more features.", "MEDIUM"
    else:
        return "CRITICAL", "High", "Pause new features - fix architecture first.", "HIGH"

def detect_main_risk(scan, scores) -> Tuple[str, str]:
    risks = []
    if scan.large_files:
        risks.append((f"{len(scan.large_files)} oversized file(s) >400 lines (largest {scan.large_files[0][1]} lines)", "ARCHITECTURE"))
    if scan.todo_count > 15:
        risks.append((f"{scan.todo_count} TODO/FIXME/HACK markers accumulating", "MAINTAINABILITY"))
    if len(scan.state_mgmt) > 1:
        risks.append((f"Multiple state-management patterns: {', '.join(scan.state_mgmt)}", "CONTEXT DRIFT"))
    if len(scan.duplication_candidates) > 2:
        risks.append((f"Duplicated logic/symbols in {len(scan.duplication_candidates)} places", "MAINTAINABILITY"))
    if scan.coupling_score > 60:
        risks.append((f"Tightly coupled modules (coupling {scan.coupling_score}/100)", "ARCHITECTURE"))
    if scan.hardcoded_count > 20:
        risks.append((f"{scan.hardcoded_count} hardcoded values / URLs", "CONFIGURATION"))
    if scan.secrets_detected > 0:
        risks.append((f"Potential hardcoded secrets detected ({scan.secrets_detected})", "SECURITY"))
    if scan.config_file_count > 10:
        risks.append((f"Configuration sprawl ({scan.config_file_count} config files)", "CONFIGURATION"))
    if len(scan.database_hints) > 2:
        risks.append((f"Multiple database systems: {', '.join(scan.database_hints)}", "DATA"))
    if not risks:
        if scores["debt"] > 50:
            risks.append(("Moderate technical debt accumulating", "TECHNICAL DEBT"))
        else:
            risks.append(("No major risk detected - project is tidy", "HEALTHY"))

    # prioritize
    priority = {"SECURITY":0, "ARCHITECTURE":1, "CONTEXT DRIFT":2, "MAINTAINABILITY":3, "TECHNICAL DEBT":4, "CONFIGURATION":5}
    risks_sorted = sorted(risks, key=lambda x: priority.get(x[1], 9))
    main, cat = risks_sorted[0]
    why = ""
    if cat == "ARCHITECTURE":
        why = "Oversized or tightly coupled files make every future change touch more code than it should."
    elif cat == "MAINTAINABILITY":
        why = "Duplicated logic and TODOs mean you fix the same bug in multiple places."
    elif cat == "CONTEXT DRIFT":
        why = "Mixing different patterns (like multiple state libraries) makes the next feature harder to build consistently."
    elif cat == "SECURITY":
        why = "Hardcoded secrets work now but will leak if the repo is ever shared or deployed."
    elif cat == "CONFIGURATION":
        why = "Hardcoded URLs and sprawling config make environment changes risky and error-prone."
    elif cat == "DATA":
        why = "Multiple database patterns increase migration cost and data-ownership confusion."
    else:
        why = "No major structural issue - focus on keeping conventions tidy."
    return main, why

# ---------------- HEALTH CHECK ----------------
def cmd_health(root: Path):
    scan = scan_repo(root, fast=True)
    scores = compute_health_scores(scan)
    overall, regret_magnitude, recommended_next, future_regret = overall_label(scores, scan)
    main_risk, why = detect_main_risk(scan, scores)
    # Integrity check — repository is source of truth
    warn = integrity_warning(root)
    if warn:
        print(warn)

    # Velocity etc already computed
    print("VIBE CHECK")
    print()
    print(f"Overall: {overall}")
    print()
    print(f"Velocity:")
    print(f"{render_bar(scores['velocity'])} {scores['velocity']}%")
    print()
    print(f"Architecture:")
    print(f"{render_bar(scores['architecture'])} {scores['architecture']}%")
    print()
    print(f"Maintainability:")
    print(f"{render_bar(scores['maintainability'])} {scores['maintainability']}%")
    print()
    print(f"Context Continuity:")
    print(f"{render_bar(scores['continuity'])} {scores['continuity']}%")
    print()
    print(f"Technical Debt:")
    print(f"{render_bar(scores['debt'])} {scores['debt']}%")
    print()
    print(f"Main Risk:")
    print(f"{main_risk}")
    print()
    print(f"Why:")
    print(f"{why}")
    print()
    print(f"Recommended next move:")
    # tailored recommendation
    if overall == "HEALTHY":
        print("Keep shipping. Run `/vibe-check sync` to capture current decisions.")
    elif overall == "WATCH":
        # pick top actionable
        if scan.todo_count > 20:
            print("Schedule a 1-hour cleanup of TODOs and duplicated logic. Run `/vibe-check debt` to prioritize.")
        elif scan.large_files:
            print(f"Split {scan.large_files[0][0].name} ({scan.large_files[0][1]} lines) into smaller modules.")
        elif len(scan.state_mgmt) > 1:
            print(f"Consolidate state management to one pattern (currently: {', '.join(scan.state_mgmt)}).")
        else:
            print(recommended_next)
    elif overall == "AT RISK":
        print(f"Address the main risk first: {main_risk}. Use `/vibe-check audit` for a deeper view.")
    else:
        print("Stop and fix: run `/vibe-check audit` and `/vibe-check debt` before adding features.")
    print()
    print(f"Future regret if ignored:")
    print(f"{future_regret}")
    print()

    # brief details if needed
    if scan.large_files or scan.todo_count>0 or scan.duplication_candidates:
        print("Details:")
        if scan.large_files:
            for p,l in scan.large_files[:3]:
                print(f"  • Large file: {safe_display(str(p.relative_to(root)))} — {l} lines")
        if scan.todo_count:
            print(f"  • TODO/FIXME count: {scan.todo_count}")
        if scan.duplication_candidates:
            for desc, paths in scan.duplication_candidates[:2]:
                print(f"  • {safe_display(desc)}")
        print()
    # drift hint
    if len(scan.state_mgmt) > 1 or len(scan.database_hints) > 1:
        print("Context drift hints:")
        if len(scan.state_mgmt) > 1:
            print(f"  • Multiple state libs: {', '.join(scan.state_mgmt)}")
        if len(scan.database_hints) > 1:
            print(f"  • Multiple DB hints: {', '.join(scan.database_hints)}")
        print()

# ---------------- FORECAST ----------------
# (keywords, points, risk text, migration-surface text). points=None selects the
# database special case below (UI talking straight to the DB scores higher).
# Order is significant: risks/surfaces are reported in rule order.
FORECAST_KEYWORD_RULES = [
    (("hardcode", "hard code", "hard-coded"), 25,
     "Hardcoded values couple many future files to this shortcut",
     "Every file that reads this value will need updating"),
    (("auth", "login", "password", "token", "session", "permission", "role"), 30,
     "Authentication logic touches almost every layer",
     "lib/auth/*, api/middleware, UI components, database user table"),
    (("bypass", "skip", "ignore", "disable", "without auth", "without validation"), 20,
     "Skipping validation/security creates future migration + security rework",
     "Validation layer, API contracts, frontend forms"),
    (("database", "db", "firebase", "supabase", "postgres", "sqlite", "direct db", "ui -> db"), None, None, None),
    (("temporary", "quick", "just for now", "mvp", "hack", "quick fix", "shortcut"), 10,
     "Temporary code tends to become permanent_without a migration trigger",
     "Files created in this change + their dependents"),
    (("global", "mutable", "singleton"), 20,
     "Global mutable state creates hidden coupling",
     "All consumers of the global state"),
    (("payment", "money", "checkout", "billing", "stripe"), 35,
     "Payment shortcuts create financial correctness risk",
     "Checkout flow, order model, webhook handlers, ledger"),
    (("api", "endpoint", "rest", "graphql"), 12,
     "API shape will be consumed by multiple clients",
     "API route, client SDK, frontend pages"),
    (("copy", "duplicate", "copy-paste"), 15,
     "Duplication multiplies future bug-fix cost",
     "Duplicated modules + their tests"),
]


def forecast_regret_score(request: str, scan) -> Tuple[int, str, str, str, List[str], List[str]]:
    req = request.lower()
    score = 10
    risks = []
    surfaces = []

    # Keyword mapping (data-driven; same order, scores, and texts as before)
    for keywords, points, risk, surface in FORECAST_KEYWORD_RULES:
        if not any(k in req for k in keywords):
            continue
        if points is None:
            # Database rule: check if UI->DB is suggested
            if "ui" in req and "database" in req:
                score += 25
                risks.append("UI talking directly to database bypasses service boundary")
                surfaces.append("UI components, service layer, repository layer")
            else:
                score += 15
                risks.append("Database assumption will spread across persistence code")
                surfaces.append("Models, repositories, migrations")
        else:
            score += points
            risks.append(risk)
            surfaces.append(surface)

    # Architecture health multiplier
    if scan.coupling_score > 60:
        score += 8
    if len(scan.state_mgmt) > 1:
        score += 5
    if scan.todo_count > 30:
        score += 5

    # Cap 0-100
    score = max(0, min(100, score))

    # Level
    if score <= 20:
        level = "NEGLIGIBLE"
    elif score <= 40:
        level = "LOW"
    elif score <= 60:
        level = "MODERATE"
    elif score <= 80:
        level = "HIGH"
    else:
        level = "SEVERE"

    # Immediate benefit
    if "auth" in req or "login" in req:
        benefit = "Saves 2-4 hours vs. building proper auth boundary"
    elif "database" in req or "migration" in req:
        benefit = "Saves 1-3 hours vs. proper schema/migration design"
    elif "test" in req:
        benefit = "Saves 30-60 minutes now"
    else:
        benefit = "Saves 30-90 minutes of upfront design"

    # Likely future rework
    if score >= 61:
        rework = "You will likely rewrite authentication, update multiple consumers, and migrate data. Estimated 1-3 days later."
    elif score >= 41:
        rework = "Expect to refactor consuming modules and add missing abstraction. Estimated 4-8 hours later."
    elif score >= 21:
        rework = "Minor refactoring to replace shortcut. Estimated 1-3 hours later."
    else:
        rework = "Little to no rework expected. Can be cleaned up in <1 hour."

    if not risks:
        risks = ["Low structural impact - mostly localized"]
    if not surfaces:
        # try to infer surface from changed files
        if scan.recent_changed_files:
            surfaces = [", ".join(scan.recent_changed_files[:5])]
        else:
            surfaces = ["Only the files in this change (localized)"]

    return score, level, benefit, rework, surfaces, risks

def cmd_forecast(root: Path, request: str):
    if not request or request.strip() == "":
        print("FORECAST")
        print()
        print("No request provided.")
        print("Usage: /vibe-check forecast \"Just hardcode the login for now.\"")
        print("Or: python vibe_check.py forecast --request \"your change\"")
        return
    scan = scan_repo(root, fast=True)
    warn = integrity_warning(root)
    if warn:
        print(warn)
    # Frame request as data to prevent prompt injection
    safe_request = frame_data(request)
    score, level, benefit, rework, surfaces, risks = forecast_regret_score(request, scan)

    print("FORECAST")
    print()
    print(f"Requested:")
    print(f"{safe_request}")
    print()
    print(f"Immediate benefit:")
    print(f"{safe_display(benefit)}")
    print()
    print(f"Detected risk:")
    for r in risks[:3]:
        print(f"• {safe_display(r)}")
    print()
    print(f"Likely future rework:")
    print(f"{safe_display(rework)}")
    print()
    print(f"Estimated migration surface:")
    for s in surfaces[:3]:
        print(f"• {frame_data(s)}")
    # also include count of files that would be affected
    affected_estimate = "1-2 files" if score < 40 else "3-6 files" if score < 70 else "6-15+ files"
    print(f"• Estimated affected files: {affected_estimate}")
    print()
    print(f"Regret score:")
    print(f"{score}/100 — {level}")
    print()
    # Recommendation — honors regret thresholds from .vibe/config.json (defaults 40/70)
    cfg = getattr(scan, 'config', {}) or {}
    warn_thresh = cfg.get("regret_warning_threshold", 40)
    block_thresh = cfg.get("regret_blocking_threshold", 70)
    if score >= block_thresh:
        rec = "You can do this, but isolate it. Create a single boundary file (e.g., lib/auth/boundary.js) so replacement is one-file swap. Add debt entry."
        alt = "Fastest safe alternative: Create one interface/abstraction now - hardcode behind it. Keeps the shortcut but limits coupling."
    elif score >= warn_thresh:
        rec = "Proceed with caution. Add a TODO and a debt entry with a future trigger (e.g., 'replace before production auth')."
        alt = "Fastest safe alternative: Extract the shortcut into a dedicated function/file you can replace later."
    else:
        rec = "Low regret - proceed normally. No special isolation needed."
        alt = "Alternative: same as requested - negligible future cost."
    print(f"Recommendation:")
    print(f"{rec}")
    print()
    print(f"Fastest safe alternative:")
    print(f"{alt}")
    print()
    # Also helpful to show debt ledger impact
    print("You can do this. Here's the cost. (Human remains in control.)")
    print()

# ---------------- DEBT ----------------
def parse_debt_ledger(debt_path: Path) -> List[Dict]:
    if not debt_path.exists():
        return []
    text = debt_path.read_text(encoding='utf-8', errors='ignore')
    debts = []
    # split by ## DEBT-
    parts = re.split(r'(?m)^##\s+DEBT-(\d+)', text)
    # first part is header
    for i in range(1, len(parts), 2):
        num = parts[i]
        body = parts[i+1] if i+1 < len(parts) else ""
        # parse fields Title:, Created:, Location:, Why..., Risk:, Future trigger:, Estimated rework:, Status:
        def get_field(name):
            m = re.search(rf'(?m)^{re.escape(name)}:\s*(.+)$', body)
            if m:
                return m.group(1).strip()
            # try multiline next line?
            m2 = re.search(rf'{re.escape(name)}:\s*\n(.+)', body)
            return m2.group(1).strip()[:200] if m2 else ""
        debt = {
            "id": f"DEBT-{num}",
            "title": get_field("Title"),
            "created": get_field("Created"),
            "location": get_field("Location"),
            "why": get_field("Why it exists"),
            "risk": get_field("Risk"),
            "trigger": get_field("Future trigger"),
            "rework": get_field("Estimated rework"),
            "status": get_field("Status") or "OPEN",
            "raw": body
        }
        # fallback title from first line if missing
        if not debt["title"]:
            lines = [l.strip() for l in body.splitlines() if l.strip() and not l.startswith("Title")]
            debt["title"] = lines[0][:80] if lines else f"Debt {num}"
        debts.append(debt)
    return debts

def debt_priority_score(debt: Dict) -> int:
    risk_map = {"critical":4, "high":3, "medium":2, "low":1, "severe":4}
    risk_val = risk_map.get(debt.get("risk","").lower().split()[0], 2)
    # rework mapping
    rework = debt.get("rework","").lower()
    if "hour" in rework:
        m = re.search(r'(\d+)\s*[-–]\s*(\d+)', rework)
        if m:
            hrs = int(m.group(2))
        else:
            m2 = re.search(r'(\d+)', rework)
            hrs = int(m2.group(1)) if m2 else 2
        if hrs <= 2:
            cost = 1
        elif hrs <= 4:
            cost = 2
        elif hrs <= 8:
            cost = 3
        else:
            cost = 4
    elif "day" in rework:
        cost = 4
    else:
        cost = 2
    # likelihood approximated by status + age? use risk as likelihood proxy
    likelihood = 2
    if debt.get("risk","").lower().startswith("high") or debt.get("risk","").lower().startswith("critical"):
        likelihood = 3
    score = risk_val * likelihood * cost
    return score

def priority_label(score: int) -> str:
    if score >= 12:
        return "P0"
    elif score >= 6:
        return "P1"
    elif score >= 3:
        return "P2"
    else:
        return "P3"

def cmd_debt(root: Path):
    ensure_templates(root)
    _, _, _, debt_path, _ = state_paths(root)
    warn = integrity_warning(root)
    if warn:
        print(warn)
    debts = parse_debt_ledger(debt_path)
    # also auto-detect potential debt from scan if ledger empty?
    scan = scan_repo(root, fast=True)
    if not debts:
        print("TECHNICAL DEBT REPORT")
        print()
        print("No debt ledger entries found.")
        if scan.todo_count > 10 or scan.large_files or scan.duplication_candidates:
            print("Potential debt detected by scanner (not yet recorded):")
            if scan.todo_count > 10:
                print(f"  • {scan.todo_count} TODOs - consider adding DEBT entry for systematic shortcuts")
            if scan.large_files:
                print(f"  • {len(scan.large_files)} large files - potential splitting debt")
            if scan.duplication_candidates:
                print(f"  • Duplicated logic - potential deduplication debt")
            print()
            print("Run `/vibe-check sync` to initialize or manually add to .vibe/debt.md")
        else:
            print("Repository appears clean. No meaningful debt detected.")
        print()
        print("Ledger: .vibe/debt.md")
        return

    # Categorize
    buckets = {"P0":[], "P1":[], "P2":[], "P3":[]}
    for d in debts:
        if d["status"] in ["RESOLVED", "ACCEPTED"]:
            continue
        score = debt_priority_score(d)
        label = priority_label(score)
        d["_score"] = score
        d["_priority"] = label
        buckets[label].append(d)

    print("TECHNICAL DEBT REPORT")
    print()
    for pri in ["P0","P1","P2","P3"]:
        label_full = {"P0":"P0 — dangerous","P1":"P1 — high impact","P2":"P2 — worth fixing","P3":"P3 — monitor"}[pri]
        print(f"{label_full}")
        items = buckets[pri]
        if not items:
            print("  (none)")
        else:
            # sort by score desc
            items = sorted(items, key=lambda x: x["_score"], reverse=True)
            for d in items[:5]:
                line = f"{d['id']}: {d['title']} [{d['status']}|Risk:{d['risk']}|Rework:{d['rework']}] — {d['location']}"
                print(f"  • {frame_data(line)}")
        print()

    total_open = sum(len(v) for v in buckets.values())
    print(f"Total meaningful debt: {total_open} open")
    # most important
    all_open = [d for bucket in buckets.values() for d in bucket]
    if all_open:
        most = sorted(all_open, key=lambda x: x["_score"], reverse=True)[0]
        top = f"{most['id']} — {most['title']} (Priority {most['_priority']})"
        print(f"Most important debt: {frame_data(top)}")
        print()
        print("Recommended order:")
        sorted_all = sorted(all_open, key=lambda x: x["_score"], reverse=True)[:3]
        for i, d in enumerate(sorted_all, 1):
            item = f"{d['id']} — {d['title']} ({d['_priority']})"
            print(f"{i}. {frame_data(item)}")
    print()
    print("Ledger: .vibe/debt.md  |  Run `/vibe-check sync` to update")

def add_debt_entry(root: Path, title: str, location: str, why: str, risk: str="Medium", trigger: str="TBD — requires developer confirmation.", rework: str="2–4 hours"):
    vibe = ensure_templates(root)
    _, _, _, debt_path, _ = state_paths(root)
    debts = parse_debt_ledger(debt_path)
    next_num = f"{len(debts)+1:03d}"
    # ensure not duplicate
    existing_ids = {d["id"] for d in debts}
    while f"DEBT-{next_num}" in existing_ids:
        next_num = f"{int(next_num)+1:03d}"
    today = datetime.now(timezone.utc).date().isoformat()
    # Sanitize all repository-controlled fields to prevent secret leakage
    title_s = sanitize_for_state(title)
    location_s = sanitize_for_state(location)
    why_s = sanitize_for_state(why)
    risk_s = sanitize_for_state(risk)
    trigger_s = sanitize_for_state(trigger)
    rework_s = sanitize_for_state(rework)
    # Enforce TBD placeholders if empty
    if not trigger_s or trigger_s.strip() == "":
        trigger_s = "TBD — requires developer confirmation."
    if not rework_s or rework_s.strip() == "":
        rework_s = "TBD — requires developer confirmation."
    entry = f"""
## DEBT-{next_num}

Title:
{title_s}

Created:
{today}

Location:
{location_s}

Why it exists:
{why_s}

Risk:
{risk_s}

Future trigger:
{trigger_s}

Estimated rework:
{rework_s}

Status:
OPEN
"""
    with open(debt_path, 'a', encoding='utf-8') as f:
        f.write(entry)
    return f"DEBT-{next_num}"

# ---------------- SYNC ----------------
def generate_state_content(root: Path, scan, existing_state: str = None) -> str:
    # Try to preserve existing values if provided
    # For MVP, generate new but try to infer
    vibe = root / ".vibe"
    debt_path = vibe / "debt.md"
    debt_items = parse_debt_ledger(debt_path)
    open_debt = [d for d in debt_items if d["status"] in ["OPEN","MONITORING"]]
    # Detect names
    project_name = root.name
    # Try reading package.json, etc for name + description
    purpose = "Vibe-coded project"
    try:
        if (root / "package.json").exists():
            data = json.loads((root / "package.json").read_text(encoding='utf-8', errors='ignore'))
            project_name = data.get("name", project_name)
            purpose = data.get("description", purpose)
        elif (root / "pyproject.toml").exists():
            txt = (root / "pyproject.toml").read_text(encoding='utf-8', errors='ignore')
            m = re.search(r'name\s*=\s*["\'](.+?)["\']', txt)
            if m:
                project_name = m.group(1)
        elif (root / "pubspec.yaml").exists():
            txt = (root / "pubspec.yaml").read_text(encoding='utf-8', errors='ignore')
            m = re.search(r'name:\s*(.+)', txt)
            if m:
                project_name = m.group(1).strip()
    except:
        pass

    # Stage detection
    total_files = scan.total_files
    if total_files < 15:
        stage = "MVP / prototype"
    elif total_files < 50:
        stage = "Early product"
    elif total_files < 150:
        stage = "Growth"
    else:
        stage = "Mature"

    backend = ", ".join(scan.api_patterns) if scan.api_patterns else "TBD — requires developer confirmation."
    frontend = ", ".join(scan.framework_hints) if scan.framework_hints else "TBD — requires developer confirmation."
    # Try more specific
    if "react/next" in scan.framework_hints:
        frontend = "React / Next.js"
    elif "flutter/dart" in scan.framework_hints:
        frontend = "Flutter"
    elif "vue" in scan.framework_hints:
        frontend = "Vue"
    database = ", ".join(scan.database_hints) if scan.database_hints else "TBD — requires developer confirmation."
    state_mgmt_str = ", ".join(scan.state_mgmt) if scan.state_mgmt else "TBD — requires developer confirmation."

    # Design language detection — use TBD for uncertain decisions
    design_style = "TBD — requires developer confirmation."
    spacing = "TBD — requires developer confirmation."
    typography = "TBD — requires developer confirmation."
    component_phil = "feature-based" if "feature" in scan.architecture_pattern else scan.architecture_pattern
    if component_phil in ["mixed / evolving", "unknown"]:
        component_phil = "TBD — requires developer confirmation."

    # Try to infer from files
    has_tailwind = any("tailwind" in str(p).lower() or "tailwind" in "".join(scan.dependencies).lower() for p in scan.dependency_files)
    if has_tailwind:
        design_style = "Tailwind utility-first"
    elif scan.framework_hints and "flutter" in " ".join(scan.framework_hints).lower():
        design_style = "Material 3"
    elif "react" in " ".join(scan.framework_hints).lower():
        design_style = "component-based (React)"

    # Coding preferences - infer naming
    naming = "camelCase (JS/TS)" if any(p.suffix in [".js",".ts",".tsx",".jsx"] for p in scan.source_files) else "snake_case / mixed"
    if any(p.suffix == ".py" for p in scan.source_files):
        naming = "snake_case (Python) / mixed"

    file_org = scan.architecture_pattern
    error_handling = "try/catch + validation" if scan.todo_count < 20 else "inconsistent - needs conventions"
    testing = "not detected" 
    # check for test files
    has_tests = any("test" in str(p).lower() or "spec" in str(p).lower() for p in scan.source_files)
    if has_tests:
        testing = "tests present (partial)"

    # Important decisions - try to preserve existing
    important_decisions = []
    if existing_state:
        # extract existing decisions bullet if exist
        m = re.search(r'## Important Decisions\s*(.+?)\n## ', existing_state, re.DOTALL)
        if m:
            important_decisions = [l.strip() for l in m.group(1).strip().splitlines() if l.strip() and l.strip().startswith("-")]
    if not important_decisions:
        important_decisions = [
            f"- Architecture pattern: {scan.architecture_pattern}",
            f"- State management: {state_mgmt_str}" if state_mgmt_str != "local / not detected" else "- State: local component state",
            f"- Database: {database}" if database != "not detected / file-based" else "- Persistence: TBD",
        ]

    current_focus = "Active development"
    if scan.git_log_recent:
        current_focus = scan.git_log_recent[0][:80] if scan.git_log_recent else current_focus

    known_constraints = "- Keep velocity high; avoid premature abstraction"
    if scan.todo_count > 20:
        known_constraints += "\n- TODO accumulation - schedule cleanup"
    if scan.coupling_score > 60:
        known_constraints += "\n- High coupling - avoid adding global state"

    dont_break = []
    dont_break.append(f"- Existing {scan.architecture_pattern} organization")
    if scan.state_mgmt:
        dont_break.append(f"- State management: {state_mgmt_str}")
    if scan.database_hints:
        dont_break.append(f"- Database: {database}")
    dont_break.append("- Don't hardcode secrets into UI")

    next_direction = "Iterate on current features; prepare for production hardening"

    # debt summary
    debt_summary = f"{len(open_debt)} open items" if open_debt else "none tracked"

    content = f"""# Vibe State

## Project
Name: {project_name}
Purpose: {sanitize_for_state(purpose)[:120]}
Current stage: {stage}

## Architecture
Pattern: {scan.architecture_pattern}
Backend: {sanitize_for_state(backend)}
Frontend: {sanitize_for_state(frontend)}
Database: {sanitize_for_state(database)}
State management: {sanitize_for_state(state_mgmt_str)}

## Design Language
Style: {design_style}
Spacing: {spacing}
Typography: {typography}
Component philosophy: {component_phil}

## Coding Preferences
Naming: {naming}
File organization: {file_org}
Error handling: {error_handling}
Testing philosophy: {testing}

## Important Decisions
{chr(10).join(important_decisions) if important_decisions else "- (none yet)"}

## Current Focus
{current_focus[:200]}

## Known Constraints
{known_constraints}

## Active Technical Debt
{debt_summary}

## Don't Break
{chr(10).join(dont_break)}

## Next Likely Direction
{next_direction}
"""
    # Ensure <5KB
    if len(content.encode('utf-8')) > 5000:
        # truncate some sections
        content = content[:4900] + "\n"
    return content

def cmd_sync(root: Path, dry_run: bool = False):
    scan = scan_repo(root, fast=True)
    vibe = ensure_templates(root)
    state_md, state_json, lock_path, debt_path, decisions_path = state_paths(root)

    had_state = state_md.exists()
    existing = state_md.read_text(encoding='utf-8', errors='ignore') if had_state else None
    integrity_before = "N/A"
    if had_state and lock_path.exists():
        valid, cur, msg = verify_lock(state_md, lock_path)
        integrity_before = msg
        if not valid:
            warn = integrity_warning(root)
            if warn:
                print(warn)
    else:
        integrity_before = "no prior lock"

    new_content = generate_state_content(root, scan, existing_state=existing)
    # sanitize before write
    new_content = sanitize_for_state(new_content)

    # detect changes
    detected = []
    preserved = []

    if had_state:
        # simple diff heuristics
        if existing:
            if scan.architecture_pattern not in existing:
                detected.append(f"Architecture pattern: {scan.architecture_pattern}")
            if scan.state_mgmt and ", ".join(scan.state_mgmt) not in existing:
                if scan.state_mgmt:
                    detected.append(f"State management: {', '.join(scan.state_mgmt)}")
            if scan.database_hints and ", ".join(scan.database_hints) not in existing:
                detected.append(f"Database: {', '.join(scan.database_hints)}")
            # check deps
            if scan.git_diff_stat and "package.json" in scan.git_diff_stat:
                detected.append("Dependency changes")

            # preserved
            if scan.architecture_pattern in existing:
                preserved.append("Existing architecture pattern")
            if scan.state_mgmt and all(x in existing for x in scan.state_mgmt):
                preserved.append("Existing state-management pattern")
            if "feature-based" in existing.lower() and "feature" in scan.architecture_pattern.lower():
                preserved.append("Existing folder structure")
            if not preserved:
                preserved.append("Existing project conventions")
        # debt detection
        debts = parse_debt_ledger(debt_path)
        open_count = len([d for d in debts if d["status"]=="OPEN"])
        if open_count > 0:
            detected.append(f"{open_count} technical debt item(s) active")
    else:
        detected.append("Initial state created")
        detected.append(f"Architecture: {scan.architecture_pattern}")
        if scan.state_mgmt:
            detected.append(f"State management: {', '.join(scan.state_mgmt)}")

    # --- Dry-run preview: show diff without writing ---
    if dry_run:
        print("VIBE SYNC — DRY RUN (no files written)")
        print()
        print(f"Would write: {state_md.relative_to(root)} ({len(new_content.encode('utf-8'))/1024:.1f} KB)")
        if had_state and existing is not None:
            # show simple diff preview
            old_lines = existing.splitlines()
            new_lines = new_content.splitlines()
            added = [l for l in new_lines if l not in old_lines][:10]
            removed = [l for l in old_lines if l not in new_lines][:10]
            if added:
                print("Would add:")
                for l in added:
                    print(f"+ {frame_data(l[:120])}")
            if removed:
                print("Would remove:")
                for l in removed:
                    print(f"- {frame_data(l[:120])}")
            if not added and not removed:
                print("No changes detected — state already up to date.")
        else:
            print("Would create initial state from repository scan.")
            print(f"Architecture: {scan.architecture_pattern}")
        print()
        print("Run without --dry-run to apply. Repository is source of truth.")
        return

    # --- Backup previous state before overwriting (spec: .vibe/state.md.bak) ---
    if had_state and existing is not None:
        try:
            backup_path = vibe / "state.md.bak"
            shutil.copy2(state_md, backup_path)
        except Exception as e:
            print(f"Warning: could not create backup: {safe_display(str(e))}", file=sys.stderr)

    # Write state.md
    try:
        state_md.write_text(new_content, encoding='utf-8')
    except Exception as e:
        print(f"Error: could not write state.md: {safe_display(str(e))}", file=sys.stderr)
        return
    # Write state.json optional
    state_json_data = {
        "project": {"name": root.name, "stage": "mvp" if scan.total_files < 30 else "early"},
        "architecture": {
            "pattern": scan.architecture_pattern,
            "backend": scan.api_patterns,
            "frontend": scan.framework_hints,
            "database": scan.database_hints,
            "state_management": scan.state_mgmt
        },
        "counts": {
            "files": scan.total_files,
            "lines": scan.total_lines,
            "todos": scan.todo_count,
            "large_files": len(scan.large_files),
            "config_files": scan.config_file_count
        },
        "integrity": {},
        "updated": datetime.now(timezone.utc).isoformat()
    }
    try:
        state_json.write_text(json.dumps(state_json_data, indent=2), encoding='utf-8')
    except Exception as e:
        print(f"Error: could not write state.json: {safe_display(str(e))}", file=sys.stderr)

    # write lock
    try:
        new_hash = write_lock(state_md, lock_path)
    except Exception as e:
        print(f"Error: could not write integrity lock: {safe_display(str(e))}", file=sys.stderr)
        return
    # verify
    valid, cur, msg = verify_lock(state_md, lock_path)
    state_size_kb = len(new_content.encode('utf-8'))/1024

    # Also check for drift
    drift_notes = []
    if len(scan.state_mgmt) > 1:
        drift_notes.append(f"Multiple state patterns: {', '.join(scan.state_mgmt)}")

    print("VIBE SYNC")
    print()
    print(f"State:")
    print("UPDATED" if had_state else "CREATED")
    print()
    print("Detected:")
    if detected:
        for d in detected:
            print(f"+ {d}")
    else:
        print("+ No major changes detected")
    # also mention recent git
    if scan.git_log_recent:
        print(f"+ Recent commit: {frame_data(scan.git_log_recent[0][:60])}")
    print()
    print("Preserved:")
    for p in preserved[:5]:
        print(f"✓ {p}")
    if not preserved:
        print("✓ (baseline preserved)")
    print()
    print(f"State size:")
    print(f"{state_size_kb:.1f} KB")
    print()
    print(f"Integrity:")
    print("VALID" if valid else f"INVALID — {msg}")
    if drift_notes:
        print()
        print("Notes:")
        for n in drift_notes:
            print(f"• {n}")

# ---------------- AUDIT ----------------
def cmd_audit(root: Path):
    scan = scan_repo(root, fast=False)
    warn = integrity_warning(root)
    if warn:
        print(warn)
    print("ARCHITECTURAL AUDIT")
    print()
    # Expanded drift detection
    drifts = detect_drift_details(scan.source_files, scan) if 'detect_drift_details' in globals() else []
    if drifts:
        print("## Drift Detection")
        for cat, desc, conf in drifts:
            print(f"• [{cat}] {safe_display(desc)} (confidence: {conf})")
        print()
    # Architecture
    print("## Architecture")
    arch_issues = []
    if scan.coupling_score > 70:
        arch_issues.append(f"Critical: High coupling ({scan.coupling_score}/100) - modules are tightly interdependent")
    elif scan.coupling_score > 50:
        arch_issues.append(f"High: Moderate coupling ({scan.coupling_score}/100)")
    if len(scan.state_mgmt) > 2:
        arch_issues.append(f"Critical: {len(scan.state_mgmt)} competing state libraries: {', '.join(scan.state_mgmt)}")
    elif len(scan.state_mgmt) > 1:
        arch_issues.append(f"Medium: Multiple state patterns: {', '.join(scan.state_mgmt)}")
    if scan.architecture_pattern == "mixed / evolving":
        arch_issues.append("Medium: Inconsistent architecture patterns (mixed/evolving)")
    if not arch_issues:
        arch_issues.append("Healthy: Clear architecture boundaries")

    for iss in arch_issues:
        print(f"• {iss}")
    print()
    # Codebase
    print("## Codebase")
    if scan.large_files:
        for p,l in scan.large_files[:5]:
            sev = "Critical" if l>800 else "High" if l>600 else "Medium"
            print(f"• {sev}: Oversized file {safe_display(str(p.relative_to(root)))} ({l} lines) - consider splitting")
    if scan.duplication_candidates:
        for desc, paths in scan.duplication_candidates[:3]:
            print(f"• Medium: {safe_display(desc)} across {len(paths)} files")
    if scan.todo_count > 20:
        print(f"• Medium: {scan.todo_count} TODO/FIXME markers - debt accumulating")
    elif scan.todo_count > 5:
        print(f"• Low: {scan.todo_count} TODOs")
    if not scan.large_files and not scan.duplication_candidates and scan.todo_count < 10:
        print("• Healthy: No major code complexity issues")
    # dead code heuristic: files not imported anywhere? simplified
    print()
    # Data
    print("## Data")
    data_issues = []
    if len(scan.database_hints) > 2:
        data_issues.append(f"High: Multiple database systems: {', '.join(scan.database_hints)} - data ownership unclear")
    elif len(scan.database_hints) == 0:
        data_issues.append("Low: No clear database/persistence - ensure proper persistence for production")
    else:
        data_issues.append(f"Healthy: Database consistent ({', '.join(scan.database_hints)})")
    if scan.hardcoded_count > 20:
        data_issues.append(f"Medium: Hardcoded data assumptions ({scan.hardcoded_count} hits)")
    for iss in data_issues:
        print(f"• {iss}")
    print()
    # API
    print("## API")
    if scan.api_patterns:
        print(f"• Detected: {', '.join(scan.api_patterns)}")
        if scan.hardcoded_count > 10:
            print(f"• Medium: Hardcoded URLs/endpoints may indicate scattered API calls")
        if len(scan.duplication_candidates) > 1:
            print(f"• Low: Check for duplicated network logic")
    else:
        print("• Low: No clear API pattern detected - ensure consistent contracts")
    # check for validation
    has_validation = any("validat" in str(p).lower() or "zod" in " ".join(scan.dependencies).lower() for p in scan.source_files)
    if not has_validation and scan.total_files > 20:
        print("• Medium: No validation layer detected")
    else:
        print("• Healthy: Validation / contracts likely present")
    print()
    # Frontend
    print("## Frontend")
    if scan.framework_hints:
        print(f"• Framework: {', '.join(scan.framework_hints)}")
    if len(scan.state_mgmt) > 1:
        print(f"• High: Inconsistent state management {scan.state_mgmt}")
    else:
        print(f"• Healthy: State management consistent ({scan.state_mgmt[0] if scan.state_mgmt else 'local'})")
    # check for direct DB in UI heuristic
    direct_db = False
    for f in scan.source_files[:100]:
        if "components" in str(f).lower() or "pages" in str(f).lower() or "screens" in str(f).lower():
            try:
                t = f.read_text(encoding='utf-8', errors='ignore')[:2000].lower()
                if "firebase" in t or "supabase" in t or "prisma" in t or "select * from" in t:
                    direct_db = True
                    break
            except:
                continue
    if direct_db:
        print("• High: Business/database logic leaking into UI components")
    else:
        print("• Healthy: UI separation looks okay")
    print()
    # Infrastructure
    print("## Infrastructure")
    print(f"• Config files: {scan.config_file_count}")
    if scan.config_file_count > 10:
        print("• Medium: Configuration sprawl - consolidate env handling")
    else:
        print("• Healthy: Config manageable")
    if scan.secrets_detected:
        print(f"• Critical: Potential secrets in code ({scan.secrets_detected}) - move to .env")
    else:
        print("• Healthy: No hardcoded secrets detected")
    # check env handling
    has_env = (root / ".env.example").exists() or (root / ".env").exists()
    if not has_env and scan.total_files > 20:
        print("• Low: No .env.example - add for onboarding")
    print()
    # Testing
    print("## Testing")
    has_tests = sum(1 for p in scan.source_files if "test" in str(p).lower() or "spec" in str(p).lower())
    if has_tests == 0:
        print("• High: No tests detected on critical paths")
    elif has_tests < 3:
        print(f"• Medium: Only {has_tests} test files - consider critical-path coverage")
    else:
        print(f"• Healthy: {has_tests} test files")
    if scan.coupling_score > 60 and has_tests == 0:
        print("• High: High coupling + no tests = fragile")
    print()
    # Trajectory
    # Determine trajectory based on git + current health
    print("---")
    scores = compute_health_scores(scan)
    avg = sum([scores["velocity"], scores["architecture"], scores["maintainability"], scores["continuity"]])/4
    if avg >= 80 and not scan.large_files and scan.todo_count <= 10:
        traj = "IMPROVING"
    elif avg >= 75:
        traj = "STABLE"
    elif avg >= 55:
        traj = "STABLE"
        if scan.todo_count > 30 or scan.large_files:
            traj = "DEGRADING"
    else:
        traj = "DEGRADING"
    biggest = detect_main_risk(scan, scores)[0]
    print(f"Architecture trajectory: {traj}")
    print()
    # Biggest risk
    print("Biggest risk:")
    print(f"{biggest}")
    print()
    # Recommended intervention - do now / do later / don't do
    print("Recommended intervention:")
    if traj == "DEGRADING":
        print("DO NOW: Split oversized files, add one architectural boundary (auth/api).")
        print("DO LATER: Broader refactoring, comprehensive tests.")
        print("DON'T DO: Microservices, event buses, or premature abstractions.")
    else:
        print("DO NOW: Run `/vibe-check sync` and keep debt ledger tidy.")
        print("DO LATER: Add tests around risky areas before next major feature.")
        print("DON'T DO: Unnecessary rewrites - velocity is good.")
    print()

# ---------------- DIFF ----------------
def cmd_diff(root: Path):
    scan = scan_repo(root, fast=True)
    warn = integrity_warning(root)
    if warn:
        print(warn)
    vibe = root / ".vibe"
    state_md = vibe / "state.md"
    has_state = state_md.exists()

    print("ARCHITECTURAL DIFF")
    print()
    if scan.git_branch:
        print(f"Branch: {frame_data(scan.git_branch)}")
        print()
    if scan.git_untracked:
        print(f"Untracked files: {frame_data(', '.join(scan.git_untracked[:5]))}")
        print()
    # Before
    print("Before:")
    if has_state:
        try:
            txt = state_md.read_text(encoding='utf-8', errors='ignore')
            # extract architecture line
            m = re.search(r'Pattern:\s*(.+)', txt)
            pat = m.group(1).strip() if m else "unknown"
            m2 = re.search(r'State management:\s*(.+)', txt)
            sm = m2.group(1).strip() if m2 else "unknown"
            # try git previous?
            print(f"• Architecture: {frame_data(pat)}")
            print(f"• State management: {frame_data(sm)}")
            # file size from state json if exists
            sf = vibe / "state.json"
            if sf.exists():
                data = json.loads(sf.read_text(encoding='utf-8', errors='ignore'))
                print(f"• Files: {safe_display(str(data.get('counts',{}).get('files','unknown')))}")
        except:
            print("• State file exists but unreadable")
    else:
        print("• No prior state - run /vibe-check sync for baseline")
    print()
    # After
    print("After:")
    print(f"• Architecture: {scan.architecture_pattern}")
    print(f"• State management: {', '.join(scan.state_mgmt) if scan.state_mgmt else 'none detected'}")
    print(f"• Database: {', '.join(scan.database_hints) if scan.database_hints else 'none'}")
    print(f"• Files: {scan.total_files} | Large files: {len(scan.large_files)} | TODOs: {scan.todo_count}")
    print()
    # Improved / Regressed
    print("Improved:")
    if scan.todo_count < 10 and scan.coupling_score < 50:
        print("✓ Clean TODO list and low coupling")
    else:
        # check git diff suggests improvement?
        if has_state:
            # simplistic: if previous debt but now less?
            print("✓ (check git diff for specifics)")
        else:
            print("✓ No major improvement detection without baseline - create one via sync")
    print()
    print("Regressed:")
    regressed = []
    if scan.large_files:
        regressed.append(f"⚠ Oversized files: {len(scan.large_files)}")
    if len(scan.state_mgmt) > 1:
        regressed.append(f"⚠ Multiple state libs: {', '.join(scan.state_mgmt)}")
    if scan.todo_count > 20:
        regressed.append(f"⚠ TODO accumulation: {scan.todo_count}")
    if scan.hardcoded_count > 20:
        regressed.append(f"⚠ Hardcoded values: {scan.hardcoded_count}")
    if not regressed:
        print("  (none - stable)")
    else:
        for r in regressed:
            print(f"{r}")
    print()
    # New debt
    print("New debt:")
    if scan.has_git and scan.git_diff_stat:
        print(f"  {frame_data(scan.git_diff_stat[:500].replace(chr(10), ', '))}")
        # hint debt
        if "TODO" in scan.git_diff_stat or scan.todo_count:
            print("  • Potential new debt from TODOs/hacks")
    else:
        # check debt file new entries
        debt_path = vibe / "debt.md"
        if debt_path.exists():
            debts = parse_debt_ledger(debt_path)
            open_debts = [d for d in debts if d["status"]=="OPEN"]
            if open_debts:
                print(f"  • {len(open_debts)} open debt entries in ledger")
            else:
                print("  (none tracked)")
        else:
            print("  (no git diff; no debt ledger)")
    print()
    print("Convention violations:")
    violations = []
    if len(scan.state_mgmt) > 1:
        violations.append(f"State management drift: {', '.join(scan.state_mgmt)}")
    if len(scan.database_hints) > 2:
        violations.append(f"DB drift: {', '.join(scan.database_hints)}")
    # Check naming? skip
    if violations:
        for v in violations:
            print(f"• {v}")
    else:
        print("  (none detected)")
    print()
    trajectory = "0"
    scores = compute_health_scores(scan)
    avg = sum([scores["velocity"], scores["architecture"], scores["maintainability"], scores["continuity"]])/4
    if avg < 60 or regressed:
        trajectory = "- (degrading)"
    elif avg > 80:
        trajectory = "+ (improving)"
    else:
        trajectory = "0 (stable)"
    print(f"Overall trajectory:")
    print(f"{trajectory}")
    print()
    # Expanded drift detection in diff
    drifts = detect_drift_details(scan.source_files, scan) if 'detect_drift_details' in globals() else []
    if drifts:
        print("Drift details:")
        for cat, desc, conf in drifts:
            print(f"• [{cat}] {safe_display(desc)} (confidence: {conf})")
        print()
    print("Git details:")
    if scan.has_git:
        print(f"• Branch: {frame_data(scan.git_branch) if scan.git_branch else 'unknown'}")
        print(f"• Status: {frame_data(scan.git_status[:300]) if scan.git_status else 'clean'}")
        if scan.git_untracked:
            print(f"• Untracked: {frame_data(', '.join(scan.git_untracked[:5]))}")
        if scan.git_log_recent:
            print(f"• Recent: {frame_data(scan.git_log_recent[0])}")
        if scan.git_diff_stat:
            print(f"• Diff stat available ({len(scan.git_diff_stat)} chars)")
        if scan.recent_changed_files:
            print(f"• Changed files: {frame_data(', '.join(scan.recent_changed_files[:5]))}")
    else:
        print("• No git repo detected")

# ---------------- RECOVER ----------------
def cmd_recover(root: Path):
    vibe = root / ".vibe"
    state_md = vibe / "state.md"
    debt_md = vibe / "debt.md"
    lock_path = vibe / "state.lock"
    decisions_md = vibe / "decisions.md"

    print("VIBE RECOVER")
    print()
    print("Context-loss recovery: verifying state against repository truth")
    print("Repository is source of truth — state is restored only from repo, not the inverse.")
    print()
    valid_pre, msg_pre = check_integrity(root)
    if not valid_pre and state_md.exists():
        print(f"Integrity: INVALID — {safe_display(msg_pre)}")
        print("Warning: persisted state hash does not match — treating repository as authoritative.")
        print()
    # Load state
    if not state_md.exists():
        print("No .vibe/state.md found.")
        print("Run `/vibe-check sync` to create baseline.")
        scan = scan_repo(root, fast=True)
        print()
        print(f"Repository says:")
        print(f"• Pattern: {scan.architecture_pattern}")
        print(f"• State mgmt: {', '.join(scan.state_mgmt) if scan.state_mgmt else 'none'}")
        print(f"• Files: {scan.total_files}")
        return

    state_text = state_md.read_text(encoding='utf-8', errors='ignore')
    print("Loaded:")
    print(f"• .vibe/state.md ({len(state_text.encode('utf-8'))/1024:.1f} KB)")
    if debt_md.exists():
        debts = parse_debt_ledger(debt_md)
        print(f"• .vibe/debt.md ({len(debts)} entries)")
    else:
        print("• .vibe/debt.md missing")
    if decisions_md.exists():
        print(f"• .vibe/decisions.md present")
    if lock_path.exists():
        lock_data = {}
        try:
            lock_data = {k.strip():v.strip() for k,v in [l.split(":",1) for l in lock_path.read_text().splitlines() if ":" in l]}
            print(f"• .vibe/state.lock present (hash {lock_data.get('state_hash','')[:8]}...)")
        except:
            print("• .vibe/state.lock corrupted")
    print()

    # Verify integrity
    valid, cur, msg = verify_lock(state_md, lock_path) if lock_path.exists() else (False, "", "missing")
    print(f"Integrity: {'VALID' if valid else 'INVALID — ' + msg}")
    print()

    # Compare repo vs state
    scan = scan_repo(root, fast=True)
    conflicts = []
    # Check pattern
    state_pat = re.search(r'Pattern:\s*(.+)', state_text)
    state_pat_text = state_pat.group(1).strip() if state_pat else ""
    if state_pat_text and state_pat_text != scan.architecture_pattern:
        conflicts.append((f"State says pattern: {state_pat_text}", f"Repository says: {scan.architecture_pattern}"))

    state_sm = re.search(r'State management:\s*(.+)', state_text)
    state_sm_text = state_sm.group(1).strip() if state_sm else ""
    scan_sm = ", ".join(scan.state_mgmt) if scan.state_mgmt else "none"
    if state_sm_text and state_sm_text != scan_sm and scan_sm != "none":
        # allow partial match
        if not all(x in state_sm_text for x in scan.state_mgmt):
            conflicts.append((f"State says state management: {state_sm_text}", f"Repository says: {scan_sm}"))

    state_db = re.search(r'Database:\s*(.+)', state_text)
    state_db_text = state_db.group(1).strip() if state_db else ""
    scan_db = ", ".join(scan.database_hints) if scan.database_hints else "none"
    if state_db_text and scan_db != "none" and state_db_text != scan_db:
        if not all(x in state_db_text for x in scan.database_hints):
            conflicts.append((f"State says database: {state_db_text}", f"Repository says: {scan_db}"))

    # README contradiction check
    readme = root / "README.md"
    if readme.exists():
        try:
            rtext = readme.read_text(encoding='utf-8', errors='ignore').lower()
            if "postgresql" in rtext and "sqlite" in scan_db:
                conflicts.append(("README says PostgreSQL", f"code uses {scan_db}"))
            if "sqlite" in rtext and "postgresql" in scan_db:
                conflicts.append(("README says SQLite", f"code uses {scan_db}"))
        except:
            pass

    if conflicts:
        print("STATE CONFLICT DETECTED")
        print()
        for state_says, repo_says in conflicts:
            print(f"State says:")
            print(f"  {frame_data(state_says)}")
            print(f"Repository says:")
            print(f"  {frame_data(repo_says)}")
            print()
        print("Resolution:")
        print("Repository state wins.")
        print("State file should be updated. Run `/vibe-check sync`.")
    else:
        print("State vs repository: CONSISTENT")
        print("No contradictions detected. State is still accurate.")
        if not valid:
            print("But integrity check failed - re-sync recommended.")
    print()
    print("Don't Break (from state):")
    # extract don't break
    m = re.search(r'## Don\'t Break\s*(.+?)\n## ', state_text, re.DOTALL)
    if m:
        for line in m.group(1).strip().splitlines():
            if line.strip():
                print(frame_data(line.strip()))
    else:
        print("(none)")
    print()
    print("Next steps: `/vibe-check sync` to refresh, `/vibe-check audit` for health")

# ---------------- MAIN ----------------
def main():
    parser = argparse.ArgumentParser(prog="vibe-check", description="Vibe Check - Architectural Conscience")
    parser.add_argument("command", nargs="?", default="health", help="health|forecast|debt|sync|audit|diff|recover")
    parser.add_argument("--request", "-r", type=str, default="", help="Requested change for forecast")
    parser.add_argument("--root", type=str, default=".", help="Project root")
    parser.add_argument("--add-debt", action="store_true", help="Add debt entry (for testing)")
    parser.add_argument("--title", type=str, default="")
    parser.add_argument("--location", type=str, default="")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing (for sync)")

    args, unknown = parser.parse_known_args()
    # handle /vibe-check style: command may be like "forecast" with extra words as request
    # unknown captures remainder for forecast natural language
    cmd = args.command.lower().strip()
    # normalize /vibe-check variants
    cmd = cmd.replace("/vibe-check","").strip()
    if cmd.startswith("/"):
        cmd = cmd[1:]
    if cmd == "":
        cmd = "health"
    # If command includes spaces due to natural language invocation, extract first word
    # e.g., "forecast --request 'hardcode login'" is handled, but if user typed "/vibe-check forecast Just hardcode the login", unknown will have words
    root = Path(args.root).resolve()
    # alternative: find project root
    try:
        proj_root = find_project_root(root)
        if proj_root != root:
            # if we are inside vibe-check itself, stay
            if (proj_root / "vibe-check").exists():
                pass
            else:
                root = proj_root
    except:
        pass

    # Handle forecast with natural language: if unknown contains text and command is forecast, join as request
    if cmd == "forecast" and unknown:
        extra = " ".join(unknown).strip()
        # if extra doesn't start with -, treat as request
        if extra and not extra.startswith("-"):
            if args.request:
                args.request = args.request + " " + extra
            else:
                args.request = extra
        elif extra.startswith("--request"):
            # already parsed? ignore
            pass

    # Also handle debt subcommands
    if cmd in ["health", "check", ""]:
        cmd_health(root)
    elif cmd == "forecast":
        # if request empty but unknown has something
        req = args.request
        if not req and unknown:
            # try to join unknown as request
            req = " ".join([u for u in unknown if not u.startswith("-")])
        cmd_forecast(root, req)
    elif cmd == "debt":
        if args.add_debt and args.title:
            nid = add_debt_entry(root, args.title, args.location or "unknown", "auto-added", "Medium", "future", "2–4 hours")
            print(f"Added {nid}")
        else:
            cmd_debt(root)
    elif cmd == "sync":
        cmd_sync(root, dry_run=getattr(args, 'dry_run', False))
    elif cmd == "audit":
        cmd_audit(root)
    elif cmd == "diff":
        cmd_diff(root)
    elif cmd == "recover":
        cmd_recover(root)
    else:
        print(f"Unknown command: {cmd}")
        print("Available: /vibe-check, /vibe-check forecast, /vibe-check debt, /vibe-check sync, /vibe-check audit, /vibe-check diff, /vibe-check recover")
        sys.exit(1)

if __name__ == "__main__":
    main()
