// Dagger CI module for lance-ns — reproducible lint / type-check / test in containers.
//
// Runs the SAME gates as .github/workflows/ci.yml, hermetically (identical locally and in CI):
//
//	dagger call ci          # lint + type-check + unit/integration tests
//	dagger call lint        # ruff check + format --check
//	dagger call typecheck   # ty
//	dagger call test        # pytest -m "not e2e"
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
			Exclude: []string{".venv", ".git", "node_modules", ".dagger", "frontend/node_modules"},
		}).
		WithWorkdir("/src").
		WithExec([]string{"uv", "sync", "--frozen", "--all-groups"})
}

// Ci runs every gate (lint → type-check → test) and returns a combined report. It fails on the first
// gate whose command exits non-zero (Dagger surfaces the container error).
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
	tests, err := m.Test(ctx, src)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf(
		"=== lint ===\n%s\n=== typecheck ===\n%s\n=== test ===\n%s\n=== CI PASSED ===",
		lint, types, tests,
	), nil
}
