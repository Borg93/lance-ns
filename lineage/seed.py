"""Producer-side OpenLineage emitter for the mock medallion flow.

This is **compute-layer instrumentation, not part of the lineage service**. It uses the
official ``openlineage-python`` client to build spec-correct ``RunEvent``s for the
bronze → silver → gold flow and either writes them to ``sample_events.json`` or POSTs
them to a running lineage service at the OpenLineage default path ``/api/v1/lineage``.

The service never imports this module — producers and consumers stay decoupled, exactly
as a real job (lance-ray / an ingest job) would emit to us over HTTP. ``openlineage-python``
is a dev/demo dependency for that reason.

Run::

    uv run python -m lineage.seed --write lineage/sample_events.json
    uv run python -m lineage.seed --emit http://localhost:2334
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import attr
from openlineage.client import OpenLineageClient
from openlineage.client.event_v2 import InputDataset, Job, OutputDataset, Run, RunEvent, RunState
from openlineage.client.facet_v2 import RunFacet, dataset_version_dataset, schema_dataset
from openlineage.client.serde import Serde
from openlineage.client.transport.http import HttpConfig, HttpTransport

_PRODUCER = "https://github.com/Borg93/lance-ns/tree/main/lineage"
_JOB_NS = "lance-jobs"


@attr.define
class AuthorRunFacet(RunFacet):
    """Custom run facet carrying the OIDC identity that ran the job (the who-by).

    OpenLineage has no standard "run author" facet, so we define one; the lineage
    service reads ``run.facets.author.{name,sub}`` from it.
    """

    name: str = attr.field(default="")
    sub: str | None = attr.field(default=None)


def _schema(fields: tuple[tuple[str, str], ...]) -> dict[str, schema_dataset.DatasetFacet]:
    if not fields:
        return {}
    facet = schema_dataset.SchemaDatasetFacet(
        fields=[schema_dataset.SchemaDatasetFacetFields(name=n, type=t) for n, t in fields]
    )
    return {"schema": facet}


def _in(namespace: str, name: str, *fields: tuple[str, str]) -> InputDataset:
    return InputDataset(namespace=namespace, name=name, facets=_schema(fields))


def _out(namespace: str, name: str, version: int, *fields: tuple[str, str]) -> OutputDataset:
    """An output dataset with its schema + the Lance version this run produced (``version`` facet)."""
    facets: dict[str, Any] = dict(_schema(fields))
    facets["version"] = dataset_version_dataset.DatasetVersionDatasetFacet(datasetVersion=str(version))
    return OutputDataset(namespace=namespace, name=name, facets=facets)


def _event(
    *,
    run_id: str,
    event_time: str,
    job_name: str,
    author: str,
    inputs: list[InputDataset],
    outputs: list[OutputDataset],
) -> RunEvent:
    return RunEvent(
        eventTime=event_time,
        producer=_PRODUCER,
        eventType=RunState.COMPLETE,
        run=Run(runId=run_id, facets={"author": AuthorRunFacet(name=author, sub=author)}),
        job=Job(namespace=_JOB_NS, name=job_name),
        inputs=inputs,
        outputs=outputs,
    )


def build_events() -> list[RunEvent]:
    """The realistic medallion run history as spec-correct OpenLineage events.

    The flow (each output carries its produced Lance ``version``; authors are OIDC subs):

    1. **alice** ingests ``raw_events`` → ``bronze$events`` (v1).
    2. **data_eng** embeds ``bronze$events`` → ``silver$features`` (v1, adds ``embedding``).
    3. **data_eng** refines ``silver$features`` in place → v2 (adds ``caption``) — the
       "run against silver again" pass; a version bump, not a self-derivation.
    4. **analyst** aggregates ``silver$features`` → ``gold$catalog`` (v1).

    Run ids are fixed (idempotent re-ingest under AGE MERGE). COMPLETE events only (a real
    producer also emits START; omitted here for a compact, terminal-state history).
    """
    bronze_cols = (("id", "int"), ("payload", "binary"), ("src", "string"))
    silver_v1_cols = (*bronze_cols, ("embedding", "array<float>"))
    silver_v2_cols = (*silver_v1_cols, ("caption", "string"))
    return [
        _event(
            run_id="11111111-1111-1111-1111-111111111111",
            event_time="2026-06-20T09:00:00Z",
            job_name="ingest_events",
            author="alice",
            inputs=[_in("source", "raw_events")],
            outputs=[_out("bronze", "bronze$events", 1, *bronze_cols)],
        ),
        _event(
            run_id="22222222-2222-2222-2222-222222222222",
            event_time="2026-06-21T09:00:00Z",
            job_name="embed_features",
            author="data_eng",
            inputs=[_in("bronze", "bronze$events", *bronze_cols)],
            outputs=[_out("silver", "silver$features", 1, *silver_v1_cols)],
        ),
        _event(
            run_id="33333333-3333-3333-3333-333333333333",
            event_time="2026-06-21T11:00:00Z",
            job_name="caption_features",
            author="data_eng",
            inputs=[_in("silver", "silver$features", *silver_v1_cols)],
            outputs=[_out("silver", "silver$features", 2, *silver_v2_cols)],
        ),
        _event(
            run_id="44444444-4444-4444-4444-444444444444",
            event_time="2026-06-21T12:00:00Z",
            job_name="aggregate_gold",
            author="analyst",
            inputs=[_in("silver", "silver$features", *silver_v2_cols)],
            outputs=[_out("gold", "gold$catalog", 1, ("caption", "string"), ("embedding", "array<float>"))],
        ),
    ]


def events_as_dicts() -> list[dict[str, Any]]:
    """The medallion events as OpenLineage JSON dicts (via the client's serializer)."""
    return [json.loads(Serde.to_json(event)) for event in build_events()]


def write_sample(path: Path) -> None:
    """Write the medallion events to ``path`` as pretty OpenLineage JSON."""
    path.write_text(json.dumps(events_as_dicts(), indent=2) + "\n")


def emit(url: str) -> None:
    """POST every medallion event to a running lineage service (OpenLineage HTTP transport)."""
    client = OpenLineageClient(transport=HttpTransport(HttpConfig(url=url)))
    for event in build_events():
        client.emit(event)


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit the mock medallion OpenLineage events.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path, metavar="PATH", help="write events to a JSON file")
    group.add_argument("--emit", metavar="URL", help="POST events to a lineage service base URL")
    args = parser.parse_args()
    if args.write:
        write_sample(args.write)
    else:
        emit(args.emit)


if __name__ == "__main__":
    main()
