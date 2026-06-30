"""Event-driven medallion pipeline — a dummy lance-ray producer + 3 stage movers.

The medallion lakehouse pattern (raw → bronze → silver → gold) as **event-driven microservices** on
Dapr pub/sub. ``lance-ray`` (a dummy Ray ingest job) is the **head of the pipeline**: it produces the
``raw_events`` dataset and publishes the first trigger (``medallion.raw``). Each mover subscribes to its
upstream stage's trigger, emits a standard OpenLineage transform event (so the lineage graph grows the
``DERIVED_FROM`` edge), and publishes the next stage's trigger — so one source event cascades the whole
chain, and Dapr propagates the W3C trace context across every hop (one distributed trace, raw → gold).

See ``docs/event-driven-pipeline.html`` and ``docs/MEDALLION.md``.
"""
