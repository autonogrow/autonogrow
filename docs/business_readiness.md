# Readiness de negocio

`business_readiness_service.py` es la fuente derivada y read-only. Evalúa identity, contact,
services, staff, schedules, booking, branding, landing, automations, integrations, credits, security
y módulos. Cada check conserva estado, severidad, mensaje, remediación, bloqueo y paso relacionado.
No se persiste un JSON de progreso ni un `onboarding_step` duplicado.

La respuesta V2 separa:

- `booking_ready`: no hay blockers que impidan recibir una reserva;
- `pilot_ready`: booking está listo y existen Business Admin, contacto público, landing activa y
  condiciones operativas mínimas;
- `modules`: readiness por Essential/Growth/Social, distinguiendo `ready`, `action_required` y
  `disabled`;
- `blocking`, `pilot_blocking`, `warnings` y `optional`: razones accionables, sin secretos.

Son blockers de booking la identidad inválida, cero servicios reservables, horario ausente/inválido,
reglas incoherentes y negocio archivado, junto a invariantes operativas ya existentes. Logo, galería,
SEO, WhatsApp Cloud y módulos no contratados no bloquean. La falta de backup verificado del entorno
es warning operativo; debe resolverse/aceptarse antes del piloto real. Social activo con Instagram
degradado queda `action_required`, pero no vuelve falso `pilot_ready` por sí solo; Social apagado no
genera warning. Essential es obligatorio y su readiness sigue booking readiness.

`ready`, score, checks y versión se conservan para compatibilidad con la activación existente. La
puntuación es el porcentaje estable de checks aplicables superados y nunca sustituye el análisis de
blockers. La evidencia se vuelve a comprobar dentro de la transacción de activación.
