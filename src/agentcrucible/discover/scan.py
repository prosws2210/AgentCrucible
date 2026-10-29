"""Read-only inventory of a repository: which files to analyse, which to skip, and secret redaction.

Nothing here executes repository code. Secrets are never read (`.env`, key files) and anything that looks like a
credential is redacted before it can reach a snippet, `discovery.json` or the synthesis model.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

LANGS = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go", ".java": "java",
}
CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".toml", ".md", ".sql", ".prisma", ".jsonl", ".prompt", ".prompty",
                   ".j2", ".jinja", ".jinja2", ".txt", ".cfg", ".ini"}
CONFIG_NAMES = {"Dockerfile", "Procfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
                ".env.example", ".env.sample", ".env.template", ".env.dist", "package.json", "pyproject.toml",
                "requirements.txt", "go.mod", "pom.xml", "build.gradle"}

ALWAYS_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
                    ".ruff_cache", "dist", "build", ".next", "out", "target", ".tox", ".idea", ".vscode-test",
                    "site-packages", ".crucible", "coverage", ".turbo", ".cache", "vendor",
                    "agent-tests"}  # what `crucible discover --apply` wrote: generated adapters aren't the user's agents
SECRET_FILE = re.compile(r"(^\.env($|\.(?!example$|sample$|template$|dist$).*)|\.pem$|\.key$|\.p12$|\.pfx$|^id_rsa|"
                         r"^id_ed25519|credentials\.json$|secrets?\.(json|ya?ml|toml)$|\.keystore$)", re.I)
MAX_FILE_BYTES = 1_000_000
MAX_FILES = 25_000

# credential-looking strings: provider key formats, and long values assigned to key/secret/token/password names
_SECRET_PATTERNS = [
    re.compile(r"\b(sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{16,})"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,})\b"),
    re.compile(r"\b(xox[abposr]-[A-Za-z0-9\-]{10,})\b"),
    re.compile(r"\b(AIza[0-9A-Za-z_\-]{30,})\b"),
    re.compile(r"""(?i)((?:api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*["'])([^"'\s]{8,})(["'])"""),
    re.compile(r"(?i)(postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://([^:/\s]+):([^@/\s]+)@"),
]


def redact(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 3 and "://" in pat.pattern:
            out = pat.sub(lambda m: f"{m.group(1)}://{m.group(2)}:***@", out)
        elif pat.groups >= 3:
            out = pat.sub(lambda m: f"{m.group(1)}***{m.group(3)}", out)
        else:
            out = pat.sub("***", out)
    return out


@dataclass
class SourceFile:
    path: Path  # absolute
    rel: str  # posix path relative to the repo root
    language: str | None  # code language, or None for config/docs
    _text: str | None = None

    @property
    def text(self) -> str:
        if self._text is None:
            try:
                self._text = self.path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._text = ""
        return self._text

    def line(self, n: int) -> str:
        lines = self.text.splitlines()
        return lines[n - 1] if 0 < n <= len(lines) else ""

    def snippet(self, line: int, before: int = 0, after: int = 2) -> str:
        lines = self.text.splitlines()
        lo, hi = max(0, line - 1 - before), min(len(lines), line + after)
        return redact("\n".join(lines[lo:hi]))[:600]


@dataclass
class Inventory:
    root: Path
    files: list[SourceFile] = field(default_factory=list)
    skipped: int = 0
    skipped_secret: list[str] = field(default_factory=list)
    skip_reasons: dict[str, int] = field(default_factory=dict)  # why things were left out, for the preview

    def skip(self, reason: str) -> None:
        self.skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def code(self, *languages: str) -> list[SourceFile]:
        return [f for f in self.files if f.language in languages]

    def named(self, *patterns: str) -> list[SourceFile]:
        """Files whose relative path matches any glob (gitwildmatch syntax)."""
        spec = pathspec.GitIgnoreSpec.from_lines(patterns)
        return [f for f in self.files if spec.match_file(f.rel)]

    def languages(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.files:
            if f.language:
                out[f.language] = out.get(f.language, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _gitignore(root: Path) -> pathspec.GitIgnoreSpec:
    lines: list[str] = []
    gi = root / ".gitignore"
    if gi.is_file():
        lines += gi.read_text(encoding="utf-8", errors="replace").splitlines()
    return pathspec.GitIgnoreSpec.from_lines(lines)


def scan(root: Path, include: list[str] | None = None) -> Inventory:
    """Walk `root` (optionally limited to `include` globs, e.g. one service of a monorepo)."""
    root = root.resolve()
    ignore = _gitignore(root)
    only = pathspec.GitIgnoreSpec.from_lines(include) if include else None
    inv = Inventory(root=root)
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for p in entries:
            rel = p.relative_to(root).as_posix()
            if p.is_dir():
                if p.name in ALWAYS_SKIP_DIRS or p.name.startswith(".") and p.name not in (".claude", ".github", ".cursor", ".vscode"):
                    inv.skip("dependency, build and hidden folders")
                    continue
                if ignore.match_file(rel + "/"):
                    inv.skip("folders in .gitignore")
                    continue
                stack.append(p)
                continue
            if SECRET_FILE.search(p.name):
                inv.skipped_secret.append(rel)
                continue
            if ignore.match_file(rel) or (only and not only.match_file(rel)):
                inv.skip("files in .gitignore" if ignore.match_file(rel) else "outside the chosen paths")
                continue
            lang = LANGS.get(p.suffix.lower())
            if lang is None and p.suffix.lower() not in CONFIG_SUFFIXES and p.name not in CONFIG_NAMES:
                inv.skip("binaries, media and other non-code files")
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    inv.skip("files over 1 MB")
                    continue
            except OSError:
                continue
            inv.files.append(SourceFile(p, rel, lang))
            if len(inv.files) >= MAX_FILES:
                return inv
    return inv


def git_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True,
                             timeout=10, stdin=subprocess.DEVNULL)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None
