# Activación y suspensión

`POST /api/owner/businesses/{id}/activate` requiere owner, motivo y `expected_readiness_version`. Bloquea la fila en PostgreSQL, recalcula readiness, rechaza cambios concurrentes con 409, transiciona por `ready`, fija actor/fecha, quita `noindex` y completa la sesión. Repetir sobre un negocio activo es idempotente.

`suspend` conserva todo y vuelve a aplicar `noindex`; `reactivate` repite readiness; `archive` no borra histórico. No existe activación mediante PATCH genérico y el business admin no modifica estados comerciales. Preview también exige owner, siempre devuelve noindex, reservas deshabilitadas, automatizaciones deshabilitadas y consumo de créditos falso.
