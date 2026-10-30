"""Agents that use Redis get an empty Redis database of their own per episode."""

import os
import socket

import pytest

from agentcrucible.discover.plan import redis_settings
from agentcrucible.discover.schema import Datastore, Discovery, RepoInfo
from agentcrucible.runner import _flush_redis, redis_db_url

REDIS_URL = os.environ.get("CRUCIBLE_TEST_REDIS_URL")


def test_a_redis_url_points_at_one_numbered_database():
    assert redis_db_url("redis://redis:6379", 3) == "redis://redis:6379/3"
    assert redis_db_url("redis://:pw@h:6379/0?ssl=1", 4) == "redis://:pw@h:6379/4?ssl=1"


def test_the_code_s_redis_settings_are_found():
    d = Discovery(repo=RepoInfo(name="x", root=".", dotenv={".env": ["AUTH_REDIS_URL", "REDIS_URL", "REDIS_TTL", "DATABASE_URL"]}),
                  datastores=[Datastore(id="cache", kind="redis", url_env="CACHE_URL")])
    assert redis_settings(d) == ["AUTH_REDIS_URL", "CACHE_URL", "REDIS_URL"]


def test_episodes_lease_different_databases_and_give_them_back(tmp_path, monkeypatch):
    from agentcrucible.config import load_config
    from agentcrucible.runner import Runner, RunOptions

    flushed: list[str] = []
    monkeypatch.setattr("agentcrucible.runner._flush_redis", flushed.append)
    monkeypatch.setenv("CRUCIBLE_REDIS_URL", "redis://r:6379")
    (tmp_path / "crucible.yaml").write_text("project: p\nagent: {command: python agent.py}\nsuites: {s: {path: scenarios}}\n"
                                            "redis: {databases: 3}\n")
    runner = Runner(load_config(tmp_path), RunOptions(out_root=tmp_path / "out"))
    a, b = runner._lease_redis(), runner._lease_redis()
    assert {a, b} == {1, 2}  # 0 is never used
    with pytest.raises(RuntimeError, match="in use"):
        runner._lease_redis()
    runner._release_redis(a)
    assert runner._lease_redis() == a
    assert flushed.count("redis://r:6379/1") >= 2  # emptied when leased and when given back


@pytest.mark.skipif(not REDIS_URL, reason="set CRUCIBLE_TEST_REDIS_URL")
def test_flush_empties_only_that_database():
    def send(*parts: str) -> bytes:
        from urllib.parse import urlparse
        u = urlparse(REDIS_URL)
        with socket.create_connection((u.hostname, u.port or 6379), timeout=5) as s:
            s.sendall(b"".join(b"*%d\r\n" % len(p) + b"".join(b"$%d\r\n%s\r\n" % (len(x), x.encode()) for x in p)
                               for p in parts))
            return s.recv(4096)
    send(("SELECT", "5"), ("SET", "k", "v"), ("SELECT", "6"), ("SET", "k", "v"))
    _flush_redis(redis_db_url(REDIS_URL, 5))
    out = send(("SELECT", "5"), ("EXISTS", "k"), ("SELECT", "6"), ("EXISTS", "k"))
    assert out.split(b"\r\n")[1:4:2] == [b":0", b":1"]
