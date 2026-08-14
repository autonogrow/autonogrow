# Operaciones de mantenimiento

El modo se guarda en `operational_states`; no requiere editar env ni reiniciar. `manage_maintenance.py status|enable|disable` exige `--apply` para cambiar y audita el motivo. Bloquea escrituras públicas y nuevas reservas con 503; permite owner, probes, métricas protegidas y webhooks almacenables. El worker continúa o pausa según política documentada.

`run_maintenance.py` es seco por defecto. Además de planificar la limpieza de historial terminal antiguo y heartbeats detenidos/erróneos, evalúa idempotentemente oportunidades de crecimiento; en seco revierte todo. Nunca elimina pendientes, dead letters, incidencias abiertas, reservas, conversaciones ni backups protegidos. `--task growth-opportunities --apply --json` ejecuta solo el detector.
