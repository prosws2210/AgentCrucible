"""Fixture SQL drafted from a repository's schema files runs on a plain database server."""

from agentcrucible.discover.plan import _schema_for, psql_free


def test_psql_only_syntax_is_left_out_and_the_rest_kept():
    sql = (
        "\\set cutoff '2026-01-01'\n"
        "CREATE TABLE a (id int, t time DEFAULT '10:30', j jsonb DEFAULT '{\"a\":\"b\"}', n int DEFAULT 1::int);\n"
        "SELECT set_config('billing.cutoff', :'cutoff', true);\n"
        "UPDATE a SET n = :n;\n"
        "INSERT INTO a VALUES (1, 'see :later', '{\"x\": \"y\"}', 2);\n"
    )
    out = psql_free(sql)
    assert "\\set" not in out
    assert "CREATE TABLE a" in out and "INSERT INTO a VALUES" in out  # casts, times, JSON and text survive
    kept = [ln for ln in out.splitlines() if not ln.startswith("--")]
    assert not any(":'cutoff'" in ln or ":n;" in ln for ln in kept)
    assert out.count("left out by AgentCrucible") == 2


def test_only_the_agents_own_service_schema_is_used(tmp_path):
    for svc in ("ai-api", "billing"):
        (tmp_path / "services" / svc).mkdir(parents=True)
        (tmp_path / "services" / svc / "requirements.txt").write_text("")
    roots = {"services/ai-api"}
    assert _schema_for("services/ai-api/migrations/001.sql", tmp_path, roots)
    assert not _schema_for("services/billing/prisma/migrations/1/migration.sql", tmp_path, roots)
    assert not _schema_for("services/ai-api/manual/backfill_rupees.sql", tmp_path, roots)  # a one-off data script
    assert _schema_for("db/schema.sql", tmp_path, roots)  # shared, outside any service
    assert _schema_for("services/billing/x.sql", tmp_path, {""})  # agents at the repo root: every file is theirs


def test_drafted_rows_follow_the_schema_files_names_types_keys_and_schemas(tmp_path):
    from agentcrucible.discover.plan import seed_order, seed_sql, sql_references, sql_tables

    sql = (
        'CREATE TABLE "Company" ("id" TEXT NOT NULL, "createdAt" TIMESTAMP(3) NOT NULL DEFAULT now(), CONSTRAINT "c_pk" PRIMARY KEY ("id"));\n'
        'CREATE TABLE "AuditEvent" ("id" UUID PRIMARY KEY, "companyId" TEXT NOT NULL, "tags" TEXT[], "ok" BOOL);\n'
        'ALTER TABLE "AuditEvent" ADD CONSTRAINT "f" FOREIGN KEY ("companyId") REFERENCES "Company"("id");\n'
        "CREATE TABLE orphan (id TEXT, parent_id TEXT REFERENCES missing_parent(id));\n"
        "SET search_path TO billing;\n"
        "CREATE TABLE plans (id TEXT);\n"
    )
    t = sql_tables(sql)
    assert set(t) == {"company", "auditevent", "orphan"}  # `plans` is in the billing schema
    assert t["auditevent"][0] == '"AuditEvent"' and t["auditevent"][1]["companyid"] == (True, "TEXT", '"companyId"')
    order = list(seed_order({"AuditEvent": 1, "Company": 1, "orphan": 1}, sql_references(sql), set()))
    assert order == ["Company", "AuditEvent"]  # referenced first; a row pointing at an unseeded table is left out
    rows = seed_sql({'"AuditEvent"': {'"id"': "UUID", '"companyId"': "TEXT", '"tags"': "TEXT[]", '"ok"': "BOOL"}}, create=False)
    assert 'INSERT INTO "AuditEvent" ("id", "companyId", "tags", "ok")' in rows
    assert "'00000000-0000-4000-8000-000000000001'" in rows and "'{}'" in rows and "TRUE" in rows


def test_drafted_tasks_name_ids_the_database_accepts():
    from agentcrucible.discover.plan import UUID_EXAMPLE, _task_for, id_examples
    from agentcrucible.discover.pyfacts import _sql_type
    from agentcrucible.discover.schema import Datastore, Discovery, RepoInfo, Tool

    assert _sql_type("UUID(as_uuid=True)") == "UUID"
    d = Discovery(repo=RepoInfo(name="x", root="."), datastores=[
        Datastore(id="app", kind="postgres", tables={"documents": {"id": "UUID", "user_id": "UUID", "name": "TEXT"}})])
    ids = id_examples(d)
    assert ids["document_id"] == ids["user_id"] == UUID_EXAMPLE
    t = Tool(name="create_invoice_from_document", params={"document_id": "str", "order_ref_id": "str", "note_id": "Optional[str]"})
    task = _task_for(t, ids)
    assert f"document_id: {UUID_EXAMPLE}" in task and "order_ref_id: A-1001" in task  # matches the seeded rows
    assert "note_id" not in task  # optional inputs aren't asked for: they steer the agent toward other tools
    doc = Tool(name="create_invoice_from_document", params={"document_id": "Optional[str]", "user_id": "str"})
    assert f"document_id: {UUID_EXAMPLE}" in _task_for(doc, ids)  # ...unless the tool is about that thing
