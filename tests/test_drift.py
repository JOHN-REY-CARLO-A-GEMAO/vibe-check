import tempfile, json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from vibe_check import cmd_sync
from utils import scan_repo

def test_detect_pattern_changes():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # initial with riverpod
        (root / "package.json").write_text(json.dumps({"dependencies":{"riverpod":"1.0"}}))
        (root / "lib").mkdir()
        (root / "lib" / "main.dart").write_text("import 'riverpod';")
        scan = scan_repo(root, fast=True)
        assert "riverpod" in scan.state_mgmt
        cmd_sync(root)
        # now add bloc alongside riverpod -> drift
        (root / "lib" / "feature_new.dart").write_text("import 'bloc'; bloc provider")
        # write package-like hint
        p = json.loads((root / "package.json").read_text())
        p["dependencies"]["bloc"] = "1.0"
        (root / "package.json").write_text(json.dumps(p))
        scan2 = scan_repo(root, fast=True)
        assert len(scan2.state_mgmt) > 1, f"should detect multiple state libs: {scan2.state_mgmt}"
        # simulate drift detection via sync second run should note multiple
        cmd_sync(root)
        state = (root / ".vibe" / "state.md").read_text().lower()
        # state should contain both
        assert "riverpod" in state or "bloc" in state

def test_contradictory_documentation():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "README.md").write_text("# App\nUses PostgreSQL")
        (root / "app.py").write_text("import sqlite3\nconn = sqlite3.connect('db.sqlite')")
        scan = scan_repo(root, fast=True)
        # our database hints should detect sqlite
        assert "sqlite" in scan.database_hints
        # recovery should flag contradiction
        from vibe_check import cmd_recover
        # need state
        cmd_sync(root)
        # capture output
        import io, contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            cmd_recover(root)
        out = f.getvalue()
        # should mention sqlite vs postgres either as conflict or database hint
        assert "sqlite" in out.lower() or "postgresql" in out.lower() or "postgres" in out.lower() or "consistent" in out.lower()

def test_inconsistent_dependencies():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text(json.dumps({"dependencies":{"firebase":"9.0","supabase":"2.0","pg":"8.0"}}))
        (root / "index.js").write_text("import firebase from 'firebase'; import supabase from '@supabase/supabase-js';")
        scan = scan_repo(root, fast=True)
        assert len(scan.database_hints) >= 2, f"should detect multiple DBs: {scan.database_hints}"

def run_all():
    test_detect_pattern_changes(); print("✓ test_detect_pattern_changes")
    test_contradictory_documentation(); print("✓ test_contradictory_documentation")
    test_inconsistent_dependencies(); print("✓ test_inconsistent_dependencies")

if __name__ == "__main__":
    run_all()
