"""A schema kept as a pg_dump plus numbered migrations (no ORM migrations) becomes a fixture that loads."""

import os
from pathlib import Path

import pytest

from agentcrucible.discover.plan import (
    _data_files,
    _migrate_for,
    _seed_value,
    psql_free,
    sql_checked,
    sql_tables,
)

PG_URL = os.environ.get("CRUCIBLE_TEST_POSTGRES_URL")

DUMP = """\\restrict abc
SELECT pg_catalog.set_config('search_path', '', false);
CREATE TABLE public.tenant (
    id uuid NOT NULL,
    code character varying(7),
    rate numeric(3,2),
    suspended_at timestamp with time zone,
    CONSTRAINT tenant_code_check CHECK (((code)::text <> ''::text))
);
ALTER TABLE public.tenant OWNER TO app_owner;
GRANT SELECT ON TABLE public.tenant TO app_rw;
CREATE TABLE public.audit (id integer, at timestamp without time zone) PARTITION BY RANGE (at);
CREATE TABLE public.audit_p1 (id integer, at timestamp without time zone);
ALTER TABLE ONLY public.audit ATTACH PARTITION public.audit_p1 FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE public.note (id integer NOT NULL, body text);
"""
MIGRATION = """ALTER TABLE public.note ADD COLUMN IF NOT EXISTS author character varying(40);
ALTER TABLE public.note RENAME COLUMN body TO text;
ALTER TABLE public.tenant DROP COLUMN IF EXISTS suspended_at;
"""


def test_a_pg_dump_and_its_migrations_shape_the_tables():
    sql = psql_free(DUMP) + psql_free(MIGRATION)
    kept = [ln.strip() for ln in sql.splitlines() if not ln.startswith("--")]
    assert not any("OWNER TO" in ln or ln.startswith("GRANT") for ln in kept)  # no such roles in a test database
    assert sql.count("left out by AgentCrucible: roles and grants") == 2
    assert "\\restrict" not in sql
    t = sql_tables(sql)
    assert set(t["note"][1]) == {"id", "text", "author"}  # added and renamed by the migration
    assert "suspended_at" not in t["tenant"][1]  # dropped by the migration
    assert t["tenant"][1]["code"][1] == "character varying(7)"
    assert {"tenant", "audit", "audit_p1"} <= sql_checked(sql)  # a CHECK, a partitioned table and its partition
    assert "note" not in sql_checked(sql)


def test_drafted_values_fit_their_columns():
    assert len(_seed_value("code", "character varying(7)", 0).strip("'")) <= 7
    assert _seed_value("rate", "numeric(3,2)", 0) in ("0", "1")
    assert _seed_value("amount", "numeric(12,2)", 0) == "49.99"


def test_reference_data_beside_the_schema_is_loaded_too(tmp_path):
    db = tmp_path / "infrastructure" / "database"
    db.mkdir(parents=True)
    (db / "01_schema.sql").write_text(DUMP)
    (db / "01a_reference_data.sql").write_text("INSERT INTO public.note VALUES (1, 'x');")
    (db / "README.sql").write_text("-- nothing")
    files = _data_files(["infrastructure/database/01_schema.sql"], Path(tmp_path))
    assert files == ["infrastructure/database/01a_reference_data.sql"]


def test_alembic_projects_get_a_migrate_step():
    from agentcrucible.discover.schema import Datastore

    s = Datastore(id="app", kind="postgres", url_env="APP_DB_URL", schema_files=["services/api/alembic.ini"])
    assert _migrate_for(s) == {"migrate": "python -m alembic -c alembic.ini upgrade head", "url_env": "APP_DB_URL",
                               "cwd": "../services/api"}
    assert _migrate_for(Datastore(id="app", kind="postgres", schema_files=["db/schema.sql"])) == {}


@pytest.mark.skipif(not PG_URL, reason="set CRUCIBLE_TEST_POSTGRES_URL")
def test_migrate_runs_once_per_run_and_every_episode_gets_a_copy(tmp_path, monkeypatch):
    import psycopg

    from agentcrucible.config import Fixture, load_config
    from agentcrucible.runner import Runner, RunOptions

    monkeypatch.setenv("CRUCIBLE_POSTGRES_URL", PG_URL)
    (tmp_path / "crucible.yaml").write_text("project: p\nagent: {command: python agent.py}\nsuites: {s: {path: scenarios}}\n")
    (tmp_path / "migrate.py").write_text(
        "import os, psycopg\n"
        "with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as c:\n"
        "    c.execute('CREATE TABLE m (id int)')\n"
        "open('ran.txt', 'a').write('x')\n")
    runner = Runner(load_config(tmp_path), RunOptions(out_root=tmp_path / "out"))
    fx = Fixture(kind="postgres", seed="seed.sql", migrate="python migrate.py")
    created: list[str] = []
    urls = [runner._create_postgres("INSERT INTO m VALUES (1);", created, fx) for _ in range(2)]
    try:
        assert (tmp_path / "ran.txt").read_text() == "x"  # migrated once, into the template
        for url in urls:
            with psycopg.connect(url) as c:
                assert c.execute("SELECT count(*) FROM m").fetchone()[0] == 1
    finally:
        runner._drop_postgres(created + runner._pg_template_names)
    with psycopg.connect(PG_URL) as c:
        assert c.execute("SELECT count(*) FROM pg_database WHERE datname LIKE 'crucible_%'").fetchone()[0] == 0
