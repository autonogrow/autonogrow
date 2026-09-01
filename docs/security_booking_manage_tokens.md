# Tokens temporales de gestión de reservas guest

## Contrato

`booking_manage_token` es una autorización temporal y de propósito único sobre una sola
`Booking`. No representa la identidad permanente de un `Customer`, no autoriza Customer
Memory y no sustituye a `CustomerAccountLink`.

- Se emite solamente al crear una reserva sin usuario autenticado.
- El bearer contiene 32 bytes aleatorios generados por `secrets.token_urlsafe`.
- La base de datos conserva únicamente su SHA-256 hexadecimal, la expiración y, cuando
  aplica, la fecha de revocación.
- La comparación recibe la Booking ya acotada por `business_id` e `id`, calcula SHA-256 y
  usa comparación constante.
- El bearer viaja en el body del claim o en `X-Booking-Token` para adjuntos. No se incluye
  en query strings, rutas, nombres de fichero, auditoría ni logs.

## Expiración y estados

La expiración es el menor valor entre siete días después del final de la cita y noventa
días desde la creación. El límite de 90 días evita bearers de larga duración cuando un
negocio permite reservar con mucha antelación; el margen de siete días mantiene el flujo
habitual de adjuntos alrededor de la cita. Un reagendado recalcula la fecha sin ampliar el
límite desde creación.

`requested`, `pending` y `confirmed` conservan utilidad guest hasta la expiración.
`rejected`, `cancelled`, `completed` y `no_show` revocan el token al entrar en el estado.
Una reserva reclamada o un negocio archivado tampoco admiten el bearer guest. La eliminación
de la reserva elimina el hash por cascade junto con la propia Booking.

## Identidad y adjuntos

Un claim válido crea o valida `CustomerAccountLink`, fija `customer_user_id` y revoca el
bearer en la misma transacción. Después del claim, el usuario accede a los adjuntos por esa
identidad fuerte; otro usuario no obtiene acceso. Upload, listado de metadatos y descarga
privada comparten el mismo validador. No existen endpoints separados de delete o preview.

## Legacy

La revisión `20260901_31` transforma cada plaintext existente a SHA-256 y elimina la columna
plaintext. Los tokens guest activos conservan el bearer ya enviado, pero reciben la nueva
expiración. Los registros claimed o terminales se migran ya revocados. El downgrade restaura
la forma de la columna antigua vacía: no puede reconstruir bearers desde un hash y por ello
es deliberadamente fail-closed.

## Protección operativa

La infraestructura existente limita claim a 30 intentos/minuto por IP, lecturas de adjuntos
a 60/minuto y uploads a 30/minuto cuando `RATE_LIMIT_ENABLED` está activo. Las respuestas de
token inválido, expirado, revocado o asociado a otra reserva usan el mismo 404 y el frontend
muestra «El enlace ya no es válido».
