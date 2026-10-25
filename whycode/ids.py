"""Graph node ids. Every id is "<repo>#<kind>:<key>", e.g. "psf/requests#pr:1565".

The Repo node itself uses the bare repo, "psf/requests". Nothing else should build ids by hand.
"""

import hashlib
import re

KINDS = frozenset({"pr", "issue", "commit", "dec", "ev", "user", "file", "fn", "mod", "cfg"})

_REPO_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*/[a-z0-9_.-]+$")


def normalize_repo(repo: str) -> str:
    """Return "owner/name" lowercased (GitHub names are case-insensitive). Raises on bad input."""
    norm = repo.strip().lower()
    if not _REPO_RE.match(norm):
        raise ValueError(f"repo must look like 'owner/name', got {repo!r}")
    return norm


def make_id(repo: str, kind: str, key: str | int) -> str:
    """Build a repo-prefixed node id. The same input always gives the same id."""
    if kind not in KINDS:
        raise ValueError(f"unknown id kind {kind!r}; expected one of {sorted(KINDS)}")
    key_str = str(key).strip()
    if not key_str or any(c in key_str for c in "\r\n\t"):
        raise ValueError(f"id key must be a non-empty single-line value, got {key!r}")
    if kind == "commit":
        key_str = key_str.lower()
    return f"{normalize_repo(repo)}#{kind}:{key_str}"


def repo_id(repo: str) -> str:
    return normalize_repo(repo)


def decision_key(source_id: str, prompt_version: str, index: int) -> str:
    """Stable decision key from where it came from, never from LLM-written text."""
    if index < 0:
        raise ValueError("index must be >= 0")
    digest = hashlib.sha256(f"{source_id}|{prompt_version}|{index}".encode()).hexdigest()
    return digest[:16]


def decision_id(repo: str, source_id: str, prompt_version: str, index: int) -> str:
    return make_id(repo, "dec", decision_key(source_id, prompt_version, index))
