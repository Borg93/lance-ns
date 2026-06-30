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
- { name: OTEL_LOGS_EXPORTER, value: "otlp" }
{{/* Default metric export interval is 60s — too slow to observe in a demo/test. Push every 5s. */}}
- { name: OTEL_METRIC_EXPORT_INTERVAL, value: "5000" }
- { name: OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED, value: "true" }
- { name: OTEL_RESOURCE_ATTRIBUTES, value: "service.namespace=lance-ns,deployment.environment=kind,service.version={{ $root.Chart.AppVersion }}" }
{{- end -}}

