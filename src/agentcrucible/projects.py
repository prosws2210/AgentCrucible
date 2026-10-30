"""The projects one `crucible serve` shows: the one it was started in, plus every test project imported or added since.

A project is one `crucible.yaml` with one or more agents. Imports land in `<repo>/agent-tests/` and are registered here
so the dashboard can switch to them. The list is kept in `<server project>/.crucible/projects.json`.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ProjectConfig, find_config, load_config, load_scenarios

HOME = "home"


@dataclass
class Project:
    """A loaded project. The config is re-read when `crucible.yaml` or a scenario file changes on disk."""

    id: str
    path: Path  # crucible.yaml
    source: str  # server | import | manual | added
    codebase: str | None = None  # the repository the agents live in
    job: str | None = None  # the import job that produced it
    added: float = 0.0
    _cfg: ProjectConfig | None = None
    _stamp: tuple = ()
    _checked: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _signature(self) -> tuple:
        files = [self.path, *sorted(self.path.parent.glob("scenarios/**/*.y*ml"))]
        return tuple((str(f), f.stat().st_mtime_ns) for f in files if f.exists())

    @property
    def cfg(self) -> ProjectConfig:
        with self._lock:
            # one request reads the config many times; look at the files at most once a second (bind mounts are slow)
            if self._cfg is not None and time.monotonic() - self._checked < 1.0:
                return self._cfg
            sig = self._signature()
            if self._cfg is None or sig != self._stamp:
                self._cfg, self._stamp = load_config(self.path), sig
            self._checked = time.monotonic()
            return self._cfg

    def invalidate(self) -> None:
        """Re-read the files on next use (after the dashboard itself changed them)."""
        self._checked = 0.0

    @property
    def root(self) -> Path:
        return self.cfg.root

    @property
    def runs_dir(self) -> Path:
        return self.root / ".crucible" / "runs"

    @property
    def discovery_file(self) -> Path:
        return self.root / "discovery.json"

    def entry(self) -> dict[str, Any]:
        return {"id": self.id, "path": str(self.path), "source": self.source, "codebase": self.codebase,
                "job": self.job, "added": self.added}


def agent_names(cfg: ProjectConfig) -> list[str]:
    """Named agents, or the one unnamed `agent` (shown as "agent")."""
    return list(cfg.agents) or ["agent"]


def scenario_agent(cfg: ProjectConfig, suite: str, sc: Any) -> str:
    return sc.agent or cfg.suites[suite].agent or agent_names(cfg)[0]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


class Workspace:
    def __init__(self, home_config: Path | None):
        home = find_config(home_config)
        self.home = Project(HOME, home.resolve(), "server")
        self.file = self.home.root / ".crucible" / "projects.json"
        self.projects: dict[str, Project] = {HOME: self.home}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.file.is_file():
            return
        try:
            entries = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for e in entries:
            p = Path(e["path"])
            if e.get("id") and e["id"] != HOME and p.is_file():
                self.projects[e["id"]] = Project(e["id"], p, e.get("source", "added"), e.get("codebase"), e.get("job"),
                                                 e.get("added", 0.0))

    def _save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        entries = [p.entry() for p in self.projects.values() if p.id != HOME]
        self.file.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    def get(self, pid: str | None) -> Project | None:
        return self.projects.get(pid or HOME)

    def by_name(self, name: str) -> Project | None:
        """The project whose `project:` name is `name` (runs are stored under that name)."""
        for p in self.projects.values():
            try:
                if p.cfg.project == name:
                    return p
            except Exception:  # noqa: BLE001 - a broken crucible.yaml shouldn't hide the others
                continue
        return None

    def for_path(self, path: Path) -> Project | None:
        path = path.resolve()
        return next((p for p in self.projects.values() if p.path == path), None)

    def register(self, path: Path, source: str, codebase: str | None = None, job: str | None = None) -> Project:
        """Add a test project (or update the one already registered at that path)."""
        path = find_config(path) if path.is_dir() else path
        path = path.resolve()
        with self._lock:
            if (p := self.for_path(path)) is not None:
                p.invalidate()
                if p.id != HOME:
                    p.source, p.codebase, p.job = source if p.source != "server" else p.source, codebase or p.codebase, job or p.job
                    self._save()
                return p
            cfg = load_config(path)
            self._unique_name(path, cfg.project)
            base = slug(load_config(path).project)
            pid, n = base, 2
            while pid in self.projects or pid == HOME:
                pid, n = f"{base}-{n}", n + 1
            p = self.projects[pid] = Project(pid, path, source, codebase, job, time.time())
            self._save()
            return p

    def _unique_name(self, path: Path, name: str) -> None:
        """Runs are stored by project name, so two projects can't share one: rename the new one in its crucible.yaml."""
        taken = {q.cfg.project for q in self.projects.values() if q.path != path}
        if name not in taken:
            return
        new, n = f"{name}-2", 3
        while new in taken:
            new, n = f"{name}-{n}", n + 1
        text = path.read_text(encoding="utf-8")
        path.write_text(re.sub(rf"(?m)^project:\s*['\"]?{re.escape(name)}['\"]?\s*$", f"project: {new}", text, count=1),
                        encoding="utf-8")

    def remove(self, pid: str) -> bool:
        with self._lock:
            if pid == HOME or pid not in self.projects:
                return False
            del self.projects[pid]
            self._save()
            return True

    def _scenario_count(self, p: Project) -> int:
        """How many scenarios a project has, re-counted only when its config or a suite folder changes (parsing every
        YAML file on each project listing was slow on a large imported project)."""
        cfg = p.cfg
        dirs = [cfg.resolve(s.path) for s in cfg.suites.values()]
        key = (p.path.stat().st_mtime_ns, tuple(d.stat().st_mtime_ns if d.exists() else 0 for d in dirs))
        cache = self.__dict__.setdefault("_counts", {})
        if cache.get(p.id, (None,))[0] != key:
            cache[p.id] = (key, len(load_scenarios(cfg)))
        return cache[p.id][1]

    def summary(self, p: Project) -> dict[str, Any]:
        out: dict[str, Any] = {**p.entry(), "home": p.id == HOME}
        try:
            cfg = p.cfg
            out.update(name=cfg.project, agents=agent_names(cfg), scenarios=self._scenario_count(p),
                       root=str(cfg.root), discovery=p.discovery_file.is_file(), error=None)
        except Exception as e:  # noqa: BLE001
            out.update(name=p.path.parent.name, agents=[], scenarios=0, root=str(p.path.parent), discovery=False,
                       error=f"{type(e).__name__}: {str(e)[:300]}")
        return out
