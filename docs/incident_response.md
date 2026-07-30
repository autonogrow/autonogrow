# Respuesta a incidentes

Clasificar severidad y alcance; preservar evidencia segura; activar mantenimiento si hay riesgo de escritura; confirmar DB, worker, colas, disco, backups e integraciones. No copiar payloads, tokens ni datos personales a tickets o logs.

Para recuperación: identificar release, asegurar backup, comprobar manifest, restaurar solo en destino temporal, decidir corrección hacia delante/rollback/restore y obtener aprobación para pérdida. Al cerrar, resolver incidencia, emitir recuperación solo si hubo aviso, documentar tiempos/causa/acciones y crear seguimiento preventivo.
