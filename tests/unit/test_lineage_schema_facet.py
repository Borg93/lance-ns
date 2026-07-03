"""§9 P4 — blob-aware lineage SchemaDatasetFacet (the type helper + the medallion emitter)."""

from __future__ import annotations

import pyarrow as pa
from common import schema
from lance import blob_field
from medallion.schemas.events import build_run_event


def test_type_label_renders_media_types() -> None:
    arrow_schema = pa.schema(
        [
            pa.field("id", pa.int64()),
            blob_field("payload"),
            pa.field("thumbnail", pa.large_binary()),
            pa.field("embedding", pa.list_(pa.float32(), 8)),
            pa.field("caption", pa.string()),
        ]
    )
    labels = {field["name"]: field["type"] for field in schema.facet_fields(arrow_schema)}
    assert labels == {
        "id": "int64",
        "payload": "blob",  # not the verbose extension repr
        "thumbnail": "binary",
        "embedding": "array<float>",
        "caption": "string",
    }


def test_type_label_covers_list_and_plain_binary() -> None:
    assert schema.type_label(pa.field("tags", pa.list_(pa.string()))) == "array<string>"
    assert schema.type_label(pa.field("big", pa.large_list(pa.int32()))) == "array<int32>"
    assert schema.type_label(pa.field("raw", pa.binary())) == "binary"


def test_build_run_event_carries_schema_facet_on_the_output() -> None:
    fields = [{"name": "payload", "type": "blob"}, {"name": "embedding", "type": "array<float>"}]
    event = build_run_event(
        operation="embed",
        author="data_eng",
        job_namespace="medallion",
        inputs=[("bronze", "events")],
        output_namespace="silver",
        output_name="features",
        version=1,
        schema_fields=fields,
        token="t1",
    )
    output = event["outputs"][0]
    assert output["facets"]["schema"]["fields"] == fields
    assert output["facets"]["schema"]["_schemaURL"].endswith("SchemaDatasetFacet")
    assert "schema" not in event["inputs"][0].get("facets", {})  # inputs carry no schema facet


def test_failed_event_omits_schema_facet() -> None:
    event = build_run_event(
        operation="embed",
        author="data_eng",
        job_namespace="medallion",
        inputs=[("bronze", "events")],
        output_namespace="silver",
        output_name="features",
        schema_fields=[{"name": "x", "type": "blob"}],
        token="t1",
        event_type="FAIL",
        error_message="oom",
    )
    assert "schema" not in event["outputs"][0].get("facets", {})  # a FAIL keeps a bare output
