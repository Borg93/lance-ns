package main

import (
	"context"

	"dagger/lance-ns/internal/dagger"
)

// Test runs the unit + integration tests, excluding the live-stack e2e marker (the CI test gate).
func (m *LanceNs) Test(
	ctx context.Context,
	// +defaultPath="/"
	// +optional
	src *dagger.Directory,
) (string, error) {
	return m.base(src).
		WithExec([]string{"uv", "run", "--no-sync", "pytest", "-q", "-m", "not e2e"}).
		Stdout(ctx)
}
