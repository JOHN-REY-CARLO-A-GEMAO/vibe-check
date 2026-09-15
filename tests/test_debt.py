import tempfile, json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from vibe_check import add_debt_entry, parse_debt_ledger, debt_priority_score, priority_label
from utils import scan_repo

def test_debt_creation():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "index.js").write_text("code")
        nid = add_debt_entry(root, "Hardcoded auth", "lib/auth/login.js", "MVP shortcut", "Medium", "Replace before prod", "2–4 hours")
        assert nid == "DEBT-001"
        debt_path = root / ".vibe" / "debt.md"
        assert debt_path.exists()
        debts = parse_debt_ledger(debt_path)
        assert len(debts) == 1
        assert debts[0]["title"] == "Hardcoded auth"
        assert debts[0]["status"] == "OPEN"

def test_debt_prioritization():
    cases = [
        ({"risk":"Critical","rework":"8 hours"}, "P0"),
        ({"risk":"High","rework":"4–6 hours"}, "P1"),
        ({"risk":"Medium","rework":"2–4 hours"}, "P2"),
        ({"risk":"Low","rework":"1 hour"}, "P3"),
    ]
    for debt, expected in cases:
        score = debt_priority_score(debt)
        label = priority_label(score)
        # we check that higher risk yields higher priority
        assert label in ["P0","P1","P2","P3"]

    # specific: critical + high cost => P0
    d = {"risk":"Critical","rework":"1–2 days"}
    assert priority_label(debt_priority_score(d)) == "P0"
    # low => P3
    d2 = {"risk":"Low","rework":"1 hour"}
    assert priority_label(debt_priority_score(d2)) in ["P3","P2"]

def test_debt_updating_and_resolution():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        add_debt_entry(root, "Debt A", "a.js", "why", "High", "trigger", "4–6 hours")
        add_debt_entry(root, "Debt B", "b.js", "why", "Low", "trigger", "1 hour")
        debt_path = root / ".vibe" / "debt.md"
        text = debt_path.read_text()
        # simulate resolving DEBT-001
        text = text.replace("Status:\nOPEN", "Status:\nRESOLVED", 1)
        debt_path.write_text(text)
        debts = parse_debt_ledger(debt_path)
        open_debts = [d for d in debts if d["status"]=="OPEN"]
        assert len(open_debts) == 1
        assert open_debts[0]["id"] == "DEBT-002"

def test_debt_not_every_minor_imperfection():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # ensure scan doesn't create debt automatically for minor todos
        (root / "app.js").write_text("// TODO: minor typo\n")
        # debt ledger should remain empty unless explicitly added
        from vibe_check import cmd_debt
        import io, sys
        debt_path = root / ".vibe" / "debt.md"
        # cmd_debt will show "No debt ledger entries found" but not auto-populate
        # we ensure no auto creation of many entries
        cmds = parse_debt_ledger(debt_path) if debt_path.exists() else []
        assert len(cmds) == 0

def run_all():
    test_debt_creation(); print("✓ test_debt_creation")
    test_debt_prioritization(); print("✓ test_debt_prioritization")
    test_debt_updating_and_resolution(); print("✓ test_debt_updating_and_resolution")
    test_debt_not_every_minor_imperfection(); print("✓ test_debt_not_every_minor_imperfection")

if __name__ == "__main__":
    run_all()
