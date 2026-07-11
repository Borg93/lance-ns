"""Shared OpenLineage spec constants + helpers for every lance-ns event emitter.

Keeping these in one place is what makes our hand-built ``RunEvent``s spec-true (and therefore
reusable by a Marquez-style consumer): a valid **UUID** ``runId``, the **required** top-level
``schemaURL``, and the ``_producer`` / ``_schemaURL`` every facet — standard OR custom — must carry.
"""

from __future__ import annotations

import logging
import uuid

log = logging.getLogger(__name__)

#: The top-level ``schemaURL`` every OpenLineage ``RunEvent`` must carry (spec: ``RunEvent.schemaURL``).
RUN_EVENT_SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"

#: The ``BaseFacet`` schema — the spec-legal ``_schemaURL`` for our CUSTOM run facets (``lance``,
#: ``author``) that have no dedicated published schema. Every facet, standard or custom, MUST carry
#: ``_producer`` + ``_schemaURL``; a custom facet points at ``BaseFacet``, which lives in the CORE spec
#: (not a standalone facet file) — verified against the installed ``openlineage-python``.
BASE_FACET_SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/BaseFacet"

#: Standard ``SchemaDatasetFacet`` schema URL — the produced dataset's columns (name + a concise,
#: blob/vector-aware type via ``common.schema.facet_fields``). Shared here so every emitter (catalog,
#: medallion) stamps the SAME spec version; a per-emitter copy would silently drift when one bumps it.
SCHEMA_FACET_SCHEMA_URL = (
    "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json#/$defs/SchemaDatasetFacet"
)

#: Fixed namespace for lance-ns name-based run ids (``uuid5`` of the project URL under ``NAMESPACE_URL``
#: — a constant, so the derivation is documented but not recomputed per call).
_RUN_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/Borg93/lance-ns")


def run_id_for(seed: str) -> str:
    """A spec-valid UUID ``runId`` that is STABLE for ``seed`` (e.g. ``"<operation>-<token>"``).

    OpenLineage requires ``runId`` to be a UUID (Marquez rejects anything else), but the medallion
    cascade and the reconcile back-fill need DETERMINISTIC ids so an at-least-once redelivery MERGEs
    onto the same ``(:Run)`` instead of duplicating it. ``uuid5`` gives both: the same seed always
    yields the same UUID. Keep the human-readable seed as a run facet / job name for correlation —
    never as the ``runId`` itself.
    """
    return str(uuid.uuid5(_RUN_ID_NAMESPACE, seed))


def custom_facet(producer: str, **fields: object) -> dict[str, object]:
    """Wrap a custom run-facet payload with the required ``_producer`` + ``_schemaURL`` (``BaseFacet``).

    Standard facets (version, dataSource, outputStatistics, …) carry their own published schema URL;
    our custom facets (``lance``, ``author``) have none, so they point at ``BaseFacet`` — which is what
    keeps them spec-legal for a strict consumer.
    """
    return {"_producer": producer, "_schemaURL": BASE_FACET_SCHEMA_URL, **fields}


#: Metadata-bloat cap on the schema facet (§9 P2, 2026-07-11): a thousands-of-columns table makes
#: the FACET ITSELF large (metadata bloat, not data bloat) and pushes the whole event toward the
#: bus payload ceiling the claim-check guard enforces. 512 fields ≈ tens of KiB worst-case — far
#: under the 64 KiB publish warning for the facet's share. Consumers needing the FULL schema of a
#: wider table read it from storage (the manifest IS the schema — /schema, reconcile's
#: read_storage_schema), never from the event.
FACET_MAX_FIELDS = 512


def schema_facet(producer: str, fields: object) -> dict[str, object]:
    """The standard ``SchemaDatasetFacet`` payload for an output dataset's column schema.

    One builder for every emitter so the ``_schemaURL`` spec version can never drift between the
    catalog and the medallion compute (both stamp the per-version schema onto the WROTE edge, #24).
    Caps at ``FACET_MAX_FIELDS`` (loudly): the facet stays spec-true (a shorter ``fields`` list is
    still a valid SchemaDatasetFacet), and the full schema remains readable from storage.
    """
    items = list(fields) if isinstance(fields, (list, tuple)) else fields
    if isinstance(items, list) and len(items) > FACET_MAX_FIELDS:
        log.warning(
            "schema_facet_truncated",
            extra={"fields": len(items), "cap": FACET_MAX_FIELDS},
        )
        items = items[:FACET_MAX_FIELDS]
    return {"_producer": producer, "_schemaURL": SCHEMA_FACET_SCHEMA_URL, "fields": items}
