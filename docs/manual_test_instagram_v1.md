# Prueba manual: Instagram API v1 segura

## Alcance

Esta versión conecta una única cuenta profesional de Instagram mediante configuración global. No incluye OAuth por negocio, adjuntos outbound, reintentos ni estados avanzados. El proveedor y las automatizaciones continúan desactivados por defecto.

## 1. Requisitos en Meta

- Cuenta profesional de Instagram.
- Página de Facebook/Meta vinculada cuando lo requiera el flujo elegido.
- Aplicación en Meta for Developers.
- Producto y permisos de mensajería de Instagram habilitados.
- URL HTTPS pública para el webhook.
- Token de acceso válido para la cuenta profesional.
- Suscripción a los eventos de mensajería necesarios.

Antes de usarlo con clientes reales hay que completar las revisiones y cumplir las políticas y ventanas de mensajería vigentes de Meta.

## 2. Variables de configuración

Configura estas variables únicamente en el fichero privado del servidor, nunca en Git:

```dotenv
META_APP_ID=
META_APP_SECRET=
META_VERIFY_TOKEN=
META_GRAPH_API_VERSION=v23.0
INSTAGRAM_ACCESS_TOKEN=
INSTAGRAM_BUSINESS_ACCOUNT_ID=
INSTAGRAM_DEFAULT_BUSINESS_SLUG=
INSTAGRAM_PROVIDER_ENABLED=false
INSTAGRAM_REQUIRE_SIGNATURE=true
```

- `META_VERIFY_TOKEN`: valor privado elegido para completar la verificación GET.
- `META_APP_SECRET`: secreto utilizado para validar `X-Hub-Signature-256`.
- `INSTAGRAM_ACCESS_TOKEN`: token usado exclusivamente en la cabecera de autorización hacia Meta.
- `INSTAGRAM_BUSINESS_ACCOUNT_ID`: cuenta profesional destinataria utilizada para filtrar y mapear los webhooks.
- `INSTAGRAM_DEFAULT_BUSINESS_SLUG`: negocio AutonoGrow al que se asignan los inbound de esa cuenta.
- `INSTAGRAM_PROVIDER_ENABLED`: habilita los envíos reales. Debe permanecer `false` hasta completar la configuración.
- `INSTAGRAM_REQUIRE_SIGNATURE`: debe ser `true` en staging y producción.

La configuración de producción rechaza el arranque si se desactiva la firma o si se habilita el proveedor con campos obligatorios vacíos.

## 3. Configurar el webhook

Registra en Meta esta URL:

```text
https://staging.autonogrow.es/api/webhooks/instagram
```

Usa como token de verificación exactamente el valor privado de `META_VERIFY_TOKEN`.

## 4. Verificación GET

Ejemplo de comprobación, sustituyendo el token por el valor configurado fuera del repositorio:

```bash
curl "https://staging.autonogrow.es/api/webhooks/instagram?hub.mode=subscribe&hub.verify_token=TU_VERIFY_TOKEN&hub.challenge=12345"
```

Debe devolver `12345` como texto plano. Un modo o token incorrecto devuelve `403`.

## 5. Simulación local

Solo en local puede configurarse temporalmente:

```dotenv
INSTAGRAM_REQUIRE_SIGNATURE=false
```

Ejemplo inbound de texto:

```bash
curl -X POST "http://127.0.0.1:8000/api/webhooks/instagram" \
  -H "Content-Type: application/json" \
  -d '{"object":"instagram","entry":[{"id":"IG_BUSINESS_ID","messaging":[{"sender":{"id":"IG_SCOPED_USER_ID"},"recipient":{"id":"IG_BUSINESS_ID"},"timestamp":1750000000000,"message":{"mid":"TEST-MID-001","text":"Hola"}}]}]}'
```

Usa valores ficticios en local. Para staging y producción no desactives la firma: Meta enviará `X-Hub-Signature-256`, calculada sobre el body original con `META_APP_SECRET`.

## 6. Probar inbound real

1. Mantén configurados el ID de cuenta, el slug de negocio y la firma obligatoria.
2. Envía un DM desde una cuenta distinta a la cuenta profesional.
3. Abre **Admin > Conversaciones**.
4. Comprueba que se creó o reutilizó una conversación Instagram para el sender.
5. Comprueba el texto, la intención y cualquier sugerencia generada.
6. Reenvía el mismo evento o `mid`: no debe duplicarse.

Los adjuntos sin texto se guardan como `[Adjunto recibido]`. Eventos de lectura, reacciones, postbacks sin mensaje, echoes y mensajes emitidos por la propia cuenta se ignoran en v1.

## 7. Probar outbound manual

1. Con `INSTAGRAM_PROVIDER_ENABLED=false`, responde desde Admin.
2. El mensaje debe mostrarse como **Modo interno** y no se realiza ninguna llamada externa.
3. Completa la configuración privada y cambia `INSTAGRAM_PROVIDER_ENABLED=true`.
4. Reinicia el backend de acuerdo con el runbook del entorno.
5. Responde otra vez desde Admin.
6. Comprueba que el mensaje llega al usuario y aparece como **Enviado**, con `provider_message_id` interno.

Si Meta rechaza el envío, el mensaje queda como **Fallido**, la conversación permanece pendiente y Admin muestra un error seguro sin tokens.

## 8. Sugerencias y automático seguro

- **Enviar sugerencia** y una sugerencia modificada usan el mismo provider que el envío manual, con `sender_type=business` y sin consumir crédito automático.
- Un automático seguro usa Meta únicamente después de pasar las reglas existentes de intención, umbral, plantilla y límite.
- Si Meta rechaza un automático, queda `failed`, la conversación vuelve a pendiente y no se consume crédito.
- Si el provider está deshabilitado, el automático conserva el modo interno `simulated`.
- Activar el provider no activa las automatizaciones; son controles independientes y ambos permanecen apagados por defecto.

## 9. Limitaciones v1

- Un token y una cuenta global para staging.
- Sin OAuth ni credenciales independientes por negocio.
- Sin App Review completa automatizada.
- Sin adjuntos outbound avanzados.
- Sin reintentos ni cola específica del provider.
- Sin recibos de entrega o lectura avanzados.
- Sin refresco automático de tokens.
- Automatización real desactivada por defecto.
- La operación debe respetar las políticas y ventanas de mensajería de Meta.
