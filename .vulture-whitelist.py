"""Vulture whitelist — symbols that ARE used, but only via a framework, so static analysis cannot see it.

Without this the dead-code sweep is useless noise: it reports ~119 "unused" symbols, of which ZERO are
actually dead. Every entry below is invoked by something other than a direct Python reference. Keeping the
list explicit (rather than lowering the confidence threshold until the noise disappears) means a genuinely
dead symbol still shows up — which is the entire point of running the sweep at all.

Run: `make deadcode` (or `uvx vulture services scripts tests .vulture-whitelist.py --min-confidence 60`).
"""
# ruff: noqa

# --- FastAPI / Dapr route handlers: invoked by the framework via @router.* / @dapr_app.subscribe, never
# by name. Nothing in our code calls create_table() directly — the ASGI router does.
_ = "every @router.get/post/put/delete handler across services/*/api/**"
_ = "every @dapr_app.subscribe handler (on_stage, on_raw_arrival, on_train_trigger)"

# --- pydantic: `model_config` and every declared field are read by pydantic itself (validation,
# serialization, env-alias binding), not referenced by name in our source.
_ = "model_config on every BaseModel/BaseSettings"
_ = "declared model fields (aud/exp/iat, in_sync, quality_passed, transformation_type, ...)"

# --- pytest: `pytestmark` is collected by pytest; mock `.return_value` / `.side_effect` are attribute
# WRITES that configure a double — never read by our code.
_ = "pytestmark in every tests/e2e/*"
_ = "unittest.mock .return_value / .side_effect assignments"

# --- attrs: `attr.field()` declarations are consumed by the generated __init__, not by name.
_ = "attr.field() declarations (medallion_demo progress counters)"

# --- PIL: a module-level guard, assigned for its side effect (decompression-bomb limit).
_ = "Image.MAX_IMAGE_PIXELS"

# --- typing.Protocol: SinkAdapter is the CONTRACT for the gold-sink seam (S3Sink / LocalDirSink implement
# it structurally, and both are exercised by tests/unit/test_ingest_seam.py). Nothing annotates against it
# yet because the sink itself is designed-but-unwired — see docs/GOAL-prove-it.md (the ingest→medallion→sink
# data-zone gap). It documents the seam; deleting it would delete the design, not dead code.
_ = "SinkAdapter (Protocol)"
