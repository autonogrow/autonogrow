# Readiness de negocio

`business_readiness_service.py` evalúa de forma central identity, contact, services, staff, schedules, booking, branding, landing, automations, integrations, credits y security. Cada check devuelve estado, severidad, mensaje, remediación, bloqueo y paso relacionado.

Son bloqueantes: identidad inválida, cero servicios reservables, horario ausente/inválido, reglas incoherentes, wallet ausente cuando la automatización está habilitada, migración pendiente y negocio archivado. Logo, galería, SEO e integraciones opcionales generan advertencias.

La puntuación es el porcentaje estable de checks aplicables superados (warnings cuentan como no superados) y nunca sustituye a `blocking_count == 0`. La versión es un hash de la evidencia evaluada y se vuelve a comprobar dentro de la transacción de activación.
