"""Shared OpenLineage spec constants + helpers for every lance-ns event emitter.

Keeping these in one place is what makes our hand-built ``RunEvent``s spec-true (and therefore
reusable by a Marquez-style consumer): a valid **UUID** ``runId``, the **required** top-level
``schemaURL``, and the ``_producer`` / ``_schemaURL`` every facet — standard OR custom — must carry.
"""

from __future__ import annotations

import uuid

#: The top-level ``schemaURL`` every OpenLineage ``RunEvent`` must carry (spec: ``RunEvent.schemaURL``).
RUN_EVENT_SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"

#: The ``BaseFacet`` schema — the spec-legal ``_schemaURL`` for our CUSTOM run facets (``lance``,
#: ``author``) that have no dedicated published schema. Every facet, standard or custom, MUST carry
#: ``_producer`` + ``_schemaURL``; a custom facet points at ``BaseFacet``, which lives in the CORE spec
#: (not a standalone facet file) — verified against the installed ``openlineage-python``.
BASE_FACET_SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/BaseFacet"

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
