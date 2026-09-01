# Sesiones de autenticación revocables

AutonoGrow usa una sesión server-side por login/dispositivo. La cookie
`autonogrow_session` contiene únicamente un token aleatorio opaco firmado; identidad,
Owner y memberships nunca se almacenan en ella. La base conserva sólo SHA-256 del token.

Cada sesión expira a los siete días. Una sesión expirada se marca revocada al intentar
usarla y se elimina oportunistamente cuando el mismo usuario vuelve a iniciar sesión.
Una fila revocada o expirada nunca vuelve a autorizar.

- `POST /api/auth/logout` revoca sólo la sesión actual, borra sesión y CSRF y es
  idempotente incluso con cookie ausente, corrupta, legacy, expirada o ya revocada.
- `POST /api/auth/logout-all` revoca todas las sesiones del usuario autenticado.
- `POST /api/auth/users/{user_id}/sessions/revoke-all` permite recuperación de seguridad
  únicamente a Owner global.

Logout normal está exento del middleware CSRF para garantizar que siempre pueda limpiar
el navegador. Las demás mutaciones, incluido logout-all, conservan CSRF. Cookies legacy
con `{user_id}` no tienen fallback: reciben 401 y requieren un nuevo login.

Retirar Owner o membership no revoca de forma implícita todas las sesiones: ambos permisos
se consultan en DB en cada petición. Un usuario inactivo conserva el contrato 403 existente
y deja de autorizar inmediatamente. Los eventos de auditoría `session_created`,
`session_revoked` y `all_sessions_revoked` registran ids internos, nunca tokens ni cookies.
