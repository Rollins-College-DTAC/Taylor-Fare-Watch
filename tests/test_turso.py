import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent import turso
from agent.config import Paths
from agent.db import open_db, open_raw_store
from agent.etl import RAW_TABLE, scan_inbox
from generator import generate
from tests.test_etl import TEST_SETTINGS

TOKEN = "test-token"


def _value(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": v}


def _arg(a):
    return None if a["type"] == "null" else turso._decode(a)


class FakeTurso(BaseHTTPRequestHandler):
    """Just enough of Turso's /v2/pipeline, backed by an in-memory SQLite database."""

    db: sqlite3.Connection
    lock = threading.Lock()

    def do_POST(self):
        if self.path != "/v2/pipeline" or self.headers["Authorization"] != f"Bearer {TOKEN}":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"Unauthorized"}')
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        results = []
        with self.lock:
            for req in body["requests"]:
                try:
                    if req["type"] == "execute":
                        cur = self.db.execute(req["stmt"]["sql"], [_arg(a) for a in req["stmt"]["args"]])
                        result = {
                            "cols": [{"name": d[0]} for d in cur.description or []],
                            "rows": [[_value(v) for v in row] for row in cur.fetchall()],
                            "affected_row_count": max(cur.rowcount, 0),
                            "last_insert_rowid": str(cur.lastrowid) if cur.lastrowid else None,
                        }
                        results.append({"type": "ok", "response": {"type": "execute", "result": result}})
                    elif req["type"] == "sequence":
                        self.db.executescript(req["sql"])
                        results.append({"type": "ok", "response": {"type": "sequence"}})
                    else:
                        results.append({"type": "ok", "response": {"type": req["type"]}})
                except sqlite3.Error as exc:
                    results.append({"type": "error", "error": {"message": str(exc)}})
        out = json.dumps({"results": results}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@pytest.fixture
def turso_env(monkeypatch):
    FakeTurso.db = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeTurso)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("TURSO_DATABASE_URL", url)
    monkeypatch.setenv("TURSO_AUTH_TOKEN", TOKEN)
    yield url
    server.shutdown()


def test_pipeline_runs_on_turso_for_sql_and_documents(turso_env, tmp_path):
    paths = Paths.under(tmp_path)
    generate.run(3, interval=0, inbox=paths.inbox, log_path=tmp_path / "generator_log.csv",
                 processed=paths.processed, seed=5, resend_rate=0.0)
    conn = open_db(paths.sqlite)
    assert isinstance(conn, turso.Connection)
    with open_raw_store(paths.raw_json, conn) as raw_db:
        outcomes = scan_inbox(paths, conn, raw_db, TEST_SETTINGS, client=None)
        raw_docs = raw_db.table(RAW_TABLE).all()

    assert [o["status"] for o in outcomes] == ["landed"] * 3
    assert not paths.sqlite.exists() and not paths.raw_json.exists()  # nothing written locally
    assert {d["file_name"] for d in raw_docs} == {o["file_name"] for o in outcomes}
    imports = conn.execute("SELECT * FROM imports ORDER BY landed_at").fetchall()
    assert len(imports) == 3 and dict(imports[0])["run_id"] == imports[0][0]
    fare = conn.execute(
        "SELECT json_extract(doc_json, '$.record') AS record FROM documents WHERE collection = ? LIMIT 1",
        (RAW_TABLE,),
    ).fetchone()["record"]
    assert json.loads(fare)


def test_values_round_trip(turso_env):
    conn = turso.Connection(turso_env, TOKEN)
    conn.executescript("CREATE TABLE t (i INTEGER, f REAL, s TEXT, n TEXT);")
    cur = conn.execute("INSERT INTO t VALUES (?, ?, ?, ?)", (True, 1.5, "Cancún $239", None))
    assert cur.lastrowid == 1 and cur.rowcount == 1 and cur.description is None
    assert tuple(conn.execute("SELECT * FROM t").fetchone()) == (1, 1.5, "Cancún $239", None)


def test_errors_raise_without_leaking_the_token(turso_env):
    with pytest.raises(turso.TursoError, match="no such table"):
        turso.Connection(turso_env, TOKEN).execute("SELECT * FROM missing")
    with pytest.raises(turso.TursoError, match="401") as exc:
        turso.Connection(turso_env, "wrong").execute("SELECT 1")
    assert "wrong" not in str(exc.value)


def test_local_files_without_turso_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    conn = open_db(Paths.under(tmp_path).sqlite)
    assert isinstance(conn, sqlite3.Connection)
    conn.close()
