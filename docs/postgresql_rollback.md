# Rollback PostgreSQL

## Antes de abrir tráfico

Detener worker y backend, conservar informe y logs saneados, restaurar la configuración SQLite
anterior y arrancar una versión compatible. Verificar head, health, login, reservas y colas. El
SQLite usado debe ser el snapshot original, no una copia modificada durante ensayos.

## Después de aceptar escrituras en PostgreSQL

Es el punto de no retorno automático. No cambiar `DATABASE_URL` a SQLite: faltarían escrituras. Las
opciones son corregir hacia delante, restaurar PostgreSQL desde backup con pérdida aprobada o diseñar
y validar una migración inversa. El SQLite original queda solo como evidencia histórica pre-corte.

## Decisión

- GO: backups verificados, migración íntegra, secuencias válidas, tests y observación sin bloqueantes.
- NO-GO: diferencia de datos, ciphertext/saldo inválido, head incorrecta, error de concurrencia o
  backup no restaurable.
- ROLLBACK: solo antes de tráfico, o después mediante un plan de recuperación aprobado que declare
  RPO, RTO y pérdida de datos.
