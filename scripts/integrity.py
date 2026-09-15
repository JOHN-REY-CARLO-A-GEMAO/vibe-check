"""
Integrity helper for .vibe/state.md
Provides SHA-256 hash for change detection (not security)
"""
import hashlib
from pathlib import Path
from datetime import datetime, timezone
import json

def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def write_lock(state_path: Path, lock_path: Path = None):
    if lock_path is None:
        lock_path = state_path.parent / "state.lock"
    state_hash = hash_file(state_path)
    now = datetime.now(timezone.utc).isoformat()
    content = f"algorithm: SHA-256\nstate_hash: {state_hash}\nupdated: {now}\n"
    lock_path.write_text(content, encoding='utf-8')
    return state_hash

def read_lock(lock_path: Path) -> dict:
    if not lock_path.exists():
        return {}
    data = {}
    try:
        for line in lock_path.read_text(encoding='utf-8').splitlines():
            if ":" in line:
                k,v = line.split(":",1)
                data[k.strip()] = v.strip()
    except:
        return {}
    return data

def verify_lock(state_path: Path, lock_path: Path = None) -> tuple[bool, str, str]:
    if lock_path is None:
        lock_path = state_path.parent / "state.lock"
    if not state_path.exists():
        return False, "", "state.md missing"
    if not lock_path.exists():
        return False, "", "lock missing - run /vibe-check sync"
    current_hash = hash_file(state_path)
    lock_data = read_lock(lock_path)
    expected = lock_data.get("state_hash", "")
    if not expected:
        return False, current_hash, "lock corrupted"
    if current_hash == expected:
        return True, current_hash, "VALID"
    else:
        return False, current_hash, f"hash mismatch (expected {expected[:8]}..., got {current_hash[:8]}...)"

def verify_state_integrity(vibe_dir: Path) -> tuple[bool, str]:
    state_path = vibe_dir / "state.md"
    lock_path = vibe_dir / "state.lock"
    valid, cur, msg = verify_lock(state_path, lock_path)
    return valid, msg
