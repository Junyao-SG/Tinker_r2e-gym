{{/*
Expand the name of the chart.
*/}}
{{- define "r2e-eks.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "r2e-eks.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "r2e-eks.labels" -}}
helm.sh/chart: {{ include "r2e-eks.name" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels for orchestrator
*/}}
{{- define "r2e-eks.orchestrator.selectorLabels" -}}
app: {{ include "r2e-eks.fullname" . }}-orchestrator
{{- end }}

{{/*
Selector labels for proxy
*/}}
{{- define "r2e-eks.proxy.selectorLabels" -}}
app: {{ include "r2e-eks.fullname" . }}-proxy
{{- end }}

{{/*
Selector labels for vLLM
*/}}
{{- define "r2e-eks.vllm.selectorLabels" -}}
app: {{ include "r2e-eks.fullname" . }}-vllm
{{- end }}
