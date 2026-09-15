# vibe-check: allow-large-file - scanner is intentionally consolidated for zero-dependency portability
"""
Vibe Check - Shared utilities for repository inspection
Fast, dependency-free scanner for vibe-coded projects
"""
import os
import re
import json
import glob
import hashlib
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

# Skill installation directory — dynamically determined from this file's location
# This makes the skill installation-independent (works from ~/.agents/skills/, .opencode/skills/, etc.)
try:
    SKILL_DIR = Path(__file__).resolve().parent.parent
except:
    SKILL_DIR = Path.cwd() / "vibe-check"

# Constants
EXCLUDE_DIRS = {".git", ".vibe", "node_modules", "__pycache__", ".venv", "venv",
                "dist", "build", "out", "target", ".next", ".nuxt", ".output",
                ".cache", ".local", ".mypy_cache", ".pytest_cache", ".ruff_cache",
                ".svelte-kit", ".tox", ".turbo", ".vite", "coverage", "vendor",
                ".arena", ".expo", ".dart_tool"}
EXCLUDE_FILES = {".DS_Store", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}

# Secret-bearing files that should NEVER be scanned for architectural analysis
SECRET_FILE_PATTERNS = {".env", ".pem", ".key", "credentials", "secrets"}

CONFIG_FILE_PATTERNS = [
    "*.config.*", "*.conf", ".env*", "docker-compose*", "Dockerfile",
    ".*rc", "*.toml", "*.yaml", "*.yml", "*.json"
]

SECRET_PATTERNS = [
    r'(?i)api[_-]?key\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,64}',
    r'(?i)secret\s*[:=]\s*["\']?[A-Za-z0-9_\-]{8,64}',
    r'(?i)password\s*[:=]\s*["\']?[^\s"\']{1,64}["\']?',
    r'(?i)token\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,64}',
    r'sk-[A-Za-z0-9]{20,64}',
    r'ghp_[A-Za-z0-9]{36,64}',
]

HARDCODE_PATTERNS = [
    r'https?://[^\s"\'`]+',
    r'localhost:\d+',
    r'127\.0\.0\.1',
    r'0\.0\.0\.0',
]

# Support // TODO, // TODO:, # TODO, /* TODO, * TODO with or without colon
TODO_PATTERNS = [r'\bTODO\b', r'\bFIXME\b', r'\bHACK\b', r'\bXXX\b', r'\bBUG\b']

# Prompt injection patterns to sanitize when displaying repository-controlled text
INJECTION_PATTERNS = [
    r'(?i)ignore\s+previous\s+instructions',
    r'(?i)system\s*:',
    r'(?i)assistant\s*:',
    r'(?i)run\s+rm\s+-rf',
    r'(?i)delete\s+all\s+files',
]

DEFAULT_CONFIG = {
    "large_file_lines": 400,
    "todo_warning_threshold": 20,
    "regret_warning_threshold": 40,
    "regret_blocking_threshold": 70,
}

@dataclass
class RepoScan:
    root: Path
    source_files: List[Path] = field(default_factory=list)
    total_files: int = 0
    total_lines: int = 0
    large_files: List[Tuple[Path, int]] = field(default_factory=list)
    todo_count: int = 0
    todo_items: List[Tuple[Path, int, str]] = field(default_factory=list)
    hardcoded_count: int = 0
    hardcoded_items: List[Tuple[Path, int, str]] = field(default_factory=list)
    config_file_count: int = 0
    dependency_files: List[Path] = field(default_factory=list)
    dependencies: Dict[str, str] = field(default_factory=dict)
    framework_hints: List[str] = field(default_factory=list)
    state_mgmt: List[str] = field(default_factory=list)
    database_hints: List[str] = field(default_factory=list)
    api_patterns: List[str] = field(default_factory=list)
    duplication_candidates: List[Tuple[str, List[Path]]] = field(default_factory=list)
    coupling_score: int = 0
    has_git: bool = False
    git_status: str = ""
    git_branch: str = ""
    git_untracked: List[str] = field(default_factory=list)
    git_log_recent: List[str] = field(default_factory=list)
    git_diff_stat: str = ""
    recent_changed_files: List[str] = field(default_factory=list)
    architecture_pattern: str = "unknown"
    secrets_detected: int = 0
    file_types: Dict[str, int] = field(default_factory=dict)
    config: Dict = field(default_factory=dict)


def load_config(root: Path) -> Dict:
    """Load optional .vibe/config.json with defaults"""
    cfg = DEFAULT_CONFIG.copy()
    config_path = root / ".vibe" / "config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding='utf-8', errors='ignore'))
            for k in DEFAULT_CONFIG:
                if k in data:
                    # Validate type is int
                    try:
                        cfg[k] = int(data[k])
                    except:
                        pass
        except:
            pass
    return cfg

def sanitize_for_state(text: str) -> str:
    """Remove secrets before persisting to state/debt/decisions"""
    sanitized = text
    for pat in SECRET_PATTERNS:
        sanitized = re.sub(pat, "[REDACTED]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+', r'\1=[REDACTED]', sanitized)
    return sanitized

def sanitize_output(text: str) -> str:
    """Sanitize repository-controlled text before displaying — prevents prompt injection from being treated as instructions"""
    sanitized = sanitize_for_state(text)
    for pat in INJECTION_PATTERNS:
        sanitized = re.sub(pat, "[FILTERED]", sanitized, flags=re.IGNORECASE)
    # Frame as data: remove leading instruction-like markers
    # Ensure output is clearly data, not command
    return sanitized

def is_skill_file(path: Path) -> bool:
    """Precisely check if path is inside the skill installation directory"""
    try:
        # Use SKILL_DIR determined from __file__
        return path.resolve().is_relative_to(SKILL_DIR.resolve())
    except:
        try:
            return SKILL_DIR.resolve() in path.resolve().parents or path.resolve() == SKILL_DIR.resolve()
        except:
            return "vibe-check" in path.parts and (SKILL_DIR / "SKILL.md").exists() and str(path).startswith(str(SKILL_DIR))

def is_secret_file(path: Path) -> bool:
    """Check if file is secret-bearing and should be excluded from architectural scan"""
    name = path.name
    # Exact matches and patterns
    if name == ".env" or name.startswith(".env."):
        return True
    for pat in SECRET_FILE_PATTERNS:
        if pat in name:
            return True
    if path.suffix in {".pem", ".key"}:
        return True
    return False

def find_project_root(start: Path = None) -> Path:
    if start is None:
        start = Path.cwd()
    cur = start.resolve()
    for parent in [cur] + list(cur.parents):
        if (parent / ".git").exists():
            return parent
        if (parent / "package.json").exists() or (parent / "pyproject.toml").exists() or (parent / "pubspec.yaml").exists() or (parent / "go.mod").exists():
            return parent
    return cur

def is_excluded(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except:
        rel = path
    for part in rel.parts:
        if part in EXCLUDE_DIRS:
            return True
    if path.name in EXCLUDE_FILES:
        return True
    if is_secret_file(path):
        return True
    return False

def get_source_files(root: Path, limit: int = 800) -> List[Path]:
    files = []
    exts = {".js", ".ts", ".jsx", ".tsx", ".py", ".dart", ".go", ".java", ".kt",
            ".rb", ".php", ".rs", ".swift", ".vue", ".svelte", ".json", ".yaml", ".yml",
            ".toml", ".md", ".css", ".scss", ".html"}
    # Precise skill exclusion: only exclude the actual skill installation directory if it is inside host root
    skill_inside_host = False
    try:
        skill_inside_host = SKILL_DIR.resolve().is_relative_to(root.resolve())
    except:
        try:
            skill_inside_host = str(SKILL_DIR.resolve()).startswith(str(root.resolve()))
        except:
            skill_inside_host = False
    for p in root.rglob("*"):
        if len(files) >= limit:
            break
        if p.is_file():
            if is_excluded(p, root):
                continue
            # Precisely exclude skill installation directory when it is inside host
            if skill_inside_host:
                try:
                    if p.resolve().is_relative_to(SKILL_DIR.resolve()):
                        continue
                except:
                    if str(p.resolve()).startswith(str(SKILL_DIR.resolve())):
                        continue
            if is_secret_file(p):
                continue
            if p.suffix in exts or p.name in {"Dockerfile", "Makefile"}:
                files.append(p)
            if p.parent == root and p.suffix in {".json", ".js", ".ts", ".py", ".yaml", ".yml", ".env"}:
                if p not in files and not is_secret_file(p):
                    files.append(p)
    return files

def count_lines(path: Path) -> int:
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return sum(1 for _ in f)
    except:
        return 0

def scan_todos_and_hardcodes(files: List[Path]) -> Tuple[int, List, int, List, int]:
    todo_count = 0
    todo_items = []
    hardcoded_count = 0
    hardcoded_items = []
    secrets = 0
    todo_re = re.compile("|".join(TODO_PATTERNS))
    hard_re = re.compile("|".join(HARDCODE_PATTERNS))
    secret_res = [re.compile(p) for p in SECRET_PATTERNS]

    for f in files:
        if f.suffix in {".md",".json",".yaml",".yml",".toml"}:
            continue
        if "tests" in str(f) or "test_" in f.name or f.name.startswith("test"):
            continue
        if is_secret_file(f):
            continue
        try:
            with open(f, 'r', encoding='utf-8', errors='ignore') as fh:
                for idx, line in enumerate(fh, 1):
                    if "TODO_PATTERNS" in line or "HARDCODE_PATTERNS" in line or "SECRET_PATTERNS" in line:
                        continue
                    if "todo_count" in line.lower() or "TODO accumulation" in line or "TODO/FIXME" in line or "Add a TODO" in line:
                        continue
                    if "TODOs," in line or "TODOs." in line:
                        continue
                    if "comment marker" in line.lower() or "only count todo" in line.lower() or "e.g., # todo" in line.lower():
                        continue
                    # TODO detection: support // TODO, // TODO:, # TODO, /* TODO, * TODO with or without colon
                    if todo_re.search(line):
                        # Check for comment marker to avoid counting strings that merely mention TODO
                        if re.search(r'(#|//|/\*|\*)\s*(TODO|FIXME|HACK|XXX|BUG)\b', line):
                            todo_count += 1
                            if len(todo_items) < 50:
                                # Sanitize before storing
                                safe = sanitize_output(line.strip()[:120])
                                todo_items.append((f, idx, safe))
                        elif re.search(r'\b(TODO|FIXME|HACK)\b\s*:', line):
                            todo_count += 1
                            if len(todo_items) < 50:
                                safe = sanitize_output(line.strip()[:120])
                                todo_items.append((f, idx, safe))
                            continue
                        else:
                            continue
                    if hard_re.search(line):
                        hardcoded_count += 1
                        if len(hardcoded_items) < 50:
                            safe = sanitize_output(line.strip()[:120])
                            hardcoded_items.append((f, idx, safe))
                    for sr in secret_res:
                        if sr.search(line):
                            if "SECRET_PATTERNS" in line or "api[_-]?key" in line:
                                continue
                            secrets += 1
                            break
                    if todo_count > 500 and hardcoded_count > 500:
                        break
        except:
            continue
        if len(files) > 200 and todo_count > 100:
            pass
    return todo_count, todo_items, hardcoded_count, hardcoded_items, secrets

def detect_dependencies(root: Path) -> Tuple[List[Path], Dict[str, str], List[str]]:
    dep_files = []
    deps = {}
    hints = []
    candidates = [
        root / "package.json",
        root / "requirements.txt",
        root / "pyproject.toml",
        root / "pubspec.yaml",
        root / "go.mod",
        root / "Cargo.toml",
        root / "Gemfile",
    ]
    for cf in candidates:
        if cf.exists():
            dep_files.append(cf)
            hints.append(cf.name)
            try:
                if cf.name == "package.json":
                    data = json.loads(cf.read_text(encoding='utf-8', errors='ignore'))
                    for k in ["dependencies", "devDependencies"]:
                        if k in data:
                            deps.update(data[k])
                    if "react" in deps or "next" in str(data):
                        hints.append("react/next")
                    if "vue" in deps:
                        hints.append("vue")
                    if "svelte" in deps:
                        hints.append("svelte")
                elif cf.name == "requirements.txt":
                    for line in cf.read_text(errors='ignore').splitlines():
                        line=line.strip()
                        if line and not line.startswith("#"):
                            deps[line.split("==")[0].split(">=")[0].strip()] = line
                elif cf.name == "pubspec.yaml":
                    hints.append("flutter/dart")
                elif cf.name == "pyproject.toml":
                    hints.append("python")
                elif cf.name == "go.mod":
                    hints.append("go")
            except:
                pass
    for lf in root.glob("*lock*"):
        if lf.is_file() and lf not in dep_files:
            dep_files.append(lf)
    return dep_files, deps, hints

def detect_state_management(files: List[Path], deps: Dict[str,str], root: Path) -> List[str]:
    found = set()
    dep_str = " ".join(deps.keys()).lower() + " " + " ".join(deps.values()).lower()
    checks = {
        "riverpod": "riverpod",
        "bloc": "bloc",
        "provider": "provider",
        "redux": "redux",
        "zustand": "zustand",
        "mobx": "mobx",
        "pinia": "pinia",
        "vuex": "vuex",
        "recoil": "recoil",
        "jotai": "jotai",
        "ngrx": "ngrx",
    }
    for k,v in checks.items():
        if k in dep_str:
            found.add(v)
    import_patterns = {
        "riverpod": re.compile(r'(import|from|require).*\briverpod\b', re.IGNORECASE),
        "bloc": re.compile(r'(import|from|require).*\bbloc\b', re.IGNORECASE),
        "provider": re.compile(r'(import|from|require).*\bprovider\b', re.IGNORECASE),
        "redux": re.compile(r'(import|from|require).*\b(redux|react-redux)\b', re.IGNORECASE),
        "zustand": re.compile(r'(import|from|require).*\bzustand\b', re.IGNORECASE),
        "mobx": re.compile(r'(import|from|require).*\bmobx\b', re.IGNORECASE),
        "pinia": re.compile(r'(import|from|require).*\bpinia\b', re.IGNORECASE),
        "vuex": re.compile(r'(import|from|require).*\bvuex\b', re.IGNORECASE),
        "recoil": re.compile(r'(import|from|require).*\brecoil\b', re.IGNORECASE),
        "jotai": re.compile(r'(import|from|require).*\bjotai\b', re.IGNORECASE),
        "ngrx": re.compile(r'(import|from|require).*\bngrx\b', re.IGNORECASE),
    }
    filtered = []
    for f in files[:300]:
        try:
            if is_skill_file(f):
                continue
            if f.suffix in {".md"}:
                continue
            if "tests" in str(f) or "test_" in f.name:
                continue
            if is_secret_file(f):
                continue
        except:
            pass
        filtered.append(f)
    for f in filtered:
        try:
            text = f.read_text(encoding='utf-8', errors='ignore')[:6000]
            text_lower = text.lower()
            for k, pat in import_patterns.items():
                if pat.search(text):
                    found.add(k)
            if "usestate" in text_lower or "setstate" in text_lower:
                if any(x in text_lower for x in ["import", "from", "require"]):
                    found.add("local-state")
        except:
            continue
    return sorted(found)

def detect_database(files: List[Path], deps: Dict[str,str]) -> List[str]:
    found = set()
    dep_str = " ".join(deps.keys()).lower()
    db_map = {
        "postgres": "postgresql",
        "pg": "postgresql",
        "sqlite": "sqlite",
        "mysql": "mysql",
        "mongodb": "mongodb",
        "mongoose": "mongodb",
        "firebase": "firebase",
        "firestore": "firebase",
        "supabase": "supabase",
        "prisma": "prisma",
        "drizzle": "drizzle",
        "typeorm": "typeorm",
        "sequelize": "sequelize",
        "redis": "redis",
    }
    for k,v in db_map.items():
        if k in dep_str:
            found.add(v)
    filtered = []
    for f in files[:300]:
        try:
            if is_skill_file(f):
                continue
            if f.suffix == ".md":
                continue
            if "tests" in str(f) or "test_" in f.name:
                continue
            if is_secret_file(f):
                continue
        except:
            pass
        filtered.append(f)
    for f in filtered:
        try:
            t = f.read_text(encoding='utf-8', errors='ignore')[:6000]
            tl = t.lower()
            for k,v in db_map.items():
                if k in tl:
                    if re.search(r'(import|from|require).*' + re.escape(k), tl):
                        found.add(v)
                    if k in ["firebase","supabase"] and (k+".initialize" in tl or k+".create" in tl or "client" in tl):
                        if re.search(r'\b' + re.escape(k) + r'\b', tl) and ("import" in tl or "require" in tl):
                            found.add(v)
        except:
            continue
    for f in files:
        if is_skill_file(f):
            continue
        if is_secret_file(f):
            continue
        n = f.name.lower()
        if "firebase" in n:
            found.add("firebase")
        if "supabase" in n:
            found.add("supabase")
    return sorted(found)

def detect_architecture_pattern(root: Path, files: List[Path]) -> str:
    has_features = (root / "lib" / "features").exists() or (root / "src" / "features").exists() or any("feature" in str(p).lower() for p in files[:100])
    has_controllers = sum(1 for p in files if "controller" in p.name.lower()) > 2
    has_services = sum(1 for p in files if "service" in p.name.lower()) > 2
    has_repos = sum(1 for p in files if "repositor" in p.name.lower()) > 1
    if has_features and has_repos:
        return "feature-based + repository"
    if has_features:
        return "feature-based"
    if has_controllers and has_services and has_repos:
        return "layered (controller/service/repository)"
    if has_controllers and has_services:
        return "mvc/service-layer"
    if has_services and has_repos:
        return "service + repository"
    if len(files) < 20:
        return "simple / early-stage"
    return "mixed / evolving"

def detect_api_patterns(files: List[Path]) -> List[str]:
    patterns = set()
    for f in files[:300]:
        if is_skill_file(f) or is_secret_file(f):
            continue
        try:
            t = f.read_text(encoding='utf-8', errors='ignore')[:5000]
            if "fetch(" in t or "axios" in t or "http.get" in t or "http.post" in t:
                patterns.add("fetch/axios")
            if "app.get(" in t or "app.post(" in t or "router." in t:
                patterns.add("express-like routes")
            if "@Get(" in t or "@Post(" in t:
                patterns.add("decorator routes")
            if "graphql" in t.lower():
                patterns.add("graphql")
            if "websocket" in t.lower() or "socket.io" in t.lower():
                patterns.add("websocket")
        except:
            continue
    return sorted(patterns)

def detect_drift_details(files: List[Path], scan) -> List[Tuple[str, str, str]]:
    """Expanded drift detection returning (category, description, confidence)"""
    drifts = []
    # UI directly accessing DB
    ui_db_files = []
    for f in files[:200]:
        if is_skill_file(f) or is_secret_file(f):
            continue
        low = str(f).lower()
        is_ui = any(x in low for x in ["components", "pages", "screens", "widgets", "views"])
        if is_ui:
            try:
                t = f.read_text(encoding='utf-8', errors='ignore')[:4000].lower()
                if any(db in t for db in ["firebase", "supabase", "prisma", "select * from", "collection("]):
                    if "import" in t or "require" in t:
                        ui_db_files.append(f.name)
            except:
                continue
    if ui_db_files:
        drifts.append(("ARCHITECTURE", f"Possible UI directly accessing persistence in {', '.join(ui_db_files[:3])}", "Medium"))
    # Business logic in UI
    biz_in_ui = []
    for f in files[:150]:
        if is_skill_file(f) or is_secret_file(f):
            continue
        low = str(f).lower()
        if "components" in low or "pages" in low:
            try:
                t = f.read_text(encoding='utf-8', errors='ignore')[:4000].lower()
                if "validation" in t or "calculate" in t or "price" in t:
                    if "fetch" in t or "axios" in t or "http" in t:
                        biz_in_ui.append(f.name)
            except:
                continue
    if len(biz_in_ui) > 2:
        drifts.append(("ARCHITECTURE", f"Possible business logic inside UI components ({len(biz_in_ui)} files)", "Low"))
    # API calls scattered
    api_files = sum(1 for f in files[:300] if not is_skill_file(f) and not is_secret_file(f) and "fetch(" in f.read_text(encoding='utf-8', errors='ignore')[:3000])
    if api_files > 10:
        drifts.append(("API", f"Possible API calls scattered through UI ({api_files} files with fetch)", "Medium"))
    # Duplicate validation/models
    val_files = [f for f in files if "validat" in f.name.lower()]
    model_files = [f for f in files if "model" in f.name.lower()]
    if len(val_files) > 3:
        drifts.append(("MAINTAINABILITY", f"Possible duplicate validation ({len(val_files)} validation files)", "Medium"))
    if len(model_files) > 5:
        drifts.append(("DATA", f"Possible duplicate models ({len(model_files)} model files)", "Low"))
    # Technology contradictions will be handled in recover/audit via README vs code
    return drifts

def estimate_coupling(files: List[Path]) -> int:
    total_imports = 0
    count = 0
    for f in files[:200]:
        if is_skill_file(f) or is_secret_file(f):
            continue
        try:
            text = f.read_text(encoding='utf-8', errors='ignore')
            imports = len(re.findall(r'^\s*import\s+', text, re.MULTILINE))
            imports += len(re.findall(r'require\(', text))
            total_imports += imports
            count += 1
        except:
            continue
    avg = total_imports / max(1, count)
    score = min(100, int(avg * 15))
    return score

def find_duplication(files: List[Path]) -> List[Tuple[str, List[Path]]]:
    filtered_files = [f for f in files if "tests" not in str(f) and not f.name.startswith("test_") and not is_skill_file(f) and not is_secret_file(f)]
    files = filtered_files
    from collections import defaultdict, Counter
    name_map = defaultdict(list)
    for f in files:
        name_map[f.name].append(f)
    dups = []
    for name, paths in name_map.items():
        if len(paths) > 1 and not name.startswith(".") and name not in {"index.js", "index.ts", "utils.js"}:
            dups.append((f"duplicate filename: {name}", paths))
    func_map = defaultdict(list)
    func_re = re.compile(r'(function\s+(\w+)|class\s+(\w+)|const\s+(\w+)\s*=\s*\(|def\s+(\w+))')
    for f in files[:200]:
        try:
            text = f.read_text(encoding='utf-8', errors='ignore')
            for m in func_re.finditer(text):
                name = next((g for g in m.groups()[1:] if g), None)
                if name and len(name) > 3:
                    func_map[name].append(f)
        except:
            continue
    for name, paths in func_map.items():
        if len(paths) > 2:
            uniq = list(set(paths))
            if len(uniq) > 2:
                dups.append((f"duplicate symbol: {name}", uniq[:5]))
        if len(dups) > 10:
            break
    return dups[:8]

def get_git_info(root: Path) -> Tuple[bool, str, str, List[str], List[str], str, List[str]]:
    has_git = (root / ".git").exists()
    status = ""
    branch = ""
    untracked = []
    logs = []
    diff_stat = ""
    changed = []
    if not has_git:
        try:
            subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, timeout=3, check=True)
            has_git = True
        except:
            return False, "", "", [], [], "", []
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=5)
        status = r.stdout.strip()[:3000]
        changed = [line[3:].strip() for line in r.stdout.splitlines() if line.strip()][:20]
        untracked = [line[3:].strip() for line in r.stdout.splitlines() if line.startswith("??")][:20]
    except:
        pass
    try:
        r = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True, timeout=5)
        branch = r.stdout.strip()[:100]
        if not branch:
            r2 = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
            branch = r2.stdout.strip()[:100]
    except:
        pass
    try:
        r = subprocess.run(["git", "log", "--oneline", "-10"], cwd=root, capture_output=True, text=True, timeout=5)
        logs = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except:
        pass
    try:
        r = subprocess.run(["git", "diff", "--stat", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
        diff_stat = r.stdout.strip()[:2000]
        if not diff_stat:
            r2 = subprocess.run(["git", "diff", "--stat"], cwd=root, capture_output=True, text=True, timeout=5)
            diff_stat = r2.stdout.strip()[:2000]
        # Include untracked in diff stat if present
        if untracked:
            diff_stat += f"\nUntracked: {', '.join(untracked[:5])}"
    except:
        pass
    return has_git, status, branch, untracked, logs, diff_stat, changed

# Backwards compatibility: older callers expect 5 returns
def get_git_info_compat(root: Path):
    has_git, status, branch, untracked, logs, diff_stat, changed = get_git_info(root)
    return has_git, status, logs, diff_stat, changed

def scan_repo(root: Path = None, fast: bool = True) -> RepoScan:
    if root is None:
        root = find_project_root()
    else:
        root = Path(root).resolve()
    scan = RepoScan(root=root)
    scan.config = load_config(root)
    has_git, status, branch, untracked, logs, diff_stat, changed = get_git_info(root)
    scan.has_git = has_git
    scan.git_status = status
    scan.git_branch = branch
    scan.git_untracked = untracked
    scan.git_log_recent = logs
    scan.git_diff_stat = diff_stat
    scan.recent_changed_files = changed

    files = get_source_files(root, limit= 500 if fast else 1200)
    scan.source_files = files
    scan.total_files = len(files)
    from collections import Counter
    scan.file_types = dict(Counter(p.suffix for p in files))

    total_lines = 0
    large = []
    large_threshold = scan.config.get("large_file_lines", 400)
    for f in files:
        lines = count_lines(f)
        total_lines += lines
        if lines > large_threshold:
            try:
                head = f.read_text(encoding='utf-8', errors='ignore')[:2000]
                if "vibe-check: allow-large" in head or "vibe-check: ignore-large" in head:
                    continue
            except:
                pass
            large.append((f, lines))
    scan.total_lines = total_lines
    scan.large_files = sorted(large, key=lambda x: x[1], reverse=True)[:10]

    config_files = []
    for p in root.rglob("*"):
        if is_excluded(p, root):
            continue
        if p.is_file():
            n = p.name
            if n.endswith((".config.js", ".config.ts", ".config.json")) or n in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"} or n.startswith(".env") or n.endswith(".toml") or (n.endswith((".yaml", ".yml")) and p.parent == root):
                if not is_secret_file(p):
                    config_files.append(p)
    scan.config_file_count = len(config_files[:20])

    dep_files, deps, hints = detect_dependencies(root)
    scan.dependency_files = dep_files
    scan.dependencies = deps
    scan.framework_hints = hints

    scan.state_mgmt = detect_state_management(files, deps, root)
    scan.database_hints = detect_database(files, deps)
    scan.api_patterns = detect_api_patterns(files)
    scan.architecture_pattern = detect_architecture_pattern(root, files)
    scan.coupling_score = estimate_coupling(files)

    todo_c, todo_items, hard_c, hard_items, secrets = scan_todos_and_hardcodes(files)
    scan.todo_count = todo_c
    scan.todo_items = todo_items
    scan.hardcoded_count = hard_c
    scan.hardcoded_items = hard_items
    scan.secrets_detected = secrets

    scan.duplication_candidates = find_duplication(files)

    return scan

def render_bar(percent: int, width: int = 10) -> str:
    filled = int(round(percent / 100 * width))
    empty = width - filled
    return "█" * filled + "░" * empty

def ensure_vibe_dir(root: Path) -> Path:
    vibe = root / ".vibe"
    vibe.mkdir(exist_ok=True)
    gi = vibe / ".gitignore"
    if not gi.exists():
        gi.write_text("# .vibe — Vibe Check state\n# state.lock is tracked for integrity; state.md/state.json are tracked\n# To ignore vibe state entirely, uncomment next line:\n# *\n", encoding='utf-8')
    return vibe
