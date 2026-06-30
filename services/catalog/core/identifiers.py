"""Lance object identifier parsing.

The REST routes carry the ``$``-delimited string identifier in the ``{id}`` path
segment. The root namespace is represented by the delimiter itself.

Object-id *canonicalization* (joining segments into the string OpenFGA stores)
lives in :mod:`common.fga` (``canonical_object_id`` / ``parent_namespace_id``),
so the FGA object string is defined in exactly one place and the grant + check
paths cannot drift apart. This module owns the structural shape of an identifier:
splitting it into segments and deriving its parent-namespace segments.
"""

from __future__ import annotations


def parse_identifier(id_str: str, delimiter: str) -> list[str]:
    """Split a delimited identifier into segments; empty or delimiter-only → root ``[]``."""
    if not id_str or id_str == delimiter:
        return []
    return id_str.split(delimiter)


def parent_segments(segments: list[str]) -> list[str]:
    """Return the parent-namespace segments of an identifier (all segments but the last).

    A table ``db1$t`` (``["db1", "t"]``) and a child namespace ``a$b`` (``["a", "b"]``)
    both live under the namespace formed by their leading segments (``["db1"]`` / ``["a"]``).
    A top-level object (``["t"]``) or the root (``[]``) yields the root namespace ``[]``.
    """
    return segments[:-1]
