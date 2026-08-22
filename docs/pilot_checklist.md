# Checklist reutilizable de piloto

## Identidad y módulos

- [ ] Business, slug, timezone y contacto correctos.
- [ ] Business Admin correcto; acceso ajeno rechazado.
- [ ] Essential activo; Growth/Social reflejan lo acordado.
- [ ] Integración, health, worker y entitlement no se confunden.

## Operación y cliente

- [ ] Servicio reservable, horario, reglas y personal si aplica.
- [ ] Checklist Admin sin bloqueos y `booking_ready=true`.
- [ ] Página pública móvil, contacto y CTA correctos.
- [ ] Reserva invitada, confirmación, calendario, login opcional, repeat y logout comprobados.
- [ ] Empty states explican qué aparecerá y la siguiente acción.

## Comunicación, seguridad y medición

- [ ] WhatsApp assisted probado; Cloud marcado opcional si no disponible.
- [ ] Instagram comprobado solo si Social activo; publisher sigue disabled/inactive.
- [ ] Roles, CSRF, signed media e IDOR tenant-scoped comprobados.
- [ ] Baseline registrada si aporta valor, con fuente y sin claim causal.
- [ ] Essential managed value, Growth attribution y Social operational value visibles.
- [ ] ROI oculto/unavailable si no hay coste o atribución suficiente.

## Recovery y activación

- [ ] `scripts/check_pilot_configuration.py --json` sin inconsistencias.
- [ ] Backup DB/uploads verificado e identificado; restore procedure conocido.
- [ ] Build SHA/release identificado; migración en head.
- [ ] Health/smoke correctos y warnings aceptados explícitamente.
- [ ] `pilot_ready=true` o deuda aceptada documentada.
- [ ] Responsable, canal de soporte y plantilla de incidencia compartidos.
