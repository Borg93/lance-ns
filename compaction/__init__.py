"""Compaction + version-GC microservice, triggered by a Dapr cron binding.

Lance accumulates small fragments (one per append/insert) and old manifest versions over time. This
service runs on a schedule — a Dapr ``bindings.cron`` component POSTs to its route every interval — and
for each Lance dataset in the lakehouse bucket runs ``compact_files()`` (merge small fragments) and
``cleanup_old_versions()`` (GC superseded manifests). Both are idempotent, so a missed/retried tick is
safe. Run: ``uvicorn compaction.service:app``.
"""
