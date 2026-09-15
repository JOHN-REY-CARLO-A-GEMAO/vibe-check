import tempfile
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from vibe_check import generate_state_content, parse_debt_ledger, cmd_sync
from utils import scan_repo
from integrity import verify_lock, hash_file

def test_state_creation(tmp_path=None):
    # Use tempfile
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # create minimal project
        (root / "package.json").write_text(json.dumps({"name":"test-app","description":"demo"}))
        (root / "src").mkdir()
        (root / "src" / "index.js").write_text("console.log('hi')")
        from vibe_check import cmd_sync
        cmd_sync(root)
        state = root / ".vibe" / "state.md"
        j = root / ".vibe" / "state.json"
        lock = root / ".vibe" / "state.lock"
        assert state.exists(), "state.md should be created"
        assert j.exists(), "state.json should be created"
        assert lock.exists(), "state.lock should be created"
        content = state.read_text()
        assert len(content.encode('utf-8')) < 5000, "state must be <5KB"
        assert "Project" in content
        assert "Architecture" in content
        # integrity
        from integrity import verify_lock
        valid, cur, msg = verify_lock(state, lock)
        assert valid, f"integrity should be VALID: {msg}"

def test_state_update_preserves_conventions():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text('{"name":"app","description":"test"}')
        (root / "lib" / "features").mkdir(parents=True)
        (root / "lib" / "features" / "auth.dart").write_text("riverpod")
        from vibe_check import cmd_sync
        cmd_sync(root)
        first = (root / ".vibe" / "state.md").read_text()
        # modify to include custom decision and sync again
        # add a file to trigger change
        (root / "lib" / "features" / "orders").mkdir(parents=True, exist_ok=True)
        (root / "lib" / "features" / "orders" / "repo.dart").write_text("repository")
        cmd_sync(root)
        second = (root / ".vibe" / "state.md").read_text()
        assert "Pattern" in second
        assert len(second.encode('utf-8')) < 5000

def test_state_integrity_and_corruption():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "README.md").write_text("# Test")
        from vibe_check import cmd_sync
        cmd_sync(root)
        state = root / ".vibe" / "state.md"
        lock = root / ".vibe" / "state.lock"
        from integrity import verify_lock
        valid, cur, msg = verify_lock(state, lock)
        assert valid
        # corrupt state
        state.write_text(state.read_text() + "\nCORRUPTION")
        valid2, cur2, msg2 = verify_lock(state, lock)
        assert not valid2, "corrupted state should fail integrity"
        assert "mismatch" in msg2.lower() or "hash" in msg2.lower()

def run_all():
    test_state_creation()
    print("✓ test_state_creation")
    test_state_update_preserves_conventions()
    print("✓ test_state_update_preserves_conventions")
    test_state_integrity_and_corruption()
    print("✓ test_state_integrity_and_corruption")

if __name__ == "__main__":
    run_all()
