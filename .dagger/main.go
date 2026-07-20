// Dagger CI module for lance-ns — reproducible lint / type-check / openapi / test in containers.
//
// Runs the CONTAINER-HERMETIC SUBSET of the CI `test` job (ruff lint + ty type-check + OpenAPI drift +
// unit/integration pytest), identical locally and in CI:
//
//	dagger call ci          # lint + type-check + openapi drift + unit/integration tests
//	dagger call lint        # ruff check + format --check
//	dagger call typecheck   # ty
//	dagger call openapi     # regenerate the specs from the apps + fail on drift
//	dagger call test        # pytest -m "not e2e" (covers the claim-lint invariants too)
//
// The CI `test` job's non-Python gates live in their own function — `dagger call charts` (helm lint/render
// invariants + prod-render-check + alert-rules-check). The one CI `test` gate NOT yet daggerized is the
// OpenFGA `fga model test` + model.json drift check (needs the `fga` CLI + jq); it stays a GHA step.
//
// The base image is the project's uv image (pylance ships a Linux-only wheel, so the lockfile is
// Linux-only — matching the container). A uv cache volume makes re-runs fast. The e2e tests are
// excluded (they need the live kind/Dapr stack; run those via `make e2e-*` against a deployed cluster).
package main

import (
	"context"
	"fmt"

	"dagger/lance-ns/internal/dagger"
)

// uvImage is the project's uv base image (Python 3.13, matching the Linux-only pylance lockfile).
const uvImage = "ghcr.io/astral-sh/uv:python3.13-trixie-slim"

type LanceNs struct{}

// base returns the synced project container: the uv image + source + `uv sync --frozen` (deps from the
// locked set). Unexported → a shared private helper, not a Dagger Function.
func (m *LanceNs) base(src *dagger.Directory) *dagger.Container {
	return dag.Container().
		From(uvImage).
		WithMountedCache("/root/.cache/uv", dag.CacheVolume("lance-ns-uv")).
		WithDirectory("/src", src, dagger.ContainerWithDirectoryOpts{
			// `rask` is a gitignored sibling checkout (its own Dagger module + toolchain) that CI's
			// `actions/checkout` never sees — excluding it keeps the mounted Python surface (services/
			// tests/ scripts/) byte-identical to CI's, so `dagger call ci` == the CI `test` job. Without
			// this, ruff/ty/pytest would scan rask's tree (which its own pyproject governs) and diverge.
			Exclude: []string{".venv", ".git", "node_modules", ".dagger", "frontend/node_modules", "rask"},
		}).
		WithWorkdir("/src").
		WithExec([]string{"uv", "sync", "--frozen", "--all-groups"})
}

// Ci runs every Python gate (lint → type-check → openapi drift → test) and returns a combined report. It
// fails on the first gate whose command exits non-zero (Dagger surfaces the container error). The order
// mirrors the CI `test` job: lint, then type-check, then the OpenAPI drift check, then the pytest suite.
func (m *LanceNs) Ci(
	ctx context.Context,
	// +defaultPath="/"
	// +optional
	src *dagger.Directory,
) (string, error) {
	lint, err := m.Lint(ctx, src)
	if err != nil {
		return "", err
	}
	types, err := m.Typecheck(ctx, src)
	if err != nil {
		return "", err
	}
	openapi, err := m.Openapi(ctx, src)
	if err != nil {
		return "", err
	}
	tests, err := m.Test(ctx, src)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf(
		"=== lint ===\n%s\n=== typecheck ===\n%s\n=== openapi ===\n%s\n=== test ===\n%s\n=== CI PASSED ===",
		lint, types, openapi, tests,
	), nil
}
