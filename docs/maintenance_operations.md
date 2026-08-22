# Operaciones de mantenimiento

El modo se guarda en `operational_states`; no requiere editar env ni reiniciar. `manage_maintenance.py status|enable|disable` exige `--apply` para cambiar y audita el motivo. Bloquea escrituras públicas y nuevas reservas con 503; permite owner, probes, métricas protegidas y webhooks almacenables. El worker continúa o pausa según política documentada.

`run_maintenance.py` es seco por defecto. Además de planificar la limpieza de historial terminal antiguo y heartbeats detenidos/erróneos, evalúa idempotentemente oportunidades y señales agregadas de crecimiento, y cancela drafts de acción vencidos a los 7 días; en seco revierte todo. Nunca elimina pendientes, dead letters, incidencias abiertas, reservas, conversaciones, oportunidades, señales, acciones, atribuciones ni backups protegidos. `--task growth-opportunities --apply --json` ejecuta el detector individual; `--task growth-signals --apply --json` ejecuta ocupación, pools, retorno, demanda y eventos usando las oportunidades ya actualizadas.

Los evaluadores de oportunidades y señales consultan la capability del business y no crean trabajo
Growth cuando el módulo está apagado. El evaluador de inteligencia de contenido aplica la misma
regla a Social. Esta omisión es business-scoped: no cambia flags globales, no borra historial y no
habilita publisher ni workers.

La reconciliacion de uploads se solicita de forma independiente con `--task storage-reconciliation --json` y no forma parte del timer por defecto. Reporta ficheros huerfanos, referencias sin fichero y paths invalidos sin modificar nada. Solo `--task storage-reconciliation --apply --json` puede borrar candidatos no referenciados con al menos 24 horas de antiguedad; antes de aplicarlo se requiere backup y revision del reporte. El detalle de namespaces, protecciones y politica pendiente esta en `backend_pilot_robustness.md`.

En staging, `autonogrow-maintenance.service` se ejecuta como `deploy` desde `/opt/autonogrow`, usa
`/etc/autonogrow/backend.env` y el Python `/opt/autonogrow/backend/.venv-next/bin/python`. El único
path escribible concedido por systemd es `/run/lock`, necesario para `flock`; el mantenimiento
persiste sus cambios en PostgreSQL y no necesita escribir en el storage de uploads. El timer corre
a las 04:30 con hasta 10 minutos de jitter. Así empieza al menos 45 minutos después del backup
diario de las 03:30, incluso cuando este consume sus 15 minutos completos de jitter.
