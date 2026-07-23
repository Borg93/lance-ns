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
# RustFS access for the CAS e2e (values.yaml defaults; the secret is pulled from the k8s Secret at run time).
RUSTFS_BUCKET      := lance-catalog
RUSTFS_ACCESS_KEY  := rustfsadmin
# Host OS/arch detection so a fresh clone bootstraps on Linux or macOS, x86_64 or arm64. Each tool names
# its release assets differently (k9s Title-cases the OS; tilt uses mac/x86_64), hence the derived variants.
# Done with sed/tr (NOT a shell `case`): a `)` inside $(shell …) prematurely closes make's paren-match.
OS          := $(shell uname -s | tr '[:upper:]' '[:lower:]')
OS_TITLE    := $(shell uname -s)
ARCH        := $(shell uname -m | sed -e 's/x86_64/amd64/' -e 's/aarch64/arm64/')
TILT_OS     := $(shell uname -s | tr '[:upper:]' '[:lower:]' | sed 's/darwin/mac/')
TILT_ARCH   := $(shell uname -m | sed 's/aarch64/arm64/')
KIND_V      := v0.25.0
KUBECTL_V   := v1.31.3
K9S_V       := v0.32.7
TILT_V      := 0.33.21
FGA_V       := 0.6.4
CATALOG_IMG := lance-rest-catalog:dev
RAY_IMG     := ray-lance:dev
# The micro-frontend zones (P5): the catch-all `home` + the four domain zones. Each builds from the ONE
# parametrized .docker/frontend.dockerfile via --build-arg APP=<zone>, image lance-<zone>:dev.
ZONES       := home data lineage models admin
MEDALLION_PORT := 8000
# OCI label provenance — supplied to every image build (BUILD_DATE rfc3339, VCS_REF full SHA, VERSION).
BUILD_DATE  := $(shell date -u +%FT%TZ)
VCS_REF     := $(shell git rev-parse HEAD 2>/dev/null || echo unknown)
VERSION     := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
BUILD_ARGS  := --build-arg BUILD_DATE=$(BUILD_DATE) --build-arg VCS_REF=$(VCS_REF) --build-arg VERSION=$(VERSION)

.PHONY: help bootstrap kind-up kind-down deps images load deploy up verify medallion compaction \
        gateway governed e2e e2e-all e2e-obs e2e-medallion e2e-media e2e-gateway e2e-compaction e2e-cas e2e-lineage \
        e2e-governance e2e-governed-union dashboards status k9s tilt-up tilt-ci clean down openapi openapi-check \
        prod-render-check alert-rules-check ci charts frontend

help: ## Show this help
	@grep -hE '^[a-z0-9-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

openapi: ## Regenerate the committed OpenAPI specs (docs/*-openapi.json) from the live FastAPI apps
	uv run scripts/gen_openapi.py

openapi-check: openapi ## Fail if the committed OpenAPI specs drift from the code (CI guard)
	@git diff --exit-code -- docs/catalog-openapi.json docs/lineage-openapi.json \
		|| { echo "!! docs/*-openapi.json is stale — run 'make openapi' and commit the result"; exit 1; }

prod-render-check: ## Render values-prod.yaml + assert its HA/security switches are ON (CI guard)
	@bash scripts/prod_render_check.sh

alert-rules-check: ## Validate the alert rules + PROVE they fire on synthetic series (promtool; needs promtool on PATH)
	@promtool check rules chart/alerting/rules.yml
	@cd chart/alerting && promtool test rules rules_test.yml

bootstrap: ## Download kind/kubectl/k9s/tilt/fga into .localbin (idempotent, OS+arch-aware) — helm + docker on PATH
	@mkdir -p $(LOCALBIN)
	@test -n "$(ARCH)"     || { echo "!! unsupported CPU '$$(uname -m)' — need x86_64 or arm64"; exit 1; }
	@test -n "$(OS_TITLE)" || { echo "!! unsupported OS '$$(uname -s)' — need Linux or Darwin"; exit 1; }
	@test -x $(LOCALBIN)/kind    || { echo "↓ kind";    curl -fsSL -o $(LOCALBIN)/kind "https://kind.sigs.k8s.io/dl/$(KIND_V)/kind-$(OS)-$(ARCH)" && chmod +x $(LOCALBIN)/kind; }
	@test -x $(LOCALBIN)/kubectl || { echo "↓ kubectl"; curl -fsSL -o $(LOCALBIN)/kubectl "https://dl.k8s.io/release/$(KUBECTL_V)/bin/$(OS)/$(ARCH)/kubectl" && chmod +x $(LOCALBIN)/kubectl; }
	@test -x $(LOCALBIN)/k9s     || { echo "↓ k9s";     curl -fsSL "https://github.com/derailed/k9s/releases/download/$(K9S_V)/k9s_$(OS_TITLE)_$(ARCH).tar.gz" | tar xz -C $(LOCALBIN) k9s; }
	@test -x $(LOCALBIN)/tilt    || { echo "↓ tilt";    curl -fsSL "https://github.com/tilt-dev/tilt/releases/download/v$(TILT_V)/tilt.$(TILT_V).$(TILT_OS).$(TILT_ARCH).tar.gz" | tar xz -C $(LOCALBIN) tilt; }
	@test -x $(LOCALBIN)/fga     || { echo "↓ fga";     curl -fsSL "https://github.com/openfga/cli/releases/download/v$(FGA_V)/fga_$(FGA_V)_$(OS)_$(ARCH).tar.gz" | tar xz -C $(LOCALBIN) fga; }
	@command -v docker >/dev/null || { echo "!! docker not on PATH — install https://docs.docker.com/get-docker/"; exit 1; }
	@command -v helm   >/dev/null || { echo "!! helm not on PATH — install https://helm.sh/docs/intro/install/"; exit 1; }
	@echo "✓ toolchain ready in .localbin ($(OS)/$(ARCH))"

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

images: frontend-images ## Build the catalog (catalog+lineage) + the 5 MFE zone images
	docker build $(BUILD_ARGS) -f .docker/rest-catalog.dockerfile -t $(CATALOG_IMG) .

load: ## Side-load the app + zone images into kind
	kind load docker-image $(CATALOG_IMG) $(foreach z,$(ZONES),lance-$(z):dev) --name $(CLUSTER)

frontend-images: ## Build all micro-frontend zone images (lance-<zone>:dev) from the parametrized frontend.dockerfile
	@for z in $(ZONES); do \
	  echo "→ building lance-$$z:dev"; \
	  docker build $(BUILD_ARGS) --build-arg APP=$$z -f .docker/frontend.dockerfile -t lance-$$z:dev . || exit 1; \
	done

frontend-load: ## Side-load the zone images into kind
	kind load docker-image $(foreach z,$(ZONES),lance-$(z):dev) --name $(CLUSTER)

deploy: ## helm upgrade --install the whole stack, then ensure sidecar injection
	helm upgrade --install $(RELEASE) ./chart --timeout 240s
	@kubectl rollout restart deploy/$(RELEASE)-catalog deploy/$(RELEASE)-lineage >/dev/null 2>&1 || true
	@echo "✓ deployed — run 'make verify' or 'make dashboards'"

up: kind-up deps images load deploy ## Everything: toolchain + cluster + images + deploy

verify: ## Prove the event-driven flow: catalog publishes via Dapr, lineage ingests into AGE
	@kubectl exec deploy/$(RELEASE)-catalog -c catalog -- python -c "import httpx; \
	  e={'eventType':'COMPLETE','eventTime':__import__('datetime').datetime.now(__import__('datetime').UTC).isoformat(),'producer':'x','run':{'runId':'make-verify','facets':{'author':{'name':'frank','sub':'frank'},'lance':{'operation':'create_table','version':1}}},'job':{'namespace':'lance-catalog','name':'create_table'},'inputs':[],'outputs':[{'namespace':'bronze','name':'bronze\$$mk','facets':{'version':{'datasetVersion':'1'}}}]}; \
	  print('dapr publish:', httpx.post('http://localhost:3500/v1.0/publish/lineage-pubsub/lineage.events.v1', json=e, timeout=8).status_code)"
	@sleep 4
	@kubectl exec deploy/$(RELEASE)-lineage -c lineage -- python -c "import httpx; \
	  print('AGE creator of bronze\$$mk:', httpx.get('http://localhost:8000/datasets/bronze\$$mk/creator', timeout=8).json())"

medallion: ## Fire the event-driven pipeline: lance-ray POST /produce → raw→bronze→silver→gold cascade
	@echo "lance-ray /produce → cascades raw → bronze → silver → gold via Dapr pub/sub …"
	@kubectl exec deploy/$(RELEASE)-lance-ray -c lance-ray -- python -c "import os, httpx; t=os.environ.get('APP_API_TOKEN'); h={'dapr-api-token': t} if t else {}; print('produce:', httpx.post('http://localhost:$(MEDALLION_PORT)/produce', headers=h, timeout=8).json())"
	@sleep 6
	@echo "resulting lineage DAG (gold's provenance):"
	@kubectl exec deploy/$(RELEASE)-lineage -c lineage -- python -c "import httpx; print(httpx.get('http://localhost:8000/datasets/gold\$$catalog/upstream', timeout=8).json())"

compaction: ## Trigger a compaction/GC sweep now (the Dapr cron binding also fires it on its schedule)
	@kubectl exec deploy/$(RELEASE)-compaction -c compaction -- python -c "import httpx; print('sweep:', httpx.post('http://localhost:$(MEDALLION_PORT)/compaction-cron', timeout=30).json())"

ray-image: ## Build + side-load the CPU Ray + lance-ray demo image into kind
	docker build $(BUILD_ARGS) -f .docker/ray-lance.dockerfile -t $(RAY_IMG) .
	kind load docker-image $(RAY_IMG) --name $(CLUSTER)

ray-demo: ray-image ## Real Ray cluster + `ray job submit`: distributed Lance write/index/evolve/compact vs RustFS
	@kubectl apply -f deploy/ray-lance-demo.yaml
	@# Pod DELETE, not rollout restart: a rebuilt same-tag :dev image only lands on a freshly-scheduled pod,
	@# and delete forces that reschedule to pull the just-loaded digest (IfNotPresent) — the kind same-tag
	@# staleness fix (memory: kind-same-tag-image-gotcha). Then assert the running pod serves the built digest.
	@kubectl delete pods -l app=ray-lance-head --ignore-not-found >/dev/null 2>&1 || true
	@kubectl rollout status deploy/ray-lance-head --timeout=180s
	@# A pod's imageID is the containerd MANIFEST digest; `docker inspect .Id` is the CONFIG digest — so
	@# match the pod's digest against the FULL set crictl holds for the tag (kind load replaces it → fresh).
	@RUNNING="$$(kubectl get pods -l app=ray-lance-head -o jsonpath='{.items[0].status.containerStatuses[0].imageID}')"; \
	 POD_SHA="$${RUNNING##*:}"; \
	 NODE_SHAS="$$(docker exec $(CLUSTER)-control-plane crictl images -o json | python3 -c "import sys,json; print(' '.join(s for i in json.load(sys.stdin).get('images',[]) if any('$(RAY_IMG)' in t for t in (i.get('repoTags') or [])) for s in ([i['id'].split(':')[-1]] + [r.split(':')[-1] for r in (i.get('repoDigests') or [])])))")"; \
	 case " $$NODE_SHAS " in *" $$POD_SHA "*) echo "ray head serves the freshly-loaded image ($$POD_SHA)" ;; \
	   *) echo "!! ray head imageID ($$RUNNING) not a digest the node holds for $(RAY_IMG) — stale, aborting"; exit 1 ;; esac
	@echo "ray job submit → distributed write + index + evolve + compact (baked scripts/ray_lance_job.py) …"
	@kubectl exec deploy/ray-lance-head -- \
	  ray job submit --address http://localhost:8265 \
	  --runtime-env-json '{"env_vars":{"RUN":"demo'$$(date +%s)'"}}' \
	  -- python /home/ray/jobs/ray_lance_job.py

ray-demo-clean: ## Tear down the Ray demo cluster
	@kubectl delete -f deploy/ray-lance-demo.yaml --ignore-not-found

gateway: ## Port-forward the API gateway — one entry point for the whole platform (Ctrl-C to stop)
	@echo "gateway → http://localhost:8088   ( / =UI  /lineage/* /catalog/* =API via Dapr invoke  /produce )"
	@kubectl port-forward svc/$(RELEASE)-gateway 8088:8080

governed: ## Governed demo: turn auth ON, then prove Dex(OIDC) → catalog → OpenFGA end to end
	@echo "enabling auth (Dex OIDC + OpenFGA) …"
	@helm upgrade --install $(RELEASE) ./chart --set image.catalog.tag=dev --set auth.enabled=true --timeout 200s >/dev/null
	@kubectl rollout restart deploy/$(RELEASE)-dex deploy/$(RELEASE)-catalog deploy/$(RELEASE)-lineage >/dev/null
	@kubectl rollout status deploy/$(RELEASE)-catalog --timeout=120s >/dev/null
	@kubectl exec -i deploy/$(RELEASE)-catalog -c catalog -- python - < scripts/governed_demo_k8s.py
	@echo "(reset to open dev mode with: make deploy)"

# PF_ADDR — the bind address for the forwards. Default 127.0.0.1 (localhost only, safe).
# On a REMOTE box (e.g. SSH'd in from a laptop) run `make dashboards PF_ADDR=0.0.0.0` and browse the
# host's LAN IP (`hostname -I`) at the ports below — no SSH tunnel needed. 0.0.0.0 exposes the UIs to
# the whole network, so only do it on a trusted LAN.
PF_ADDR ?= 127.0.0.1
# local port for the web UI; override if 5173 is taken (e.g. another user's vite). NOTE: no inline
# comment on the assignment below — GNU Make keeps trailing spaces before a `#`, which would break the port.
WEB_PORT ?= 5173
dashboards: ## Port-forward all the UIs (Ctrl-C to stop). Remote box: make dashboards PF_ADDR=0.0.0.0
	@echo "bind $(PF_ADDR) — browse localhost (or the host LAN IP if PF_ADDR=0.0.0.0):"
	@echo "home zone  → :$(WEB_PORT)   (the landing; cross-zone nav needs the Ingress — see docs/DEPLOY.md)"
	@echo "lineage    → :8000"
	@echo "Perses     → :8080   (metrics+traces+logs dashboards over GreptimeDB)"
	@echo "GreptimeDB → :4000   (/dashboard — SQL + PromQL over all 3 signals)"
	@echo "Dapr dash  → :8081"
	@kubectl port-forward --address $(PF_ADDR) svc/$(RELEASE)-web-home $(WEB_PORT):3000 & \
	 kubectl port-forward --address $(PF_ADDR) svc/$(RELEASE)-lineage 8000:8000 & \
	 kubectl port-forward --address $(PF_ADDR) svc/$(RELEASE)-perses 8080:8080 & \
	 kubectl port-forward --address $(PF_ADDR) svc/$(RELEASE)-greptimedb-standalone 4000:4000 & \
	 kubectl port-forward --address $(PF_ADDR) svc/$(RELEASE)-dapr-dashboard 8081:8080 & wait

# --- Fire the cascade lanes (the demo triggers) ----------------------------------------------------
# /produce and /ingest-media live on the medallion PRODUCER inside the lance-ray pod — token-guarded and
# NOT browser-exposed, so we exec into the pod (where APP_API_TOKEN already is). Watch the effect in the
# lineage graph (:8000 /runs /datasets), Greptime (:4000), or k9s. This is the "fire the demo" button.
produce: ## Fire the tabular cascade: raw → bronze → silver → gold
	@kubectl exec deploy/$(RELEASE)-lance-ray -c lance-ray -- python -c \
	 "import os,httpx; print(httpx.post('http://localhost:8000/produce', headers={'dapr-api-token':os.environ['APP_API_TOKEN']}, timeout=30).json())"

ingest-media: ## Fire the media lane: blob bronze → derived silver (thumbnail + embedding) on Ray
	@kubectl exec deploy/$(RELEASE)-lance-ray -c lance-ray -- python -c \
	 "import os,httpx; print(httpx.post('http://localhost:8000/ingest-media', headers={'dapr-api-token':os.environ['APP_API_TOKEN']}, timeout=60).json())"

reset-lineage: ## DESTRUCTIVE clean slate: wipe the lineage graph so the frontend shows only new cascades (fixes clutter + lag)
	@bash scripts/reset_lineage_graph.sh

e2e-obs: ## Run the e2e observability test against the deployed stack (auto-forwards catalog/lineage/greptime)
	@echo "port-forwarding catalog/lineage/greptime …"
	@kubectl port-forward svc/$(RELEASE)-catalog 2333:2333 >/dev/null 2>&1 & C=$$!; \
	 kubectl port-forward svc/$(RELEASE)-lineage 8000:8000 >/dev/null 2>&1 & L=$$!; \
	 kubectl port-forward svc/$(RELEASE)-dex 5556:5556 >/dev/null 2>&1 & X=$$!; \
	 kubectl port-forward svc/$(RELEASE)-greptimedb-standalone 4000:4000 >/dev/null 2>&1 & G=$$!; \
	 sleep 4; \
	 LANCE_E2E_CATALOG_URL=http://localhost:2333 LANCE_E2E_LINEAGE_URL=http://localhost:8000 \
	   LANCE_E2E_GREPTIME_URL=http://localhost:4000 \
	   uv run pytest tests/e2e/test_observability_e2e.py -v -m observability; rc=$$?; \
	 kill $$C $$L $$X $$G 2>/dev/null; exit $$rc

e2e-medallion: ## Run the e2e medallion-cascade test against the deployed stack (auto-forwards lance-ray/lineage)
	@echo "port-forwarding lance-ray/lineage …"
	@kubectl port-forward svc/$(RELEASE)-lance-ray 8002:8000 >/dev/null 2>&1 & R=$$!; \
	 kubectl port-forward svc/$(RELEASE)-lineage 8000:8000 >/dev/null 2>&1 & L=$$!; \
	 sleep 4; \
	 TOKEN=$$(kubectl exec deploy/$(RELEASE)-lance-ray -c lance-ray -- printenv APP_API_TOKEN 2>/dev/null || true); \
	 LANCE_E2E_LANCERAY_URL=http://localhost:8002 LANCE_E2E_LINEAGE_URL=http://localhost:8000 LANCE_E2E_DAPR_TOKEN=$$TOKEN \
	   uv run pytest tests/e2e/test_medallion_e2e.py -v -m medallion; rc=$$?; \
	 kill $$R $$L 2>/dev/null; exit $$rc

e2e-gateway: ## Run the e2e gateway test (Dapr service-invocation routing) against the deployed stack
	@kubectl port-forward svc/$(RELEASE)-gateway 8088:8080 >/dev/null 2>&1 & G=$$!; \
	 sleep 4; \
	 LANCE_E2E_GATEWAY_URL=http://localhost:8088 uv run pytest tests/e2e/test_gateway_e2e.py -v -m gateway; rc=$$?; \
	 kill $$G 2>/dev/null; exit $$rc

e2e-compaction: ## Run the e2e compaction test (real Lance sweep + OTel metric) against the deployed stack
	@kubectl port-forward svc/$(RELEASE)-compaction 8000:8000 >/dev/null 2>&1 & C=$$!; \
	 kubectl port-forward svc/$(RELEASE)-greptimedb-standalone 4000:4000 >/dev/null 2>&1 & G=$$!; \
	 sleep 4; \
	 LANCE_E2E_COMPACTION_URL=http://localhost:8000 LANCE_E2E_GREPTIME_URL=http://localhost:4000 \
	 LANCE_E2E_DAPR_TOKEN=$$(kubectl get secret $(RELEASE)-dapr-app-token -o jsonpath='{.data.token}' | base64 -d) \
	   uv run pytest tests/e2e/test_compaction_e2e.py -v -m compaction; rc=$$?; \
	 kill $$C $$G 2>/dev/null; exit $$rc

e2e-lineage: ## AGE-backed lineage e2e — real Cypher vs a hermetic AGE service container via Dagger (== CI)
	@dagger call test-lineage

e2e-media: ## Run the e2e MEDIA-lane test (ingest-media → blob bronze → derived silver + lineage) against the deployed stack
	@kubectl port-forward svc/$(RELEASE)-lance-ray 8002:8000 >/dev/null 2>&1 & R=$$!; \
	 kubectl port-forward svc/$(RELEASE)-lineage 8000:8000 >/dev/null 2>&1 & L=$$!; \
	 sleep 4; \
	 TOKEN=$$(kubectl exec deploy/$(RELEASE)-lance-ray -c lance-ray -- printenv APP_API_TOKEN 2>/dev/null || true); \
	 LANCE_E2E_LANCERAY_URL=http://localhost:8002 LANCE_E2E_LINEAGE_URL=http://localhost:8000 LANCE_E2E_DAPR_TOKEN=$$TOKEN \
	   uv run pytest tests/e2e/test_media_e2e.py -v -m media; rc=$$?; \
	 kill $$R $$L 2>/dev/null; exit $$rc

e2e-cas: ## Validate object-store conditional-write (CAS = Lance manifest commit safety) against RustFS
	@echo "port-forwarding RustFS (9900->9000) …"
	@kubectl port-forward svc/$(RELEASE)-rustfs 9900:9000 >/dev/null 2>&1 & S=$$!; \
	 sleep 4; \
	 LANCE_E2E_S3_ENDPOINT=http://localhost:9900 LANCE_E2E_S3_BUCKET=$(RUSTFS_BUCKET) \
	 LANCE_E2E_S3_ACCESS_KEY=$(RUSTFS_ACCESS_KEY) \
	 LANCE_E2E_S3_SECRET_KEY=$$(kubectl get secret $(RELEASE)-infra-credentials -o jsonpath='{.data.rustfs-secret-key}' | base64 -d) \
	   uv run pytest tests/e2e/test_object_store_cas_e2e.py -v -m cas; rc=$$?; \
	 kill $$S 2>/dev/null; exit $$rc


e2e-governance: ## e2e governance boundary cases (OIDC+FGA: create-lineage, malformed-bearer 401, non-owner rename/overwrite 403) — needs an AUTH-ON stack
	@echo "port-forwarding catalog/lineage/dex …"
	@kubectl port-forward svc/$(RELEASE)-catalog 2333:2333 >/dev/null 2>&1 & C=$$!; \
	 kubectl port-forward svc/$(RELEASE)-lineage 8000:8000 >/dev/null 2>&1 & L=$$!; \
	 kubectl port-forward svc/$(RELEASE)-dex 5556:5556 >/dev/null 2>&1 & D=$$!; \
	 sleep 4; \
	 LANCE_E2E_AUTH_SERVER=http://localhost:2333 LANCE_E2E_LINEAGE_URL=http://localhost:8000 \
	 LANCE_E2E_DEX=http://localhost:5556/dex \
	   uv run pytest tests/e2e/test_governance_e2e.py -v -m e2e; rc=$$?; \
	 kill $$C $$L $$D 2>/dev/null; exit $$rc

e2e-client-direct: ## Client-DIRECT write e2e (#2): vend → write_fragments (client→RustFS) → governed /commit, zero byte-ingress + 401/403 gates
	@echo "port-forwarding catalog/dex/openfga/rustfs …"
	@kubectl port-forward svc/$(RELEASE)-catalog 2333:2333 >/dev/null 2>&1 & C=$$!; \
	 kubectl port-forward svc/$(RELEASE)-dex 5556:5556 >/dev/null 2>&1 & D=$$!; \
	 kubectl port-forward svc/$(RELEASE)-openfga 8080:8080 >/dev/null 2>&1 & F=$$!; \
	 kubectl port-forward svc/$(RELEASE)-rustfs 9900:9000 >/dev/null 2>&1 & S=$$!; \
	 sleep 5; \
	 LANCE_E2E_CATALOG_URL=http://localhost:2333 LANCE_E2E_DEX=http://localhost:5556/dex \
	 LANCE_E2E_FGA=http://localhost:8080 LANCE_E2E_S3=http://localhost:9900 \
	   uv run pytest tests/e2e/test_client_direct_e2e.py -v -m e2e; rc=$$?; \
	 kill $$C $$D $$F $$S 2>/dev/null; exit $$rc

e2e-outbox: ## Transactional-outbox drain e2e (#4): stage a leftover event → trigger the reconcile sweep → re-ingested + object gone (deploy with services.lineage.outbox.enabled=true,reconcile.enabled=true)
	@echo "port-forwarding lineage/rustfs …"
	@kubectl port-forward svc/$(RELEASE)-lineage 8000:8000 >/dev/null 2>&1 & L=$$!; \
	 kubectl port-forward svc/$(RELEASE)-rustfs 9900:9000 >/dev/null 2>&1 & S=$$!; \
	 sleep 4; \
	 LANCE_E2E_LINEAGE_URL=http://localhost:8000 LANCE_E2E_S3=http://localhost:9900 \
	 LANCE_E2E_DAPR_TOKEN=$$(kubectl get secret $(RELEASE)-dapr-app-token -o jsonpath='{.data.token}' | base64 -d) \
	   uv run pytest tests/e2e/test_outbox_e2e.py -v -m e2e; rc=$$?; \
	 kill $$L $$S 2>/dev/null; exit $$rc

e2e-warehouses: ## Per-warehouse physical-isolation e2e (#3-A): provision A/B buckets → table under A lands in bucket-a, absent from bucket-b (deploy with catalog.warehouses.enabled=true; set LANCE_E2E_TOKEN to a project-admin bearer)
	@echo "port-forwarding catalog/rustfs …"
	@kubectl port-forward svc/$(RELEASE)-catalog 2333:2333 >/dev/null 2>&1 & C=$$!; \
	 kubectl port-forward svc/$(RELEASE)-rustfs 9900:9000 >/dev/null 2>&1 & S=$$!; \
	 sleep 4; \
	 LANCE_E2E_CATALOG_URL=http://localhost:2333 LANCE_E2E_S3=http://localhost:9900 \
	 LANCE_E2E_TOKEN=$${LANCE_E2E_TOKEN} LANCE_E2E_NONADMIN_TOKEN=$${LANCE_E2E_NONADMIN_TOKEN} \
	   uv run pytest tests/e2e/test_warehouses_e2e.py -v -m e2e; rc=$$?; \
	 kill $$C $$S 2>/dev/null; exit $$rc

e2e-multibase: ## Lance multi-base e2e (#3-B): create a table across 2 approved data buckets → fragments distributed across both (deploy with catalog.multibase.dataBases naming the buckets; set LANCE_E2E_TOKEN + LANCE_E2E_BASE_A/B)
	@echo "port-forwarding catalog/rustfs …"
	@kubectl port-forward svc/$(RELEASE)-catalog 2333:2333 >/dev/null 2>&1 & C=$$!; \
	 kubectl port-forward svc/$(RELEASE)-rustfs 9900:9000 >/dev/null 2>&1 & S=$$!; \
	 sleep 4; \
	 LANCE_E2E_CATALOG_URL=http://localhost:2333 LANCE_E2E_S3=http://localhost:9900 \
	 LANCE_E2E_TOKEN=$${LANCE_E2E_TOKEN} LANCE_E2E_BASE_A=$${LANCE_E2E_BASE_A} LANCE_E2E_BASE_B=$${LANCE_E2E_BASE_B} \
	   uv run pytest tests/e2e/test_multibase_e2e.py -v -m e2e; rc=$$?; \
	 kill $$C $$S 2>/dev/null; exit $$rc

e2e-governed-union: ## FULL governed-union e2e (deploy first: auth+fga+compute+quality ON, openbao OFF — see tests/e2e/test_governed_union_e2e.py)
	@echo "port-forwarding lance-ray/lineage/dex/openfga/rustfs + the bronze-to-silver mover …"
	@kubectl port-forward svc/$(RELEASE)-lance-ray 8002:8000 >/dev/null 2>&1 & PIDS=$$!; \
	 kubectl port-forward svc/$(RELEASE)-lineage 8000:8000 >/dev/null 2>&1 & PIDS="$$PIDS $$!"; \
	 kubectl port-forward svc/$(RELEASE)-dex 5556:5556 >/dev/null 2>&1 & PIDS="$$PIDS $$!"; \
	 kubectl port-forward svc/$(RELEASE)-openfga 8081:8080 >/dev/null 2>&1 & PIDS="$$PIDS $$!"; \
	 kubectl port-forward svc/$(RELEASE)-rustfs 9900:9000 >/dev/null 2>&1 & PIDS="$$PIDS $$!"; \
	 kubectl port-forward deploy/$(RELEASE)-bronze-to-silver 8003:8000 >/dev/null 2>&1 & PIDS="$$PIDS $$!"; \
	 ready=0; for i in $$(seq 1 30); do \
	   curl -fsS -m 2 -o /dev/null http://localhost:8002/livez 2>/dev/null \
	     && curl -fsS -m 2 -o /dev/null http://localhost:8000/livez 2>/dev/null \
	     && curl -fsS -m 2 -o /dev/null http://localhost:8081/healthz 2>/dev/null \
	     && curl -fsS -m 2 -o /dev/null http://localhost:5556/dex/.well-known/openid-configuration 2>/dev/null \
	     && curl -fsS -m 2 -o /dev/null http://localhost:8003/livez 2>/dev/null \
	     && curl -s -m 2 -o /dev/null http://localhost:9900/ 2>/dev/null \
	     && { ready=1; break; }; \
	   sleep 1; \
	 done; \
	 [ $$ready -eq 1 ] || { echo "!! port-forwards never became ready (lance-ray/lineage/openfga/dex/mover/rustfs)"; kill $$PIDS 2>/dev/null; exit 1; }; \
	 OPENFGA_API_URL=http://localhost:8081 scripts/seed_medallion_fga.sh \
	   || { echo "!! FGA seed failed — aborting before pytest (a silent seed failure reads as a 90s poll timeout)"; kill $$PIDS 2>/dev/null; exit 1; }; \
	 TOKEN=$$(kubectl exec deploy/$(RELEASE)-lance-ray -c lance-ray -- printenv APP_API_TOKEN 2>/dev/null || true); \
	 MTOKEN=$$(kubectl exec deploy/$(RELEASE)-bronze-to-silver -c mover -- printenv APP_API_TOKEN 2>/dev/null || true); \
	 LANCE_E2E_LANCERAY_URL=http://localhost:8002 LANCE_E2E_LINEAGE_URL=http://localhost:8000 \
	 LANCE_E2E_DEX=http://localhost:5556/dex LANCE_E2E_FGA=http://localhost:8081 \
	 LANCE_E2E_DAPR_TOKEN=$$TOKEN LANCE_E2E_MOVER_URL=http://localhost:8003 LANCE_E2E_MOVER_TOKEN=$$MTOKEN \
	 LANCE_E2E_S3_ENDPOINT=http://localhost:9900 LANCE_E2E_S3_BUCKET=$(RUSTFS_BUCKET) \
	 LANCE_E2E_S3_ACCESS_KEY=$(RUSTFS_ACCESS_KEY) \
	 LANCE_E2E_S3_SECRET_KEY=$$(kubectl get secret $(RELEASE)-infra-credentials -o jsonpath='{.data.rustfs-secret-key}' | base64 -d) \
	   uv run pytest tests/e2e/test_governed_union_e2e.py -v -m governed_union; rc=$$?; \
	 OPENFGA_API_URL=http://localhost:8081 scripts/seed_medallion_fga.sh || true; \
	 kill $$PIDS 2>/dev/null; exit $$rc

e2e-ray-train: ## #53 Ray TRAIN path e2e: governed train→candidate→blessed + reproducibility capture (pins, OTLP metrics, validator gate)
	@echo "port-forwarding lance-ray/catalog/lineage/dex/openfga/greptimedb …"
	@kubectl port-forward svc/$(RELEASE)-lance-ray 8002:8000 >/dev/null 2>&1 & PIDS=$$!; \
	 kubectl port-forward svc/$(RELEASE)-catalog 2333:2333 >/dev/null 2>&1 & PIDS="$$PIDS $$!"; \
	 kubectl port-forward svc/$(RELEASE)-lineage 8000:8000 >/dev/null 2>&1 & PIDS="$$PIDS $$!"; \
	 kubectl port-forward svc/$(RELEASE)-dex 5556:5556 >/dev/null 2>&1 & PIDS="$$PIDS $$!"; \
	 kubectl port-forward svc/$(RELEASE)-openfga 8081:8080 >/dev/null 2>&1 & PIDS="$$PIDS $$!"; \
	 kubectl port-forward svc/$(RELEASE)-greptimedb-standalone 4000:4000 >/dev/null 2>&1 & PIDS="$$PIDS $$!"; \
	 ready=0; for i in $$(seq 1 30); do \
	   curl -fsS -m 2 -o /dev/null http://localhost:8002/livez 2>/dev/null \
	     && curl -fsS -m 2 -o /dev/null http://localhost:2333/readyz 2>/dev/null \
	     && curl -fsS -m 2 -o /dev/null http://localhost:8000/livez 2>/dev/null \
	     && curl -fsS -m 2 -o /dev/null http://localhost:8081/healthz 2>/dev/null \
	     && { ready=1; break; }; sleep 1; done; \
	 [ $$ready -eq 1 ] || { echo "!! port-forwards never became ready"; kill $$PIDS 2>/dev/null; exit 1; }; \
	 OPENFGA_API_URL=http://localhost:8081 scripts/seed_medallion_fga.sh || true; \
	 TOKEN=$$(kubectl exec deploy/$(RELEASE)-lance-ray -c lance-ray -- printenv APP_API_TOKEN 2>/dev/null || true); \
	 GT=$$(curl -fsS -m 2 -o /dev/null http://localhost:4000/health 2>/dev/null && echo http://localhost:4000 || echo ""); \
	 LANCE_E2E_LANCERAY_URL=http://localhost:8002 LANCE_E2E_CATALOG_URL=http://localhost:2333 \
	 LANCE_E2E_LINEAGE_URL=http://localhost:8000 LANCE_E2E_DEX=http://localhost:5556/dex \
	 LANCE_E2E_FGA=http://localhost:8081 LANCE_E2E_DAPR_TOKEN=$$TOKEN LANCE_E2E_GREPTIME_URL=$$GT \
	   uv run pytest tests/e2e/test_ray_train_e2e.py -v -m ray_train; rc=$$?; \
	 kill $$PIDS 2>/dev/null; exit $$rc

e2e-ray-batch: ## #53 Ray BATCH path e2e: distributed Lance write/index/evolve/compact on the real KubeRay demo cluster (run `make ray-demo` deploy first)
	uv run pytest tests/e2e/test_ray_batch_e2e.py -v -m ray_batch

e2e: ## Run the core e2e suite in sequence against the deployed stack (auth-agnostic: obs, medallion, media, gateway, compaction, cas)
	@echo "▶ full core e2e suite against the deployed $(RELEASE) stack (each suite self-forwards + self-skips if unreachable)"; \
	 fail=0; failed=""; \
	 for t in e2e-obs e2e-medallion e2e-media e2e-gateway e2e-compaction e2e-cas; do \
	   echo; echo "═══════════ $$t ═══════════"; \
	   $(MAKE) --no-print-directory $$t || { fail=1; failed="$$failed $$t"; }; \
	 done; \
	 echo; if [ $$fail -eq 0 ]; then echo "✓ ALL core e2e suites passed"; \
	 else echo "✗ FAILED:$$failed  (governance is separate: 'make e2e-governance' on an auth-on stack)"; fi; \
	 exit $$fail

e2e-all: ## Full e2e incl. governance boundary cases (requires the stack deployed with auth ON)
	@$(MAKE) --no-print-directory e2e; a=$$?; \
	 echo; echo "═══════════ e2e-governance ═══════════"; \
	 $(MAKE) --no-print-directory e2e-governance; b=$$?; \
	 echo; if [ $$((a|b)) -eq 0 ]; then echo "✓ ALL e2e suites (incl. governance) passed"; fi; \
	 exit $$((a|b))

status: ## Show all pods
	@kubectl get pods

k9s: ## Inspect the cluster with k9s
	@k9s

tilt-up: ## Dev loop: build + deploy via Tilt, hot-reload the FastAPI services (UI at :10350)
	@tilt up

tilt-ci: ## One-shot: build + deploy via Tilt and wait for all workloads healthy
	@tilt ci --timeout 900s

ci: ## Run the Python CI gate (ruff + ty + openapi drift + unit/integration tests) hermetically via Dagger
	@dagger call ci

charts: ## Run the chart CI gate (helm lint/render invariants + prod-render-check + alert-rules-check) via Dagger
	@dagger call charts

frontend: ## Run the frontend CI gate (svelte-check + bun unit tests + eslint + prettier) hermetically via Dagger
	@dagger call frontend

clean: ## helm uninstall the release (keep the cluster)
	@helm uninstall $(RELEASE) 2>/dev/null || true

down: ## Delete the kind cluster
	@kind delete cluster --name $(CLUSTER)

e2e-ci: ## THE guarded live proof (P0.1): governed kind stack + the 5 e2e suites (CAS/#2/#3-A/#3-B/#4) — identical to the CI `e2e-stack` job
	@bash scripts/e2e_stack.sh

e2e-ray-ci: ## #53 guarded Ray-path proof: governed ray-ON kind stack + real KubeRay + both Ray suites — identical to the CI `ray-e2e` job
	@bash scripts/ray_e2e_stack.sh

deadcode: ## Dead-code sweep (vulture). Decorator-invoked symbols are IGNORED and reviewed knowns are whitelisted, so output ~0 == a REAL dead symbol surfaces instead of drowning in noise.
	@uvx vulture services scripts tests .vulture-whitelist.py --min-confidence 60 \
		--ignore-decorators "$(DEADCODE_IGNORE_DECORATORS)" || true
	@cd frontend && bunx knip --no-exit-code 2>/dev/null || echo "  (frontend: eslint --max-warnings=0 gates unused imports/vars)"

# Framework call sites vulture cannot see. WITHOUT these the sweep reported 70 "dead" symbols in services/,
# every one a false positive (FastAPI routes/exception handlers, pydantic validators) — a sweep that cries
# wolf 70 times is WORSE than none, because a genuine dead symbol is invisible in the noise.
DEADCODE_IGNORE_DECORATORS = @app.*,@router.*,@model_validator,@field_validator,@asynccontextmanager,@pytest.*
