"""Run and audit history. Postgres in Docker (DATABASE_URL), SQLite file by default."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

runs = Table(
    "runs", metadata,
    Column("id", String(80), primary_key=True),
    Column("project", String(200)),
    Column("label", String(200), default=""),
    Column("suite", String(200), nullable=True),
    Column("model", String(200)),
    Column("status", String(20), index=True),  # queued | running | done | failed
    Column("created_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("k", Integer, nullable=True),
    Column("n_episodes", Integer, nullable=True),
    Column("pass_at_1", Float, nullable=True),
    Column("pass_pow_k", Float, nullable=True),
    Column("compare_to", String(80), nullable=True),
    Column("verdict", String(20), nullable=True),  # regressed | improved | unchanged (vs compare_to)
    Column("gate", String(10), nullable=True),  # pass | fail
    Column("params", JSON, default=dict),
    Column("summary", JSON, nullable=True),
    Column("error", Text, nullable=True),
)

audits = Table(
    "audits", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("server", String(200)),
    Column("grade", String(2)),
    Column("overall", Integer),
    Column("created_at", DateTime(timezone=True)),
    Column("report", JSON),
)


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def make_engine(url: str | None, root: Path) -> Engine:
    if not url:
        (root / ".crucible").mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{(root / '.crucible' / 'crucible.db').as_posix()}"
    engine = create_engine(url, pool_pre_ping=True, future=True)
    metadata.create_all(engine)
    return engine


def _row(r: Any) -> dict[str, Any]:
    d = dict(r._mapping)
    for k, v in d.items():
        if isinstance(v, dt.datetime):
            d[k] = v.isoformat()
    return d


class Store:
    def __init__(self, engine: Engine):
        self.engine = engine

    # runs ---------------------------------------------------------------
    def add_run(self, **values: Any) -> None:
        with self.engine.begin() as c:
            c.execute(insert(runs).values(**values))

    def update_run(self, run_id: str, **values: Any) -> None:
        with self.engine.begin() as c:
            c.execute(update(runs).where(runs.c.id == run_id).values(**values))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            r = c.execute(select(runs).where(runs.c.id == run_id)).first()
        return _row(r) if r else None

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(select(runs).order_by(runs.c.created_at.desc()).limit(limit)).all()
        return [_row(r) for r in rows]

    def run_ids(self) -> set[str]:
        with self.engine.connect() as c:
            return {r[0] for r in c.execute(select(runs.c.id)).all()}

    # audits -------------------------------------------------------------
    def add_audit(self, server: str, report: dict[str, Any]) -> dict[str, Any]:
        with self.engine.begin() as c:
            res = c.execute(insert(audits).values(server=server, grade=report["grade"], overall=report["overall"],
                                                  created_at=now(), report=report))
            audit_id = res.inserted_primary_key[0]
        return self.get_audit(audit_id)  # type: ignore[return-value]

    def get_audit(self, audit_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            r = c.execute(select(audits).where(audits.c.id == audit_id)).first()
        return _row(r) if r else None

    def list_audits(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(select(audits.c.id, audits.c.server, audits.c.grade, audits.c.overall,
                                    audits.c.created_at).order_by(audits.c.id.desc()).limit(limit)).all()
        return [_row(r) for r in rows]
