"""Turso (hosted libSQL) for both stores, used when TURSO_DATABASE_URL and TURSO_AUTH_TOKEN
are set:

- SQL: `Connection` speaks Turso's HTTP API (POST /v2/pipeline) and offers the slice of
  sqlite3 this project uses -- execute, executescript, close, and rows readable by column
  name or index -- so the agent and dashboard code don't change. Each statement is its own
  request, which autocommits, matching the local `isolation_level=None` connection.
- NoSQL: `DocStore` replaces TinyDB's raw.json with JSON documents in a `documents` table,
  offering the TinyDB calls the pipeline uses (`table(name).insert_multiple`, `.all()`).
  Query them with libSQL's JSON functions, e.g. `json_extract(doc_json, '$.record.fare')`.

Stdlib urllib only, like the other API clients here, so there is no native dependency.
Docs: https://docs.turso.tech/sdk/http/reference
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

DOCS_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  collection TEXT NOT NULL, doc_json TEXT NOT NULL, stored_at TEXT
);
CREATE INDEX IF NOT EXISTS documents_collection ON documents (collection);
"""


class TursoError(RuntimeError):
    pass


class Row(tuple):
    """Like sqlite3.Row: row["col"], row[0] and dict(row) all work."""

    def __new__(cls, values: list, cols: list[str]):
        row = super().__new__(cls, values)
        row._cols = cols
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            key = self._cols.index(key)
        return super().__getitem__(key)

    def keys(self) -> list[str]:
        return list(self._cols)


def _encode(value) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, (bool, int)):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode()}
    return {"type": "text", "value": str(value)}


def _decode(value: dict):
    kind = value["type"]
    if kind == "null":
        return None
    if kind == "integer":
        return int(value["value"])
    if kind == "float":
        return float(value["value"])
    if kind == "blob":
        return base64.b64decode(value["base64"])
    return value["value"]


class Cursor:
    def __init__(self, result: dict):
        cols = [c["name"] for c in result["cols"]]
        self.description = tuple((c, None, None, None, None, None, None) for c in cols) or None
        self._rows = [Row([_decode(v) for v in r], cols) for r in result["rows"]]
        self.rowcount = result["affected_row_count"]
        rowid = result.get("last_insert_rowid")
        self.lastrowid = int(rowid) if rowid is not None else None

    def fetchall(self) -> list[Row]:
        rows, self._rows = self._rows, []
        return rows

    def fetchone(self) -> Row | None:
        return self._rows.pop(0) if self._rows else None

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    def __init__(self, url: str, auth_token: str, timeout: float = 30.0):
        base = url.replace("libsql://", "https://", 1).rstrip("/")
        self._endpoint = f"{base}/v2/pipeline"
        self._token = auth_token
        self._timeout = timeout

    def _send(self, request: dict) -> dict:
        body = json.dumps({"requests": [request, {"type": "close"}]}).encode()
        req = urllib.request.Request(self._endpoint, data=body, method="POST", headers={
            "Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                reply = json.loads(resp.read())
        except urllib.error.HTTPError as exc:  # the token never appears in the message
            raise TursoError(f"Turso HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}") from None
        except urllib.error.URLError as exc:
            raise TursoError(f"Turso unreachable: {exc.reason}") from None
        first = reply["results"][0]
        if first["type"] == "error":
            raise TursoError(first["error"]["message"])
        return first["response"]

    def execute(self, sql: str, params: tuple | list = ()) -> Cursor:
        stmt = {"sql": sql, "args": [_encode(p) for p in params]}
        return Cursor(self._send({"type": "execute", "stmt": stmt})["result"])

    def executescript(self, sql: str) -> None:
        self._send({"type": "sequence", "sql": sql})

    def close(self) -> None:
        pass  # each request closes its own stream


class DocTable:
    def __init__(self, conn: Connection, name: str):
        self.conn, self.name = conn, name

    def insert_multiple(self, docs) -> None:
        docs = list(docs)
        if not docs:
            return
        stored_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        params = [v for d in docs for v in (self.name, json.dumps(d, ensure_ascii=False), stored_at)]
        marks = ", ".join("(?, ?, ?)" for _ in docs)
        self.conn.execute(f"INSERT INTO documents (collection, doc_json, stored_at) VALUES {marks}", params)

    def all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT doc_json FROM documents WHERE collection = ? ORDER BY rowid", (self.name,)
        ).fetchall()
        return [json.loads(r["doc_json"]) for r in rows]


class DocStore:
    """TinyDB's interface over the `documents` table, so `with ... as raw_db:` still works."""

    def __init__(self, conn: Connection):
        self.conn = conn

    def table(self, name: str) -> DocTable:
        return DocTable(self.conn, name)

    def close(self) -> None:
        pass

    def __enter__(self) -> "DocStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
