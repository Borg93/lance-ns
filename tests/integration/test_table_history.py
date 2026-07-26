"""``GET /v1/table/{id}/history`` — the commit log, read out of the format.

The question this answers is the Lakekeeper-console one the owner asked for: *what changed in the data, and
when*. Lance is immutable and append-only at the manifest level, so the answer is already in the dataset —
``versions()`` for the timestamps, the transaction log for the substance — rather than in a side-table the
catalog would have to keep in sync with the data it describes.

Driven end to end through the real ``dir`` backend and real pylance writes, because the whole value of the
endpoint is that it reports what Lance ACTUALLY recorded. A mocked namespace would only pin the shape we
imagined the transaction log has, and the shape is exactly the thing worth verifying — it is why this feature
was scoped from a probe rather than from the docs.
"""

from __future__ import annotations

import io

import pyarrow as pa
import pyarrow.ipc as ipc
from fastapi.testclient import TestClient

ARROW = {"content-type": "application/vnd.apache.arrow.stream"}


def _ipc(table: pa.Table) -> bytes:
    sink = io.BytesIO()
    with ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue()


def _seed(client: TestClient) -> None:
    """create → delete → update, so the log has one row of each interesting shape."""
    assert client.post("/v1/namespace/h1/create", json={}).status_code == 200
    rows = pa.table({"id": pa.array([1, 2, 3], pa.int64()), "v": ["a", "b", "c"]})
    created = client.post("/v1/table/h1$t/create?mode=overwrite", content=_ipc(rows), headers=ARROW)
    assert created.status_code == 200, created.text
    deleted = client.post("/v1/table/h1$t/delete", json={"predicate": "id = 2"})
    assert deleted.status_code == 200, deleted.text
    updated = client.post("/v1/table/h1$t/update", json={"updates": [["v", "'Z'"]], "predicate": "id = 3"})
    assert updated.status_code == 200, updated.text


def test_history_reports_what_changed_per_version(real_ns_client: TestClient) -> None:
    _seed(real_ns_client)
    r = real_ns_client.get("/v1/table/h1$t/history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["table"] == "h1$t"
    rows = body["versions"]

    # Newest first — a log reads backwards, and a UI should not have to re-sort it.
    assert [row["version"] for row in rows] == sorted((row["version"] for row in rows), reverse=True), rows
    assert len(rows) == 3, rows

    by_version = {row["version"]: row for row in rows}
    # v1 = the create. Lance records it as an Overwrite, and it is the version that SET the schema.
    assert by_version[1]["operation"] == "Overwrite"
    assert by_version[1]["schema_set"] is True
    assert by_version[1]["fragments"] == 1

    # v2 = the delete, carrying the predicate AS THE CALLER WROTE IT. This single field is most of why the
    # endpoint is worth having: "rows matching `id = 2` went away" is an answer; "a Delete happened" is not.
    assert by_version[2]["operation"] == "Delete"
    assert by_version[2]["predicate"] == "id = 2"
    assert by_version[2]["schema_set"] is False

    # v3 = the update, with HOW it was applied. Not asserting fields_modified's value: pylance reports 0 for
    # this shape, and pinning a number we do not understand would be pinning a coincidence.
    assert by_version[3]["operation"] == "Update"
    assert by_version[3]["update_mode"] == "rewrite_rows"
    assert "fields_modified" in by_version[3]

    # Every row is timestamped — the WHEN half.
    assert all(row["timestamp"] for row in rows), rows


def test_history_carries_no_actor_and_does_not_pretend_to(real_ns_client: TestClient) -> None:
    """The format has no notion of a user, so this endpoint must not invent one.

    WHO lives in the lineage store's ``author`` run facet, keyed by the same version number
    (``GET /datasets/{name}/producers``). Asserting the absence here is the point: a future change that
    started guessing an actor from, say, the request that happened to read the log would be a fabricated
    audit trail, which is worse than no actor at all.
    """
    _seed(real_ns_client)
    rows = real_ns_client.get("/v1/table/h1$t/history").json()["versions"]
    for row in rows:
        assert "author" not in row
        assert "actor" not in row
        assert "user" not in row


def test_history_limit_bounds_the_transaction_reads(real_ns_client: TestClient) -> None:
    """`limit` exists so a table with many versions cannot turn one UI page into N object-store reads."""
    _seed(real_ns_client)
    rows = real_ns_client.get("/v1/table/h1$t/history?limit=2").json()["versions"]
    assert [row["version"] for row in rows] == [3, 2], rows  # the NEWEST 2, not the first 2


def test_history_of_a_missing_table_is_not_a_500(real_ns_client: TestClient) -> None:
    r = real_ns_client.get("/v1/table/h1$nope/history")
    assert r.status_code in (400, 404), r.text
