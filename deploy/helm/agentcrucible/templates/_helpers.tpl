{{- define "agentcrucible.fullname" -}}{{ .Release.Name }}-crucible{{- end -}}

{{- define "agentcrucible.runId" -}}{{ .Release.Name }}-r{{ .Release.Revision }}{{- end -}}

{{- define "agentcrucible.labels" -}}
app.kubernetes.io/name: agentcrucible
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "agentcrucible.podSecurity" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  fsGroup: 10001
  seccompProfile: { type: RuntimeDefault }
{{- end -}}

{{- define "agentcrucible.containerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities: { drop: ["ALL"] }
{{- end -}}

{{- define "agentcrucible.env" -}}
- name: CRUCIBLE_LLM_URL
  value: {{ .Values.llm.baseUrl | quote }}
{{- if .Values.llm.apiKeySecret }}
- name: CRUCIBLE_LLM_API_KEY
  valueFrom: { secretKeyRef: { name: {{ .Values.llm.apiKeySecret }}, key: api-key } }
{{- end }}
- name: CRUCIBLE_RUN_ID
  value: {{ include "agentcrucible.runId" . | quote }}
- name: HOME
  value: /tmp
{{- end -}}

{{- define "agentcrucible.volumes" -}}
volumes:
  - name: results
    persistentVolumeClaim: { claimName: {{ include "agentcrucible.fullname" . }}-results }
  - name: tmp
    emptyDir: {}
{{- end -}}

{{- define "agentcrucible.mounts" -}}
volumeMounts:
  - { name: results, mountPath: {{ .Values.workdir }}/.crucible }
  - { name: tmp, mountPath: /tmp }
{{- end -}}
