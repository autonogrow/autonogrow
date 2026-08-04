# Métricas

`METRICS_ENABLED=false` es el valor seguro. Al habilitarlo, `METRICS_ALLOWED_IPS` admite por defecto solo loopback o se exige token Bearer comparado en tiempo constante. No se confía en `X-Forwarded-For`; Caddy bloquea `/internal/*` externamente.

Las métricas usan labels acotadas: método, ruta declarada, clase HTTP, estado de cola/integración/reserva. Nunca incluyen business_id, emails, rutas locales, URL de DB o payloads. Incluyen HTTP, pool, workers, colas, integraciones, reservas, incidencias y última copia.
# Integraciones Meta

Sprint 4D expone series `autonogrow_meta_integration_*` para estado de health, jobs por tipo/estado, checks programados/iniciados/completados/fallidos, duración, job pendiente más antiguo y última limpieza. Los eventos de recuperación, reconexión, reparación y destrucción de candidaturas se cuentan desde auditoría. Las etiquetas nunca contienen negocio, cuenta, teléfono ni IDs Meta para evitar cardinalidad y exposición.
