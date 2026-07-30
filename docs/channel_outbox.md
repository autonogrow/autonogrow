# Channel outbox

Estados: `pending`, `processing`, `sent`, `retry`, `blocked`, `failed`, `dead_letter`, `cancelled`.

Mensaje y outbox nacen en la misma transacción. La outbox no almacena tokens. El worker valida que la integración pertenece al negocio, comprueba estado y caducidad, descifra justo antes de enviar y no mantiene una transacción durante HTTP.

Los intentos usan aproximadamente 30 s, 2 min, 10 min, 30 min y 2 h, con jitter limitado al ±10 %. Un error temporal reutiliza la misma outbox; un error de credenciales queda bloqueado.
