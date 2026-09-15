import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from vibe_check import forecast_regret_score
from utils import scan_repo

def make_scan(root):
    return scan_repo(root, fast=True)

def test_low_risk_change():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "README.md").write_text("# App")
        (root / "src").mkdir()
        (root / "src" / "utils.js").write_text("export function formatDate(d){return d.toISOString()}")
        scan = make_scan(root)
        score, level, ben, rework, surfaces, risks = forecast_regret_score("Rename utils.formatDate to formatISO", scan)
        assert score <= 40, f"low risk should be <=40 got {score}"
        assert level in ["NEGLIGIBLE","LOW"]

def test_medium_risk_change():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src" / "api.js").write_text("fetch()")
        scan = make_scan(root)
        score, level, ben, rework, surfaces, risks = forecast_regret_score("Skip validation for address field for MVP", scan)
        assert 20 <= score <= 70, f"medium should be 20-70 got {score}"

def test_high_risk_architectural():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "lib").mkdir()
        (root / "lib" / "auth.js").write_text("auth")
        scan = make_scan(root)
        score, level, ben, rework, surfaces, risks = forecast_regret_score("Just hardcode the login for now.", scan)
        assert score >= 60, f"hardcode login should be high >=60 got {score}"
        assert level in ["HIGH","SEVERE"]
        # ensure migration surface mentions auth
        assert any("auth" in s.lower() for s in surfaces)

def test_payment_risk_severe():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "app.js").write_text("")
        scan = make_scan(root)
        score, *_ = forecast_regret_score("Hardcode payment amount for quick demo", scan)
        assert score >= 70

def run_all():
    test_low_risk_change(); print("✓ test_low_risk_change")
    test_medium_risk_change(); print("✓ test_medium_risk_change")
    test_high_risk_architectural(); print("✓ test_high_risk_architectural")
    test_payment_risk_severe(); print("✓ test_payment_risk_severe")

if __name__ == "__main__":
    run_all()
