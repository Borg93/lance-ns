"""Dagger module for lance-ns CI — reproducible lint / type-check / test in containers.

Runs the SAME gates as .github/workflows/ci.yml, but hermetically (same result locally and in CI):

    dagger call ci --source=.          # lint + type-check + unit/integration tests
    dagger call lint --source=.        # ruff check + format --check
    dagger call typecheck --source=.   # ty
    dagger call test --source=.        # pytest -m "not e2e"

The base image is the project's uv image (pylance ships a Linux-only wheel, so the lockfile is Linux-only —
matching the container). A uv cache volume makes re-runs fast. e2e tests are excluded (they need the live
kind/Dapr stack); those run via `make e2e-*` against a deployed cluster, not here.
"""

import dagger
from dagger import dag, function, object_type

UV_IMAGE = "ghcr.io/astral-sh/uv:python3.13-trixie-slim"

# Never upload local build/cache dirs into the container context — they're huge and irrelevant.
_EXCLUDE = [".venv", ".git", "node_modules", ".dagger", "frontend/node_modules", "**/__pycache__"]


@object_type
class LanceNs:
    @function
    def base(self, source: dagger.Directory) -> dagger.Container:
        """The synced project container: uv image + source + `uv sync --frozen` (deps from the locked set)."""
        return (
            dag.container()
            .from_(UV_IMAGE)
            .with_mounted_cache("/root/.cache/uv", dag.cache_volume("lance-ns-uv"))
            .with_directory("/src", source, exclude=_EXCLUDE)
            .with_workdir("/src")
            .with_exec(["uv", "sync", "--frozen", "--all-groups"])
        )

    @function
    async def lint(self, source: dagger.Directory) -> str:
        """ruff lint + format check over services + tests (the CI lint gate)."""
        return await (
            self.base(source)
            .with_exec(["uvx", "ruff", "check", "services", "tests"])
            .with_exec(["uvx", "ruff", "format", "--check", "services", "tests"])
            .stdout()
        )

    @function
    async def typecheck(self, source: dagger.Directory) -> str:
        """ty type-check (the CI type gate)."""
        return await self.base(source).with_exec(["uvx", "ty", "check"]).stdout()

    @function
    async def test(self, source: dagger.Directory) -> str:
        """Unit + integration tests, excluding the live-stack e2e marker (the CI test gate)."""
        return await (
            self.base(source)
            .with_exec(["uv", "run", "--no-sync", "pytest", "-q", "-m", "not e2e"])
            .stdout()
        )

    @function
    async def ci(self, source: dagger.Directory) -> str:
        """Run every gate (lint → type-check → test) and return a combined report. Fails on the first gate
        whose command exits non-zero (dagger surfaces the container error)."""
        lint = await self.lint(source)
        types = await self.typecheck(source)
        tests = await self.test(source)
        return f"=== lint ===\n{lint}\n=== typecheck ===\n{types}\n=== test ===\n{tests}\n=== CI PASSED ==="
