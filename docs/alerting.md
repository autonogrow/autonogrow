# Alertas operativas

`run_operational_checks.py` ejecuta una sola iteración y sale 0/1/2/3 para ok/warning/critical/error técnico. Evalúa readiness, workers, backlog, antigüedad, dead letters, disco y edad de backup. `--dry-run`, `--no-notify`, `--json` y `--component` permiten comprobaciones seguras.

Las alertas se deduplican por fingerprint en `system_incidents`, respetan cooldown y se resuelven automáticamente. La recuperación solo se notifica si la apertura fue notificada. Email/webhook permanecen desactivados hasta configurar destinos reales fuera de Git.
# Salud Meta

Owner muestra prioridad operativa por `health_status`, última/próxima comprobación, fallos, error seguro y acciones. `revoked`, `suspended` y errores bloqueantes deshabilitan la disponibilidad efectiva sin cambiar el permiso comercial. El runbook aplicable es `meta_integration_recovery_runbook.md`.
