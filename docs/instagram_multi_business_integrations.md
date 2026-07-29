# Integraciones de Instagram multiempresa

## Arquitectura

La configuración global anterior combinaba una cuenta, un token y un slug por defecto.
Eso impedía aislar negocios y podía enrutar o enviar mensajes con la identidad equivocada.

La fuente de verdad es ahora:

```text
Instagram Business Account ID
  -> business_channel_integrations(provider=instagram, external_account_id)
  -> business_id
  -> conversaciones, automatización e incidencias de ese negocio
```

El webhook nunca selecciona el primer negocio ni usa un slug enviado por frontend. Para
un inbound resuelve por `recipient_id`; para un echo resuelve por `sender_id`. Una cuenta
no asociada se ignora con HTTP 200 después de validar la firma y genera una incidencia
segura sin el cuerpo del mensaje.

Los envíos cargan la integración por `business_id`, validan estado y caducidad,
descifran el token únicamente en memoria y lo pasan a la llamada de Meta. Una integración
no puede afectar el estado ni las incidencias de otra.

## Modelo

`business_channel_integrations` conserva el negocio, canal, proveedor, account ID único,
nombre, ciphertext, versión de clave, expiración, scopes, estado, fechas de actividad y
el último error seguro. Los estados son `pending`, `connected`, `degraded`, `expired`,
`disconnected`, `revoked` y `error`.

Existe una restricción única `(provider, external_account_id)`: una cuenta externa no
puede estar vinculada simultáneamente a dos negocios. Los tokens y el ciphertext nunca
forman parte de respuestas, auditorías o incidencias.

## Cifrado y variables

Los tokens se cifran con AES-256-GCM, nonce aleatorio de 96 bits, tag autenticado y datos
asociados que incluyen la versión. La base de datos guarda el paquete autenticado y
`encryption_key_version`; la clave sólo existe en el entorno.

Variables nuevas:

```dotenv
INTEGRATION_ENCRYPTION_KEYS_JSON={"v1":"CLAVE_BASE64_URLSAFE"}
INTEGRATION_ENCRYPTION_ACTIVE_KEY_VERSION=v1
```

Generar una clave nueva desde la raíz del repositorio:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -c "from app.services.integration_crypto_service import generate_encryption_key; print(generate_encryption_key())"
```

Guardar el resultado directamente en el gestor de secretos o en
`/etc/autonogrow/backend.env`, con permisos restringidos. No incluirlo en Git, tickets,
logs o capturas.

En local se permite no configurar claves mientras no existan credenciales cifradas ni
esté habilitado el proveedor. En staging/producción, habilitar Instagram exige un keyring
válido. Al arrancar se descifran de forma controlada todas las credenciales existentes;
una clave incorrecta, ciphertext manipulado o versión desconocida detiene el arranque.

## Rotación manual

1. Añadir la clave nueva sin retirar la antigua:

   ```dotenv
   INTEGRATION_ENCRYPTION_KEYS_JSON={"v1":"CLAVE_ANTIGUA","v2":"CLAVE_NUEVA"}
   INTEGRATION_ENCRYPTION_ACTIVE_KEY_VERSION=v2
   ```

2. Hacer backup y ejecutar:

   ```powershell
   $env:PYTHONPATH='backend'
   .\.venv\Scripts\python.exe scripts\rotate_integration_encryption.py
   ```

3. Reiniciar, verificar todas las integraciones y confirmar que usan `v2`.
4. Retirar `v1` del keyring sólo cuando ya no exista ninguna fila con esa versión.

El script sólo informa del número de integraciones recifradas; nunca imprime claves,
tokens ni ciphertext.

## Ciclo de vida y API

Endpoints owner:

- `GET /api/owner/businesses/{business_id}/integrations`
- `GET /api/owner/businesses/{business_id}/integrations/instagram`
- `POST /api/owner/businesses/{business_id}/integrations/instagram`
- `POST /api/owner/businesses/{business_id}/integrations/instagram/verify`
- `POST /api/owner/businesses/{business_id}/integrations/instagram/reconnect`
- `POST /api/owner/businesses/{business_id}/integrations/instagram/disconnect`
- `DELETE /api/owner/businesses/{business_id}/integrations/instagram/credentials`

El alta y la reconexión verifican con Meta que el token permite acceder al account ID
declarado antes de activar la integración. La verificación manual tiene protección ante
llamadas repetidas. Desconectar conserva temporalmente el ciphertext para permitir una
reconexión operativa; eliminar credenciales borra ciphertext, versión y datos del token.
Ninguna operación cambia `business_id` silenciosamente.

Endpoint admin de sólo lectura:

- `GET /api/admin/businesses/{slug}/integrations/status`

Devuelve únicamente `connected`, `needs_review` o `disconnected`, un texto seguro y la
caducidad. No contiene account ID, scopes, códigos OAuth ni acciones de gestión.

## Expiración, verificación e incidencias

Cuando `now >= token_expires_at`, el estado pasa a `expired`, se bloquea el proveedor y
se crea una incidencia deduplicada. El aviso visual de próxima expiración comienza siete
días antes. No existe un worker recurrente todavía; la evaluación se ejecuta al consultar
o usar la integración y queda preparada para una tarea programada futura.

Categorías específicas: `instagram_authentication`, `instagram_token_expired`,
`instagram_token_revoked`, `instagram_verification_failed`,
`instagram_unmapped_account` e `integration_decryption_failed`. La deduplicación incluye
negocio, integración, proveedor, código y operación. Una recuperación sólo resuelve las
incidencias de esa integración.

Auditorías: `instagram_integration_created`, `instagram_integration_verified`,
`instagram_integration_reconnected`, `instagram_integration_disconnected`,
`instagram_credentials_deleted`, `instagram_unmapped_account_received` e
`instagram_global_integration_migrated`. Sólo incluyen identificadores enmascarados y
metadatos operativos seguros.

## Migración desde variables globales

Las variables siguientes están deprecated y sólo se leen durante la migración inicial:

```dotenv
INSTAGRAM_ACCESS_TOKEN=
INSTAGRAM_BUSINESS_ACCOUNT_ID=
INSTAGRAM_DEFAULT_BUSINESS_SLUG=
```

En el primer arranque con las tres variables y un keyring válido se localiza el negocio,
se cifra el token, se crea una integración `pending` y se registra la auditoría. El proceso
es idempotente. Si falta la clave, el negocio o parte de la configuración, el arranque
falla claramente y nunca guarda el token en texto plano.

Después de verificar manualmente que la integración está `connected`, que llegan mensajes
y que los envíos usan la cuenta correcta, eliminar las tres variables deprecated del
entorno y reiniciar. Envío y routing ya no las consultan.

## Permisos

| Acción | Owner | Business admin | Staff | Cliente |
|---|---:|---:|---:|---:|
| Ver estado simplificado | Sí | Sí, propio | No | No |
| Conectar | Sí | No | No | No |
| Verificar | Sí | No | No | No |
| Reconectar | Sí | No | No | No |
| Desconectar | Sí | No | No | No |
| Eliminar credenciales | Sí | No | No | No |
| Ver account ID enmascarado | Sí | No | No | No |
| Ver errores técnicos seguros | Sí | No | No | No |
| Recibir mensajes | Según integración | Negocio propio | Negocio propio | No |
| Enviar mensajes | Gestión interna | Negocio propio | Negocio propio | No |

## Despliegue, rollback y prueba manual

Antes de desplegar, detener escrituras o usar una ventana controlada y respaldar SQLite y
uploads:

```powershell
.\.venv\Scripts\python.exe scripts\backup_sqlite_uploads.py --database <db> --uploads <uploads> --output-dir <backups>
```

Actualizar dependencias para instalar `cryptography`, configurar el keyring, conservar
temporalmente las variables globales y arrancar una sola instancia para aplicar la
migración. Verificar que el ciphertext no coincide con el token, que el mapping es correcto
y que el token no aparece en logs. Después probar dos cuentas simultáneas, inbound, echo,
envío, expiración, reconexión, desconexión, borrado, incidencias y auditoría.

Para rollback, detener el servicio, restaurar la base de datos y uploads del backup,
restaurar el código anterior y su entorno. Conservar de forma segura las claves usadas por
el backup: sin ellas no se pueden recuperar sus tokens cifrados. No intentar copiar tokens
desde el ciphertext ni activar un fallback global silencioso.
