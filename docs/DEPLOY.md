# Deploying lance-ns on kind (event-driven, Dapr + Helm)

One umbrella Helm chart (`chart/`) deploys the whole event-driven stack on a local **kind** cluster:
the catalog (producer) + lineage (consumer) + web, plus Dapr, NATS JetStream, Apache-AGE Postgres,
OpenFGA, Dex, and MinIO. Modeled on the `rask/` chart pattern. See the topology diagram:
[`k8s-event-driven-architecture.html`](k8s-event-driven-architecture.html).

## Toolchain

`helm` + `docker` are required. `kind`, `kubectl`, `k9s`, `tilt` are downloaded into `./.localbin/`
(gitignored) — add it to PATH: `export PATH="$PWD/.localbin:$PATH"`.

## Bring it up

```bash
export PATH="$PWD/.localbin:$PATH" KUBECONFIG="$HOME/.kube/config"

kind create cluster --config deploy/kind/kind-config.yaml          # 1. cluster
helm repo add dapr https://dapr.github.io/helm-charts/             # 2. subchart repos
helm repo add nats https://nats-io.github.io/k8s/helm/charts/
helm repo add openfga https://openfga.github.io/helm-charts
helm dependency build ./chart

docker build -f .docker/rest-catalog.dockerfile -t lance-rest-catalog:dev .   # 3. build images
docker build -f .docker/web.dockerfile -t lance-lineage-web:dev .
kind load docker-image lance-rest-catalog:dev lance-lineage-web:dev --name lance

helm upgrade --install lance-ns ./chart                            # 4. deploy
kubectl rollout restart deploy/lance-ns-catalog deploy/lance-ns-lineage  # ensure sidecar injection

k9s                                                                # 5. watch it (or: kubectl get pods)
```

Reach the services (kind has no host ports — port-forward):

```bash
kubectl port-forward svc/lance-ns-web     5173:3000   # the UI
kubectl port-forward svc/lance-ns-lineage 8000:8000   # the lineage API
kubectl port-forward svc/lance-ns-catalog 2333:2333   # the catalog
```

## Verify the event-driven path

Publish an OpenLineage event **through the catalog's Dapr sidecar** and watch it reach Apache AGE via
the lineage subscription (this is exactly what a real `create_table` does):

```bash
kubectl exec deploy/lance-ns-catalog -c catalog -- python -c "
import httpx
event = {'eventType':'COMPLETE','eventTime':'t','producer':'x',
  'run':{'runId':'demo-1','facets':{'author':{'name':'alice','sub':'alice'},'lance':{'operation':'create_table','version':1}}},
  'job':{'namespace':'lance-catalog','name':'create_table'},'inputs':[],
  'outputs':[{'namespace':'kind','name':'kind\$demo','facets':{'version':{'datasetVersion':'1'}}}]}
print(httpx.post('http://localhost:3500/v1.0/publish/lineage-pubsub/lineage.events.v1', json=event).status_code)"
# → 204

curl -s 'localhost:8000/datasets/kind$demo/creator'   # → {"dataset":"kind$demo","creator":"alice"}
```

## Status (audited)

| | |
|---|---|
| Event-driven catalog→lineage (Dapr pub/sub over NATS JetStream) | ✅ verified end-to-end |
| Apache AGE graph, NATS JetStream, web, Dex, MinIO, Dapr control plane | ✅ running |
| Dapr sidecars injected into catalog + lineage | ✅ 2/2 each |
| Auth (Dex OIDC + OpenFGA) | ⚠️ deployed, `auth.enabled=false`; OpenFGA datastore migrates but the server init-container races Postgres on first install (re-run `helm upgrade` once Postgres is ready) |
| S3 | ⚠️ MinIO (not RustFS) |
| Medallion as event-driven services (raw→bronze landing, bronze→silver, silver→gold movers) + Ray dummy | ❌ not built — only the catalog producer + lineage consumer exist; the medallion is still the synchronous seed |

## Known follow-ups

- Fix the OpenFGA migrate/server ordering (init-container wait-for-postgres) and flip `auth.enabled=true`
  for the governed multi-user demo (Dex token → catalog → OpenFGA check).
- Build the medallion stage movers as event-driven services (S3 ObjectCreated → NATS → Ray bridge →
  Dapr-Workflow gold QC gate), with a **dummy** producer standing in for real Ray.
- **OpenBao** as the Dapr secret store (replace plaintext demo secrets).
- A Tiltfile (`helm_resource` + `live_update`) for hot-reload, and Makefile `kind-*`/`tilt-*` targets.
