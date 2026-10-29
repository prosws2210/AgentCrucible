"""Document snapshots for RAG tests: a small keyword index of a repository's own documents.

A scenario mocks a retriever with `{snapshot: fixtures/docs-snapshot.json, k: 3}` instead of a fixed passage. The
tool then answers each query with the best-matching passages from the snapshot, so the agent's real retrieval path
(what it searches for, how it uses what comes back) is exercised without the live vector store. Pure Python, no
embeddings: results are the same on every run.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

QUERY_KEYS = ("query", "question", "q", "input", "text", "search", "search_query", "prompt", "message", "topic")
STOP = set("""a an and are as at be but by can do does for from has have how i if in into is it its me my no not of on
or our please so than that the their them then there these they this to was we what when where which who why will
with you your about any some tell know find check give get""".split())
WORD = re.compile(r"[a-z0-9][a-z0-9\-]{1,}")


def words(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


def chunk(text: str, size: int = 900) -> list[str]:
    """Split on blank lines, then pack paragraphs into passages of about `size` characters."""
    out, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if cur and len(cur) + len(para) > size:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}".strip() if cur else para[: size * 2]
    if cur:
        out.append(cur)
    return out


def build(documents: list[tuple[str, str]]) -> dict[str, Any]:
    """documents: (source, text) pairs -> the snapshot written to fixtures/."""
    passages = [{"source": src, "text": p} for src, text in documents for p in chunk(text)]
    return {"version": 1, "passages": passages}


@lru_cache(maxsize=16)
def _load(path: str, mtime: float) -> tuple[list[dict[str, str]], list[Counter], dict[str, float], float]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    passages = data.get("passages") or []
    tfs = [Counter(words(p["source"] + " " + p["text"])) for p in passages]
    n = max(len(passages), 1)
    df: Counter = Counter()
    for tf in tfs:
        df.update(tf.keys())
    idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
    avg = sum(sum(tf.values()) for tf in tfs) / n or 1.0
    return passages, tfs, idf, avg


def search(path: str | Path, query: str, k: int = 3) -> list[dict[str, str]]:
    """BM25 over the snapshot's passages."""
    p = Path(path)
    passages, tfs, idf, avg = _load(str(p), p.stat().st_mtime)
    q = set(words(query))
    scored = []
    for i, tf in enumerate(tfs):
        length = sum(tf.values())
        s = sum(idf.get(w, 0) * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * length / avg)) for w in q if w in tf)
        if s > 0:
            scored.append((s, i))
    scored.sort(key=lambda x: -x[0])
    return [passages[i] for _, i in scored[:k]]


def query_of(args: Any) -> str:
    """The search text from a tool call's arguments."""
    if isinstance(args, str):
        return args
    if isinstance(args, dict):
        for k in QUERY_KEYS:
            if isinstance(args.get(k), str):
                return args[k]
        strings = [v for v in args.values() if isinstance(v, str)]
        if strings:
            return max(strings, key=len)
        for v in args.values():
            if isinstance(v, (list, tuple)) and v and isinstance(v[0], str):
                return v[0]
    return ""


def is_snapshot_mock(mock: Any) -> bool:
    return isinstance(mock, dict) and isinstance(mock.get("snapshot"), str)


def answer(mock: dict[str, Any], args: Any) -> str:
    """What a retriever mocked with a snapshot returns for these arguments."""
    hits = search(mock["snapshot"], query_of(args), int(mock.get("k", 3)))
    if not hits:
        return "No results."
    return "\n\n".join(f"[{h['source']}]\n{h['text']}" for h in hits)


def resolve(mocks: dict[str, Any], root: Path) -> dict[str, Any]:
    """Make snapshot paths absolute (they are written relative to crucible.yaml)."""
    out = {}
    for name, m in mocks.items():
        if is_snapshot_mock(m) and not Path(m["snapshot"]).is_absolute():
            m = {**m, "snapshot": str((root / m["snapshot"]).resolve())}
        out[name] = m
    return out
