"""End-to-end catalog round-trip against a moto-mocked S3 (no MinIO needed).

Runs the real app + native backend + pylance data plane against an in-process
moto S3 server, exercising the full create → insert → count → query path on fake
Lance data. This is the deterministic, infra-free counterpart to the Docker e2e.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import boto3
import pyarrow as pa
import pyarrow.ipc as ipc
import pytest
from fastapi.testclient import TestClient
from moto.server import ThreadedMotoServer

ARROW = {"content-type": "application/vnd.apache.arrow.stream"}
BUCKET = "lance-moto"


def _ipc(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


@pytest.fixture(scope="module")
def moto_endpoint() -> Iterator[str]:
    server = ThreadedMotoServer(port=0)
    server.start()
    host, port = server.get_host_and_port()
    url = f"http://{host}:{port}"
    s3 = boto3.client(
        "s3",
        endpoint_url=url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    s3.create_bucket(Bucket=BUCKET)
    yield url
    server.stop()


@pytest.fixture
def moto_client(moto_endpoint: str) -> Iterator[TestClient]:
    os.environ.update(
        LANCE_REST_IMPL="dir",
        LANCE_REST_ROOT=f"s3://{BUCKET}",
        LANCE_S3_ENDPOINT=moto_endpoint,
        LANCE_S3_ACCESS_KEY_ID="test",
        LANCE_S3_SECRET_ACCESS_KEY="test",
        LANCE_S3_ALLOW_HTTP="true",
        LANCE_OIDC_ENABLED="false",
        LANCE_FGA_ENABLED="false",
    )
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_catalog_roundtrip_on_moto_s3(moto_client: TestClient) -> None:
    assert moto_client.post("/v1/namespace/m1/create", json={}).status_code == 200

    rows = pa.table({"id": pa.array([1, 2, 3], pa.int64()), "name": ["a", "b", "c"]})
    created = moto_client.post(
        "/v1/table/m1$t/create?mode=overwrite", content=_ipc(rows), headers=ARROW
    )
    assert created.status_code == 200, created.text
    assert created.json()["location"].startswith(f"s3://{BUCKET}/")

    assert moto_client.post(
        "/v1/table/m1$t/insert?mode=append",
        content=_ipc(pa.table({"id": pa.array([4], pa.int64()), "name": ["d"]})),
        headers=ARROW,
    ).status_code == 200
    assert int(moto_client.post("/v1/table/m1$t/count_rows", json={}).text) == 4

    query = moto_client.post("/v1/table/m1$t/query", json={"k": 10, "filter": "id >= 2", "vector": {}})
    assert query.headers["content-type"].startswith("application/vnd.apache.arrow.file")
    assert ipc.open_file(pa.BufferReader(query.content)).read_all().num_rows == 3
