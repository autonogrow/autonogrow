# Prueba manual: Automatizaciones de conversaciones v1

## Alcance y seguridad

Esta versión trabaja con plantillas aprobadas del Centro de conversaciones y no usa IA. Puede recibir y enviar Instagram mediante la integración v1 cuando está configurada; sin provider conserva el modo interno `simulated`. Consulta `docs/manual_test_instagram_v1.md`.

La automatización está desactivada por defecto en todos los negocios. Abrir el panel o recibir mensajes no la activa.

## 1. Activar la automatización

1. Inicia sesión como owner o `business_admin`.
2. Abre **Admin > Conversaciones**.
3. Despliega **Automatización**.
4. Revisa el límite del periodo y el umbral automático.
5. Marca **Activar automatización** y pulsa **Guardar configuración**.

Un usuario `business_staff` puede consultar y gestionar sugerencias, pero no ve ni puede editar esta configuración.

## 2. Configurar los modos

Cada intención tiene uno de estos modos:

- **Desactivado**: guarda el inbound y lo deja para gestión manual.
- **Sugerir**: crea una respuesta sugerida a partir de una plantilla, sin enviar ni consumir créditos.
- **Automático seguro**: solo registra el outbound cuando la intención es segura, supera el umbral, tiene una plantilla activa y quedan créditos.

Selecciona el modo y, opcionalmente, una plantilla concreta para cada intención. Si no eliges plantilla, se usa la recomendada:

- Reserva → `Enviar enlace de reserva`.
- Precio y servicios → `Enviar servicios`.
- Ubicación → `Enviar ubicación`.
- Bienvenida y horario → `Mensaje de bienvenida`.

Quejas, atención humana, cancelaciones/reprogramaciones y mensajes desconocidos nunca son seguros para envío automático en v1.

## 3. Probar con el webhook simulado

Con el backend local disponible en `http://127.0.0.1:8000`, envía un mensaje de prueba:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/webhooks/test/inbound-message" `
  -H "Content-Type: application/json" `
  -d '{"business_slug":"demo-manicura","channel":"instagram","external_user_id":"manual-test-001","body":"hay que pedir cita?"}'
```

Si `WEBHOOK_TEST_SECRET` está configurado, añade:

```powershell
-H "X-AutonoGrow-Webhook-Secret: TU_SECRETO_LOCAL"
```

Usa un `external_user_id` distinto cuando quieras crear otra conversación. Mensajes con el mismo identificador y canal se añaden a la conversación existente.

## 4. Mensajes recomendados

Prueba estos ejemplos y revisa el badge de intención y confianza:

- `hay que pedir cita?` → Reserva.
- `cuánto cuesta?` → Precio.
- `dónde estáis?` → Ubicación.
- `quiero cancelar mi cita` → Cancelar o cambiar cita; nunca automático.
- `me habéis cobrado mal` → Queja; nunca automático.

El detector convierte el texto a minúsculas, elimina acentos y signos, compacta espacios y compara patrones. No genera texto ni usa IA.

## 5. Verificar una sugerencia

1. Activa la automatización.
2. Configura la intención como **Sugerir**.
3. Envía un inbound que coincida con esa intención.
4. Abre la conversación: debe aparecer **Respuesta sugerida**, pero no un outbound.
5. Pulsa **Enviar sugerencia**: el texto sugerido se registra directamente como outbound del negocio y la sugerencia cambia a `used`.
6. En otra sugerencia, pulsa **Modificar**: el texto pasa al editor sin cambiar todavía de estado. Edita y envía; solo entonces cambia a `used`.
7. Como alternativa, pulsa **Descartar** y comprueba que desaparece de las pendientes sin crear outbound.

Enviar, modificar o descartar una sugerencia no consume crédito automático.

## 6. Verificar un envío automático

1. Activa la automatización.
2. Configura `booking_intent` como **Automático seguro**.
3. Mantén el umbral en `80` y verifica que queda saldo en el periodo.
4. Envía `hay que pedir cita?`.
5. Comprueba que aparece un outbound con emisor **Automatización**, estado `sent` y el enlace público absoluto.
6. Comprueba que el contador **Mensajes automáticos utilizados** aumenta en uno y la conversación queda respondida.

## 7. Verificar el límite del periodo

1. Configura un límite bajo en un entorno local de prueba.
2. Selecciona **Pasar a sugerencias** al alcanzar el límite.
3. Genera automáticos hasta consumir el saldo.
4. Envía otro mensaje seguro.
5. Comprueba que no se crea outbound, no aumenta el contador y aparece una sugerencia.
6. Verifica el aviso: **Límite del periodo alcanzado. Las respuestas automáticas pasan a modo sugerencia.**

El contador se reinicia al primer acceso o inbound de un mes cuyo `YYYY-MM` no coincida con el periodo guardado.

## 8. Integración Instagram y pendientes

- Instagram v1 ya valida webhooks, guarda inbound, aplica automatizaciones y envía texto outbound si el provider está configurado.
- Siguen pendientes OAuth y credenciales por negocio, reintentos, adjuntos avanzados y estados de entrega/lectura avanzados.
- WhatsApp real continúa fuera de alcance.

Estas integraciones no forman parte de Automatizaciones v1.
