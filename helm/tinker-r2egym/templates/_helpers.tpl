{{/*
Expand the name of the chart.
*/}}
{{- define "tinker-r2egym.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "tinker-r2egym.fullname" -}}
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
{{- define "tinker-r2egym.labels" -}}
helm.sh/chart: {{ include "tinker-r2egym.name" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels for orchestrator
*/}}
{{- define "tinker-r2egym.orchestrator.selectorLabels" -}}
app: {{ include "tinker-r2egym.fullname" . }}-orchestrator
{{- end }}

{{/*
Selector labels for proxy
*/}}
{{- define "tinker-r2egym.proxy.selectorLabels" -}}
app: {{ include "tinker-r2egym.fullname" . }}-proxy
{{- end }}
