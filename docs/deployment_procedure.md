# Procedimiento de despliegue

Usar releases identificables y un enlace `current` intercambiable atómicamente; el código anterior permanece disponible. `deploy_release.py` produce un plan de veinte pasos y nunca hace git pull. Antes de aplicar: CI verde, árbol limpio, release metadata, GO/NO-GO, espacio, backup conjunto verificado y rollback preparado.

Orden: mantenimiento, detener worker, instalar lock, migrar hacia delante, cambiar release, backend, readiness, worker/heartbeat, smoke y retirar mantenimiento. `--skip-backup` exige confirmación fuerte. El script no ejecuta cambios de servicio automáticamente tras predeploy: seguir el runbook con operador.
