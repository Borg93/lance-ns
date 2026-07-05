{{/* Release name is the fullname (install as `helm install lance-ns ./chart` → all names = lance-ns-*). */}}
{{- define "lance.fullname" -}}{{ .Release.Name }}{{- end -}}

{{- define "lance.labels" -}}
app.kubernetes.io/name: lance-ns
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* In-cluster hostnames (subcharts derive their service name from the release). */}}
{{- define "lance.ageHost" -}}{{ .Release.Name }}-age{{- end -}}
{{- define "lance.natsHost" -}}{{ .Release.Name }}-nats{{- end -}}
{{- define "lance.openfgaHost" -}}{{ .Release.Name }}-openfga{{- end -}}
{{- define "lance.dexHost" -}}{{ .Release.Name }}-dex{{- end -}}
{{- define "lance.rustfsHost" -}}{{ .Release.Name }}-rustfs{{- end -}}
{{- define "lance.openbaoHost" -}}{{ .Release.Name }}-openbao{{- end -}}
{{- define "lance.greptimeHost" -}}{{ .Release.Name }}-greptimedb-standalone{{- end -}}

{{/* App image refs. required() fails the render LOUD if the tag is empty/unset — e.g. a prod overlay
that forgot to set a release tag — instead of emitting an invalid `repo:` ref the kubelet only rejects
later (InvalidImageName), bricking the pod with no obvious signal. */}}
{{- define "lance.catalogImage" -}}
{{- $i := .Values.image.catalog -}}
{{- printf "%s:%s" $i.repository (required "image.catalog.tag must be set (a release tag in prod; `dev` locally)" $i.tag) -}}
{{- end -}}
{{- define "lance.webImage" -}}
{{- $i := .Values.image.web -}}
{{- printf "%s:%s" $i.repository (required "image.web.tag must be set (a release tag in prod; `dev` locally)" $i.tag) -}}
{{- end -}}

{{/* CONSUMER endpoints — return the EXTERNAL override when set (the in-cluster component is then usually
disabled, e.g. a managed S3 / Postgres / Vault / collector in prod), else the in-cluster address. The
component's OWN Service/StatefulSet keeps the plain *Host helper above; only the apps that CONNECT switch.
This is what makes the docs/DURABILITY.md tier-3 externalization real (values-prod.yaml sets the overrides). */}}
{{- define "lance.s3Endpoint" -}}
{{- if .Values.rustfs.externalEndpoint -}}{{ .Values.rustfs.externalEndpoint }}{{- else -}}http://{{ include "lance.rustfsHost" . }}:{{ .Values.rustfs.port }}{{- end -}}
{{- end -}}
{{- define "lance.ageConnectHost" -}}
{{- .Values.age.externalHost | default (include "lance.ageHost" .) -}}
{{- end -}}
{{- define "lance.otlpEndpoint" -}}
{{- if .Values.observability.externalOtlpEndpoint -}}{{ .Values.observability.externalOtlpEndpoint }}{{- else -}}http://{{ include "lance.greptimeHost" . }}:{{ .Values.observability.greptimePort }}/v1/otlp{{- end -}}
{{- end -}}
{{- define "lance.vaultAddr" -}}
{{- if .Values.openbao.externalAddr -}}{{ .Values.openbao.externalAddr }}{{- else -}}http://{{ include "lance.openbaoHost" . }}:{{ .Values.openbao.port }}{{- end -}}
{{- end -}}
{{- define "lance.natsUrl" -}}
{{- if .Values.nats.externalUrl -}}{{ .Values.nats.externalUrl }}{{- else -}}nats://{{ include "lance.natsHost" . }}:4222{{- end -}}
{{- end -}}

{{/* The per-SUBSCRIBER pubsub component name (call: include "lance.subPubsub" (list $root <appId>)).
Each subscriber app-id gets its OWN pubsub.jetstream component carrying its queueGroupName — one shared
component cannot: lineage AND lance-ray both consume lineage.events.v1, so a single queue group would
SPLIT those messages across the two apps instead of duplicating per app / competing per replica. The
component (dapr-component.yaml) and the app's *_PUBSUB env must agree on this name — hence one helper. */}}
{{- define "lance.subPubsub" -}}
{{- $root := index . 0 -}}
{{- $root.Values.pubsub.name }}-{{ index . 1 -}}
{{- end -}}

{{/* daprd sidecar resource annotations — the app containers are bounded (resources.default), so the
sidecars must be too (an unbounded daprd per pod × 8 pods can starve a small node). One helper = one
place to size them. */}}
{{- define "lance.daprSidecarResources" -}}
{{- $r := .Values.dapr.sidecarResources -}}
dapr.io/sidecar-cpu-request: {{ $r.cpuRequest | quote }}
dapr.io/sidecar-cpu-limit: {{ $r.cpuLimit | quote }}
dapr.io/sidecar-memory-request: {{ $r.memoryRequest | quote }}
dapr.io/sidecar-memory-limit: {{ $r.memoryLimit | quote }}
{{- end -}}
{{/* Do the app services consume secrets via Dapr (the secret store), vs plaintext env? True when there is
ANY Vault to read from — the in-cluster OpenBao OR an external Vault address. This decouples "use the secret
store" from "render the in-cluster OpenBao server", so openbao.enabled=false + externalAddr consumes from
the external Vault WITHOUT falling back to plaintext secrets in pod env (the closed leak). */}}
{{- define "lance.secretsViaDapr" -}}
{{- if or .Values.openbao.enabled .Values.openbao.externalAddr -}}true{{- end -}}
{{- end -}}

{{/* Sidecar-only lineage routes: Dapr-delivered (pub/sub ingest + the cron reconcile binding), auth'd by
the app-api-token the sidecar stamps — they must NEVER be reachable through the public edge, which would
otherwise proxy them via the gateway's own sidecar (stamping that same trusted token). ONE source for the
gateway's 403 blocks — add any new Dapr-delivered lineage route here, not in gateway.yaml. Rendered as an
nginx regex alternation; `lineage-events` matches the app's subscription route (lineage/api/dapr.py). The
reconcile binding is blocked even when reconcile is disabled (the route isn't mounted then — belt and
suspenders). On the kgateway/Envoy migration these become "no HTTPRoute declared" (allow-list by
construction) — the service-side token check is the load-bearing guard either way. */}}
{{- define "lance.lineageSidecarOnlyRoutes" -}}
{{- $bn := .Values.services.lineage.reconcile.bindingName -}}
{{- /* The binding name is interpolated raw into the gateway 403 nginx regex (below) AND used as a Dapr
     Component metadata.name — validate the charset at the render so a `|` (which would add an empty
     alternation and 403 the whole /lineage/ API) or a space (which breaks `nginx -t`) fails loudly here
     instead of bricking the gateway. Same [a-z0-9-] shape a k8s name needs anyway. */ -}}
{{- if and $bn (not (regexMatch "^[a-zA-Z0-9._-]+$" $bn)) -}}
{{- fail (printf "services.lineage.reconcile.bindingName %q must match ^[A-Za-z0-9._-]+$ — it is interpolated into the gateway 403 regex and used as a Dapr Component name" $bn) -}}
{{- end -}}
{{- /* `with` skips a blank binding name — a bare `|` alternation would match the empty string and 403 the whole /lineage/ API. */ -}}
lineage-events{{ with $bn }}|{{ . }}{{ end }}
{{- end -}}

{{/* OTel SDK env for an app (call: include "lance.otelEnv" (list $root "<service.name>")). The apps run
under `opentelemetry-instrument` and export all three signals OTLP-direct to GreptimeDB — no Collector
(mirrors rask). The SDK appends /v1/{traces,metrics,logs} to the /v1/otlp base. GreptimeDB needs the
db-name header on every signal and ADDITIONALLY the trace-pipeline header on traces (→ opentelemetry_traces
table); metrics/logs must NOT carry the pipeline header, so traces get their own *_TRACES_HEADERS. */}}
{{- define "lance.otelEnv" -}}
{{- $root := index . 0 -}}
{{- $svc := index . 1 -}}
{{- $o := $root.Values.observability -}}
- { name: OTEL_SERVICE_NAME, value: {{ $svc | quote }} }
- { name: OTEL_EXPORTER_OTLP_ENDPOINT, value: "{{ include "lance.otlpEndpoint" $root }}" }
- { name: OTEL_EXPORTER_OTLP_PROTOCOL, value: "http/protobuf" }
- { name: OTEL_EXPORTER_OTLP_HEADERS, value: "x-greptime-db-name={{ $o.dbName }}" }
- { name: OTEL_EXPORTER_OTLP_TRACES_HEADERS, value: "x-greptime-db-name={{ $o.dbName }},x-greptime-pipeline-name={{ $o.tracePipeline }}" }
- { name: OTEL_TRACES_EXPORTER, value: "otlp" }
- { name: OTEL_METRICS_EXPORTER, value: "otlp" }
{{/* Logs go out via the OTel SDK (OTLP → GreptimeDB `opentelemetry_logs`) — the "three signals, one SDK,
all OTLP" path. NO double-ingest: the app pods carry `lance.dev/logs=otlp`, and Vector's kubernetes_logs
source excludes that label (values.yaml `vector.customConfig`), so Vector tails only the INFRA pods (no OTel
SDK) into `lance_logs`. Each pod's logs land in exactly one table; `make e2e-obs` still sees both populated
(apps → opentelemetry_logs, infra → lance_logs). Tradeoff: an app crash BEFORE the SDK inits is only in
`kubectl logs`, not GreptimeDB — acceptable for the OTLP-native path. */}}
- { name: OTEL_LOGS_EXPORTER, value: "otlp" }
{{/* Default metric export interval is 60s — too slow to observe in a demo/test. Push every 5s. */}}
- { name: OTEL_METRIC_EXPORT_INTERVAL, value: "5000" }
- { name: OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED, value: "true" }
{{/* Don't trace the k8s probe endpoints — they're hit every 10s and bury real request spans (otel
signals.md § Exclude noisy endpoints). Launcher-driven instrumentation → the env var is the only lever. */}}
- { name: OTEL_PYTHON_FASTAPI_EXCLUDED_URLS, value: "/livez,/readyz,/metrics" }
- { name: OTEL_RESOURCE_ATTRIBUTES, value: "service.namespace=lance-ns,deployment.environment.name={{ $o.environment | default "kind" }},service.version={{ $root.Chart.AppVersion }}" }
{{- end -}}


{{/* Rollout drain: a preStop sleep holds SIGTERM until endpoint removal has propagated to kube-proxy /
the Dapr sidecar, so in-flight requests drain instead of hitting connection-refused — this is what makes
the apps' /readyz shutting_down branch actually reachable during a rollout. Pairs with pod-level
terminationGracePeriodSeconds (grace > preStop + app drain). sh exists in every app image
(python-slim, nginx-unprivileged). */}}
{{- define "lance.preStop" -}}
lifecycle:
  preStop:
    exec:
      command: ["sh", "-c", "sleep {{ .Values.lifecycle.preStopSeconds }}"]
{{- end -}}

{{/* HTTP health probes for the FastAPI app workloads (catalog/lineage/producer/movers/compaction). Two
distinct signals: readiness (/readyz) is dependency-aware (503 until the pool/namespace is up AND again once
draining) so k8s only routes traffic to a truly-ready pod; liveness (/livez) is process-up only (never
checks a backend — a slow dependency must NOT trigger a restart loop). Liveness runs slower + more tolerant
(failureThreshold 3 × 20s) so a busy-but-alive worker is never SIGKILLed. One helper = every app agrees. */}}
{{- define "lance.appProbes" -}}
readinessProbe:
  httpGet: { path: /readyz, port: http }
  initialDelaySeconds: 5
  periodSeconds: 10
livenessProbe:
  httpGet: { path: /livez, port: http }
  initialDelaySeconds: 10
  periodSeconds: 20
  timeoutSeconds: 3
  failureThreshold: 3
{{- end -}}

{{/* TCP health probes for non-HTTP-health workloads — the SvelteKit web pod (no /readyz route) and RustFS
(S3 API, no health route). A successful TCP accept on the serving port is the liveness/readiness signal.
Call: include "lance.tcpProbes" "<portName>" (the named container port to dial). */}}
{{- define "lance.tcpProbes" -}}
readinessProbe:
  tcpSocket: { port: {{ . }} }
  initialDelaySeconds: 5
  periodSeconds: 10
livenessProbe:
  tcpSocket: { port: {{ . }} }
  initialDelaySeconds: 10
  periodSeconds: 20
  failureThreshold: 3
{{- end -}}

{{/* Container hardening applied to every APP container (our images: catalog/lineage/web/movers/compaction).
runAsNonRoot enforces the image's non-root USER (catalog uid 10001, web `bun`) at admission — a manifest that
regressed to root fails to start instead of running privileged. drop ALL caps + no privilege escalation +
the RuntimeDefault seccomp profile = the restricted PodSecurity baseline. readOnlyRootFilesystem is on by
default (values.security.readOnlyRootFilesystem) — each app mounts an emptyDir at /tmp for scratch (pyarrow
spill, OTel), so nothing needs a writable rootfs. Container-level (NOT pod-level) so it never touches the
injected daprd sidecar or the busybox wait-age initContainer (which legitimately runs as root). */}}
{{- define "lance.securityContext" -}}
securityContext:
  runAsNonRoot: true
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: {{ .Values.security.readOnlyRootFilesystem }}
  capabilities:
    drop: ["ALL"]
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{/* The writable-/tmp scratch pair that makes readOnlyRootFilesystem feasible: an emptyDir volume + its
mount. Emitted as a container volumeMount via "lance.tmpMount" and a pod volume via "lance.tmpVolume" so a
read-only rootfs still has a place for pyarrow/Lance spill + OTel. Only needed when readOnlyRootFilesystem
is on; harmless (an unused tmpfs) when off, so unconditionally included keeps the templates uniform. */}}
{{- define "lance.tmpMount" -}}
- { name: tmp, mountPath: /tmp }
{{- end -}}
{{- define "lance.tmpVolume" -}}
- { name: tmp, emptyDir: {} }
{{- end -}}
