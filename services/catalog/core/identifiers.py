"""Lance object identifier parsing.

The REST routes carry the ``$``-delimited string identifier in the ``{id}`` path
segment. The root namespace is represented by the delimiter itself.

Object-id *canonicalization* (joining segments into the string OpenFGA stores)
lives in :mod:`common.fga` (``canonical_object_id`` / ``parent_namespace_id``),
so the FGA object string is defined in exactly one place and the grant + check
paths cannot drift apart. This module owns the structural shape of an identifier:
splitting it into segments. (Parent-namespace derivation lives in ``common.fga``.)
"""

from __future__ import annotations


def parse_identifier(id_str: str, delimiter: str) -> list[str]:
    """Split a delimited identifier into segments; empty or delimiter-only → root ``[]``."""
    if not id_str or id_str == delimiter:
        return []
    return id_str.split(delimiter)
