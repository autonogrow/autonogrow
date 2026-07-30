# Métricas

`METRICS_ENABLED=false` es el valor seguro. Al habilitarlo, `METRICS_ALLOWED_IPS` admite por defecto solo loopback o se exige token Bearer comparado en tiempo constante. No se confía en `X-Forwarded-For`; Caddy bloquea `/internal/*` externamente.

Las métricas usan labels acotadas: método, ruta declarada, clase HTTP, estado de cola/integración/reserva. Nunca incluyen business_id, emails, rutas locales, URL de DB o payloads. Incluyen HTTP, pool, workers, colas, integraciones, reservas, incidencias y última copia.
