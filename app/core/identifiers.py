"""Lance object identifier parsing.

The REST routes carry the ``$``-delimited string identifier in the ``{id}`` path
segment. The root namespace is represented by the delimiter itself.
"""

from __future__ import annotations


def parse_identifier(id_str: str, delimiter: str) -> list[str]:
    """Split a delimited identifier into segments; empty or delimiter-only → root ``[]``."""
    if not id_str or id_str == delimiter:
        return []
    return id_str.split(delimiter)
