# Sprint 4A — Control Owner y onboarding de canales

## Alcance

Este sprint incorpora el control previo a cualquier conexión oficial con Meta. El onboarding
de WhatsApp sigue siendo controlado/simulado. Desde Sprint 4B, Instagram usa Instagram
Login real y nunca recibe contraseñas en AutonoGrow.

Las integraciones creadas antes de este sprint se marcan como `legacy` durante la migración.
Las solicitudes nuevas de Instagram usan `oauth`; la simulación Instagram solo existe en
tests con `APP_ENV=test` y un flag explícito.

## Estados

```text
not_allowed (sin fila)
    -> available             Owner concede el permiso
    -> pending_approval      Meta autoriza una candidatura Instagram o se solicita WhatsApp
    -> approved              Owner revisa y aprueba
    -> suspended/revoked     Owner detiene el acceso y apaga capacidades
```

Volver a conceder un canal suspendido o revocado lo deja en `available`; requiere una nueva
solicitud y aprobación. La aprobación siempre deja apagados tanto el envío integrado como la
automatización. El Owner los activa después y por separado.

## Políticas y seguridad

- `business_admin`: un administrador activo del mismo negocio puede solicitar la conexión.
- `owner_only`: solo el Owner puede iniciar el enlace asistido para ese negocio.
- Un miembro `business_staff` y un administrador de otro negocio reciben `403`.
- Las capacidades solo son efectivas con estado `approved` y su flag específico activo.
- Suspender o revocar apaga ambos flags de forma atómica.
- Cada concesión, solicitud, aprobación, cambio de capacidad, suspensión y revocación genera
  un registro de auditoría sin secretos.

## API

Cliente:

- `GET /api/admin/businesses/{slug}/channel-onboarding`
- `POST /api/admin/businesses/{slug}/channel-onboarding/{channel}/request`
- `POST /api/admin/businesses/{slug}/integrations/instagram/oauth/start`

Owner:

- `GET /api/owner/businesses/{id}/channel-controls`
- `PUT /api/owner/businesses/{id}/channel-controls/{channel}/access`
- `POST /api/owner/businesses/{id}/channel-controls/{channel}/request`
- `POST /api/owner/businesses/{id}/channel-controls/{channel}/approve`
- `PATCH /api/owner/businesses/{id}/channel-controls/{channel}/capabilities`
- `POST /api/owner/businesses/{id}/channel-controls/{channel}/suspend`
- `POST /api/owner/businesses/{id}/channel-controls/{channel}/revoke`

Los contratos de control no contienen credenciales. La candidatura OAuth temporal vive en
`instagram_oauth_attempts` y la integración aprobada en `business_channel_integrations`.
