# lance-ns — event-driven Lance lakehouse + lineage on kind (Dapr / NATS / AGE / OpenFGA / Dex / RustFS
# / OpenBao / Jaeger). One `make up` bootstraps the toolchain, the cluster, and the whole stack.
#
#   make up        # bootstrap + kind cluster + build images + deploy everything (idempotent)
#   make verify    # prove the event-driven flow (catalog -> Dapr -> NATS -> lineage -> AGE)
#   make dashboards# port-forward the UIs (web / lineage / Jaeger / Dapr dashboard)
#   make k9s       # inspect the cluster
#   make tilt-up   # dev loop: hot-reload the FastAPI services via Tilt
#   make down      # delete the kind cluster

SHELL       := /bin/bash
LOCALBIN    := $(CURDIR)/.localbin
export PATH := $(LOCALBIN):$(PATH)
export KUBECONFIG ?= $(HOME)/.kube/config

CLUSTER     := lance
RELEASE     := lance-ns
ARCH        := $(shell case $$(uname -m) in x86_64) echo amd64;; aarch64|arm64) echo arm64;; esac)
KIND_V      := v0.25.0
KUBECTL_V   := v1.31.3
K9S_V       := v0.32.7
TILT_V      := 0.33.21
CATALOG_IMG := lance-rest-catalog:dev
WEB_IMG     := lance-lineage-web:dev
# OCI label provenance — supplied to every image build (BUILD_DATE rfc3339, VCS_REF full SHA, VERSION).
BUILD_DATE  := $(shell date -u +%FT%TZ)
VCS_REF     := $(shell git rev-parse HEAD 2>/dev/null || echo unknown)
VERSION     := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
BUILD_ARGS  := --build-arg BUILD_DATE=$(BUILD_DATE) --build-arg VCS_REF=$(VCS_REF) --build-arg VERSION=$(VERSION)

.PHONY: help bootstrap kind-up kind-down deps images load deploy up verify dashboards status k9s \
        tilt-up tilt-ci clean down

help: ## Show this help
	@grep -hE '^[a-z0-9-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Download kind/kubectl/k9s/tilt into .localbin (idempotent) — helm + docker must be on PATH
	@mkdir -p $(LOCALBIN)
	@test -x $(LOCALBIN)/kind    || { echo "↓ kind";    curl -fsSL -o $(LOCALBIN)/kind "https://kind.sigs.k8s.io/dl/$(KIND_V)/kind-linux-$(ARCH)" && chmod +x $(LOCALBIN)/kind; }
	@test -x $(LOCALBIN)/kubectl || { echo "↓ kubectl"; curl -fsSL -o $(LOCALBIN)/kubectl "https://dl.k8s.io/release/$(KUBECTL_V)/bin/linux/$(ARCH)/kubectl" && chmod +x $(LOCALBIN)/kubectl; }
	@test -x $(LOCALBIN)/k9s     || { echo "↓ k9s";     curl -fsSL "https://github.com/derailed/k9s/releases/download/$(K9S_V)/k9s_Linux_$(ARCH).tar.gz" | tar xz -C $(LOCALBIN) k9s; }
	@test -x $(LOCALBIN)/tilt    || { echo "↓ tilt";    curl -fsSL "https://github.com/tilt-dev/tilt/releases/download/v$(TILT_V)/tilt.$(TILT_V).linux.x86_64.tar.gz" | tar xz -C $(LOCALBIN) tilt; }
	@command -v helm >/dev/null || { echo "!! helm not on PATH — install https://helm.sh/docs/intro/install/"; exit 1; }
	@echo "✓ toolchain ready in .localbin"

kind-up: bootstrap ## Create the kind cluster (idempotent)
	@kind get clusters 2>/dev/null | grep -qx $(CLUSTER) || kind create cluster --config deploy/kind/kind-config.yaml --wait 150s

deps: ## Add subchart repos + vendor chart deps into chart/charts/
	@helm repo add dapr https://dapr.github.io/helm-charts/ >/dev/null 2>&1 || true
	@helm repo add nats https://nats-io.github.io/k8s/helm/charts/ >/dev/null 2>&1 || true
	@helm repo add openfga https://openfga.github.io/helm-charts >/dev/null 2>&1 || true
	@helm repo add greptime https://greptimeteam.github.io/helm-charts/ >/dev/null 2>&1 || true
	@helm repo add vector https://helm.vector.dev >/dev/null 2>&1 || true
	@helm repo add perses https://perses.github.io/helm-charts >/dev/null 2>&1 || true
	@helm repo update >/dev/null && helm dependency build ./chart >/dev/null
	@echo "✓ chart deps vendored"

images: ## Build the catalog (catalog+lineage) + web images
	docker build $(BUILD_ARGS) -f .docker/rest-catalog.dockerfile -t $(CATALOG_IMG) .
	docker build $(BUILD_ARGS) -f .docker/web.dockerfile -t $(WEB_IMG) .

load: ## Side-load the app images into kind
	kind load docker-image $(CATALOG_IMG) $(WEB_IMG) --name $(CLUSTER)

deploy: ## helm upgrade --install the whole stack, then ensure sidecar injection
	helm upgrade --install $(RELEASE) ./chart --timeout 240s
	@kubectl rollout restart deploy/$(RELEASE)-catalog deploy/$(RELEASE)-lineage >/dev/null 2>&1 || true
	@echo "✓ deployed — run 'make verify' or 'make dashboards'"

up: kind-up deps images load deploy ## Everything: toolchain + cluster + images + deploy

verify: ## Prove the event-driven flow: catalog publishes via Dapr, lineage ingests into AGE
	@kubectl exec deploy/$(RELEASE)-catalog -c catalog -- python -c "import httpx; \
	  e={'eventType':'COMPLETE','eventTime':'t','producer':'x','run':{'runId':'make-verify','facets':{'author':{'name':'frank','sub':'frank'},'lance':{'operation':'create_table','version':1}}},'job':{'namespace':'lance-catalog','name':'create_table'},'inputs':[],'outputs':[{'namespace':'bronze','name':'bronze\$$mk','facets':{'version':{'datasetVersion':'1'}}}]}; \
	  print('dapr publish:', httpx.post('http://localhost:3500/v1.0/publish/lineage-pubsub/lineage.events.v1', json=e, timeout=8).status_code)"
	@sleep 4
	@kubectl exec deploy/$(RELEASE)-lineage -c lineage -- python -c "import httpx; \
	  print('AGE creator of bronze\$$mk:', httpx.get('http://localhost:8000/datasets/bronze\$$mk/creator', timeout=8).json())"

dashboards: ## Port-forward all the UIs (Ctrl-C to stop)
	@echo "web        → http://localhost:5173"
	@echo "lineage    → http://localhost:8000"
	@echo "Perses     → http://localhost:8080   (metrics+traces+logs dashboards over GreptimeDB)"
	@echo "GreptimeDB → http://localhost:4000   (/dashboard — SQL + PromQL over all 3 signals)"
	@echo "Dapr dash  → http://localhost:8081"
	@kubectl port-forward svc/$(RELEASE)-web 5173:3000 & \
	 kubectl port-forward svc/$(RELEASE)-lineage 8000:8000 & \
	 kubectl port-forward svc/$(RELEASE)-perses 8080:8080 & \
	 kubectl port-forward svc/$(RELEASE)-greptimedb-standalone 4000:4000 & \
	 kubectl port-forward svc/$(RELEASE)-dapr-dashboard 8081:8080 & wait

e2e-obs: ## Run the e2e observability test against the deployed stack (auto-forwards catalog/lineage/greptime)
	@echo "port-forwarding catalog/lineage/greptime …"
	@kubectl port-forward svc/$(RELEASE)-catalog 2333:2333 >/dev/null 2>&1 & C=$$!; \
	 kubectl port-forward svc/$(RELEASE)-lineage 8000:8000 >/dev/null 2>&1 & L=$$!; \
	 kubectl port-forward svc/$(RELEASE)-greptimedb-standalone 4000:4000 >/dev/null 2>&1 & G=$$!; \
	 sleep 4; \
	 LANCE_E2E_CATALOG_URL=http://localhost:2333 LANCE_E2E_LINEAGE_URL=http://localhost:8000 \
	   LANCE_E2E_GREPTIME_URL=http://localhost:4000 \
	   uv run pytest tests/e2e/test_observability_e2e.py -v -m observability; rc=$$?; \
	 kill $$C $$L $$G 2>/dev/null; exit $$rc

status: ## Show all pods
	@kubectl get pods

k9s: ## Inspect the cluster with k9s
	@k9s

tilt-up: ## Dev loop: build + deploy via Tilt, hot-reload the FastAPI services (UI at :10350)
	@tilt up

tilt-ci: ## One-shot: build + deploy via Tilt and wait for all workloads healthy
	@tilt ci --timeout 900s

clean: ## helm uninstall the release (keep the cluster)
	@helm uninstall $(RELEASE) 2>/dev/null || true

down: ## Delete the kind cluster
	@kind delete cluster --name $(CLUSTER)
