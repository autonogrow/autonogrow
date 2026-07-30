# Operaciones de mantenimiento

El modo se guarda en `operational_states`; no requiere editar env ni reiniciar. `manage_maintenance.py status|enable|disable` exige `--apply` para cambiar y audita el motivo. Bloquea escrituras públicas y nuevas reservas con 503; permite owner, probes, métricas protegidas y webhooks almacenables. El worker continúa o pausa según política documentada.

`run_maintenance.py` es seco por defecto y solo elimina historial terminal antiguo y heartbeats detenidos/erróneos. Nunca elimina pendientes, dead letters, incidencias abiertas, reservas, conversaciones ni backups protegidos.
