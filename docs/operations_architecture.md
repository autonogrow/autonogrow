# Arquitectura operativa

La capa operativa separa cuatro superficies: `/health` solo confirma proceso vivo; `/ready` decide entrada en tráfico; `/internal/metrics` entrega agregados protegidos; y `/api/owner/system/health` expone diagnóstico seguro solo al owner global.

PostgreSQL conserva mantenimiento, metadatos de backup, heartbeats, colas, incidencias y auditoría. `system_incidents` deduplica alertas; no se almacenan payloads ni secretos operativos nuevos. Los scripts son secos por defecto y systemd solo aporta ejemplos no activados.
