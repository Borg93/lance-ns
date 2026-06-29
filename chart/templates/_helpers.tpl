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
{{- define "lance.jaegerHost" -}}{{ .Release.Name }}-jaeger{{- end -}}
{{- define "lance.otelHost" -}}{{ .Release.Name }}-otel-collector{{- end -}}

{{/* OTel SDK env for an app (call: include "lance.otelEnv" (list $root "<service.name>")). The apps run
under `opentelemetry-instrument`; this exports all three signals over OTLP to the Collector. */}}
{{- define "lance.otelEnv" -}}
{{- $root := index . 0 -}}
{{- $svc := index . 1 -}}
- { name: OTEL_SERVICE_NAME, value: {{ $svc | quote }} }
- { name: OTEL_EXPORTER_OTLP_ENDPOINT, value: "http://{{ include "lance.otelHost" $root }}:{{ $root.Values.observability.collectorPort }}" }
- { name: OTEL_EXPORTER_OTLP_PROTOCOL, value: "grpc" }
- { name: OTEL_TRACES_EXPORTER, value: "otlp" }
- { name: OTEL_METRICS_EXPORTER, value: "otlp" }
- { name: OTEL_LOGS_EXPORTER, value: "otlp" }
- { name: OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED, value: "true" }
- { name: OTEL_RESOURCE_ATTRIBUTES, value: "service.namespace=lance-ns,deployment.environment=kind" }
{{- end -}}

