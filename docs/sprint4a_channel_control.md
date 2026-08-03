# Sprint 4A — Control Owner y onboarding de canales

## Alcance

Este sprint incorpora el control previo a cualquier conexión oficial con Meta. El onboarding
disponible para Instagram y WhatsApp es simulado y nunca recibe tokens, contraseñas,
identificadores de cuenta ni códigos OAuth.

Las integraciones creadas antes de este sprint se marcan como `legacy` durante la migración.
Las solicitudes nuevas usan exclusivamente `simulated`.

## Estados

```text
not_allowed (sin fila)
    -> available             Owner concede el permiso
    -> pending_approval      administrador autorizado solicita conexión simulada
    -> approved              Owner revisa y aprueba
    -> suspended/revoked     Owner detiene el acceso y apaga capacidades
```

Volver a conceder un canal suspendido o revocado lo deja en `available`; requiere una nueva
solicitud y aprobación. La aprobación siempre deja apagados tanto el envío integrado como la
automatización. El Owner los activa después y por separado.

## Políticas y seguridad

- `business_admin`: un administrador activo del mismo negocio puede solicitar la conexión.
- `owner_only`: solo el Owner puede ejecutar la solicitud simulada.
- Un miembro `business_staff` y un administrador de otro negocio reciben `403`.
- Las capacidades solo son efectivas con estado `approved` y su flag específico activo.
- Suspender o revocar apaga ambos flags de forma atómica.
- Cada concesión, solicitud, aprobación, cambio de capacidad, suspensión y revocación genera
  un registro de auditoría sin secretos.

## API

Cliente:

- `GET /api/admin/businesses/{slug}/channel-onboarding`
- `POST /api/admin/businesses/{slug}/channel-onboarding/{channel}/request`

Owner:

- `GET /api/owner/businesses/{id}/channel-controls`
- `PUT /api/owner/businesses/{id}/channel-controls/{channel}/access`
- `POST /api/owner/businesses/{id}/channel-controls/{channel}/request`
- `POST /api/owner/businesses/{id}/channel-controls/{channel}/approve`
- `PATCH /api/owner/businesses/{id}/channel-controls/{channel}/capabilities`
- `POST /api/owner/businesses/{id}/channel-controls/{channel}/suspend`
- `POST /api/owner/businesses/{id}/channel-controls/{channel}/revoke`

No existe en estos contratos ningún campo para credenciales o activos externos de Meta.
