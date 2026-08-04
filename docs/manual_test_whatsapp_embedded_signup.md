# Prueba manual de WhatsApp Embedded Signup

## Preparación

Configura en un entorno HTTPS de staging `WHATSAPP_EMBEDDED_SIGNUP_ENABLED=true`, App ID,
App Secret, Configuration ID, versión Graph, webhook WhatsApp y las claves de cifrado. No
uses credenciales de producción en archivos versionados. Verifica que la Configuration ID
pertenece a la misma app y que el dominio/redirect permitido está dado de alta en Meta.

## Recorrido válido

1. Como Owner, concede WhatsApp a un negocio y permite conectar al administrador.
2. Como administrador, abre Canales y pulsa **Conectar WhatsApp**.
3. Confirma en DevTools que solo se carga el SDK desde
   `https://connect.facebook.net/en_US/sdk.js`; no deben aparecer token, App Secret, WABA ID
   persistida ni phone number ID persistido en localStorage/sessionStorage.
4. Completa el flujo estándar de Meta. La UI debe indicar revisión pendiente.
5. Comprueba en Owner que solo se muestran nombre verificado, teléfono redactado,
   suscripción, registro y diagnóstico seguro.
6. Antes de aprobar, confirma que no existe una integración nueva utilizable y que una
   integración anterior, el envío integrado y la automatización permanecen intactos.
7. Aprueba solo si suscripción y registro están confirmados. Comprueba que la integración
   queda conectada, pero envío integrado y automatización continúan desactivados.

## Casos adversos

- Reutiliza el mismo state o envía dos finalizaciones: la segunda debe fallar por replay.
- Cambia de sesión o negocio antes de finalizar: debe fallar sin revelar activos.
- Simula un mensaje desde un origen distinto de HTTPS/Facebook: el frontend debe ignorarlo.
- Manipula Business/WABA/phone IDs: la verificación server-side debe rechazar la relación.
- Cancela o entrega un evento distinto de `FINISH`: el intento no debe poder reutilizarse.
- Fuerza un fallo de suscripción: el Owner puede reintentar y no puede aprobar.
- Usa un número que requiera `register`: debe mostrar diagnóstico seguro, no pedir PIN y
  bloquear la aprobación.
- Intenta usar una WABA o phone number ya vinculada a otro negocio: debe devolver conflicto
  genérico sin identificar al otro negocio.
- Suspende o revoca el canal con intento/candidatura activa: debe quedar invalidado.

## Migración y regresión

Ejecuta upgrade desde cero y la secuencia `08 → 09 → 08 → 09`. Después ejecuta pruebas de
Instagram Login, inbox/outbox WhatsApp y control de canales para confirmar que filas
históricas no se reinterpretan y que la versión Graph del sender no cambió.
