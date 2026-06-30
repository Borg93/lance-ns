"""Shared FastAPI dependencies for the compaction service (Annotated type aliases)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from compaction.core.config import CompactionSettings, get_settings

SettingsDep = Annotated[CompactionSettings, Depends(get_settings)]
