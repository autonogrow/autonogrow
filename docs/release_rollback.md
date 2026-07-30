# Rollback de release

Distinguir rollback de código pretráfico, código compatible tras tráfico, migración irreversible y restore con pérdida de datos. `rollback_release.py` es seco, exige release objetivo y nunca baja Alembic ni restaura automáticamente.

Confirmar compatibilidad de la release anterior con la head actual, activar mantenimiento, parar worker, cambiar enlace, arrancar, comprobar readiness/smoke y registrar. Si el esquema no es compatible, corregir hacia delante o preparar restore aprobado con evaluación de pérdida.
