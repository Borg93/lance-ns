"""Runners — every model's home (offline Ray Data actors AND online Ray Serve).

Each ``runners/<name>/`` owns a model: its env (``pyproject.toml``), its compute,
and its actor/deployment. ratch (pure orchestration) imports runner ACTORS lazily
into its Ray Data stages — ``map_batches(actor, runtime_env=<runner env>)`` — so
model deps resolve on the WORKERS, never in ratch's driver env. The same runner
can expose ``deployment.py`` (Ray Serve) for online use. ratch knows runner NAMES
(``Stage.runner=``), nothing about the models.
"""
