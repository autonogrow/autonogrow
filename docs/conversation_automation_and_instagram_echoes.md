# Automatización por conversación y ecos de Instagram

## Despliegue en staging

1. Haz una copia de seguridad de la base de datos y configura las variables habituales de staging.
2. Despliega backend y panel admin con el procedimiento normal, sin cambiar secretos de Meta.
3. Arranca el backend una vez. `create_db_and_tables()` ejecuta la migración ligera que añade las columnas de estado a `conversations` y `human_reply_pause_minutes` a `conversation_automation_settings`.
4. Desde el directorio `backend`, ejecuta el upsert idempotente del catálogo:

   ```powershell
   ..\.venv\Scripts\python.exe -m app.automation_upsert
   ```

   En el servidor Linux, usa el Python del entorno virtual equivalente. El comando añade únicamente plantillas y reglas ausentes; no modifica textos personalizados ni crea duplicados.
5. Reinicia el servicio backend y publica los archivos estáticos del panel admin.
6. Comprueba una empresa existente en **Centro de conversaciones > Automatización**: deben aparecer `complaint_intent`, `human_intent`, `cancel_reschedule_intent` y `unknown`, inicialmente desactivadas.

## Suscripción de Meta

La aplicación de Meta debe mantener el webhook de Instagram suscrito al campo `messages`/`message`, que incluye los eventos de mensajes y sus *message echoes*. El echo se reconoce por `message.is_echo=true` y por el sentido negocio → cliente (`sender.id` es la cuenta profesional y `recipient.id` es el cliente). Referencia del payload: [Meta Instagram API — Messaging webhook](https://www.postman.com/meta/instagram/request/23987686-95cce6f6-b811-41dc-b560-d43741c5002a).

La suscripción se verifica en Meta for Developers, en la configuración de webhooks del producto Instagram. Este cambio no modifica esa configuración externa. Tras comprobarla, envía una respuesta desde la app de Instagram y confirma que el endpoint `/api/webhooks/instagram` recibe un evento con `message.mid`; no registres el cuerpo ni tokens durante la comprobación.

## Prueba manual con Instagram

1. Abre en AutonoGrow una conversación de Instagram con automatización activa.
2. Responde desde la app o web de Instagram del negocio.
3. Espera el siguiente ciclo de polling y verifica que aparece un único mensaje outbound, con estado enviado.
4. Confirma que la cabecera muestra una pausa aproximada de una hora y el texto “Pausada por respuesta humana”.
5. Escribe como cliente un mensaje que normalmente active una regla automática.
6. Verifica que el inbound se guarda y clasifica, pero no recibe respuesta automática; una sugerencia puede seguir apareciendo.
7. Pulsa **Activar automatización** en AutonoGrow.
8. Envía otro mensaje como cliente y confirma que la automatización vuelve a funcionar.
9. Selecciona **Hasta reactivarla**, pulsa **Pausar automatización** y repite el envío del cliente.
10. Confirma que el indicador muestra **Modo manual**, que no hay respuesta automática y que el envío manual sigue disponible.
11. En la configuración global, revisa **Pausa tras respuesta humana** y confirma que las cuatro reglas nuevas pueden cambiar entre automático, sugerencia y desactivado.

Para validar la reconciliación, envía también un texto desde el panel con el proveedor real activo: al llegar el echo con el mismo `mid` (o una coincidencia única reciente sin `mid`) debe mantenerse un solo mensaje en el hilo.
