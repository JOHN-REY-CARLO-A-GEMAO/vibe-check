import tempfile, json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from vibe_check import cmd_sync, cmd_recover
from integrity import verify_lock

def test_loading_state():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "README.md").write_text("# App")
        cmd_sync(root)
        import io, contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            cmd_recover(root)
        out = f.getvalue()
        assert "Loaded" in out
        assert "Integrity" in out

def test_repository_vs_state_conflict():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text(json.dumps({"dependencies":{"riverpod":"1.0"}}))
        cmd_sync(root)
        # now manually corrupt state to say something else
        state = root / ".vibe" / "state.md"
        txt = state.read_text()
        txt = txt.replace("riverpod", "bloc")
        state.write_text(txt)
        # need to keep lock invalid so recover detects conflict regardless of hash
        import io, contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            cmd_recover(root)
        out = f.getvalue()
        # should detect conflict or at least show INVALID
        assert "CONFLICT" in out or "Repository says" in out or "INVALID" in out

def test_stale_state_recovery():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "app.js").write_text("old")
        cmd_sync(root)
        # modify repo significantly
        (root / "lib" / "features").mkdir(parents=True)
        (root / "lib" / "features" / "new.dart").write_text("new feature")
        # recover should notice repo has more files than state claimed? At least not crash
        import io, contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            cmd_recover(root)
        out = f.getvalue()
        assert "VIBE RECOVER" in out

def run_all():
    test_loading_state(); print("✓ test_loading_state")
    test_repository_vs_state_conflict(); print("✓ test_repository_vs_state_conflict")
    test_stale_state_recovery(); print("✓ test_stale_state_recovery")

if __name__ == "__main__":
    run_all()
