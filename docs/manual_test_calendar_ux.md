# Manual test: calendar UX y acciones de reserva

## Preparacion

1. Ejecuta seed:
   `C:\Users\localUser\AppData\Local\Programs\Python\Python310\python.exe backend\app\seed.py`
2. Arranca backend:
   `C:\Users\localUser\AppData\Local\Programs\Python\Python310\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`
3. Abre:
   `autonogrow-landing/index.html?b=demo-barberia`
4. Abre:
   `autonogrow-admin/index.html?b=demo-barberia`

## Estados visuales del calendario

1. En admin, crea una excepcion `closed` para una fecha futura.
2. En landing, elige un servicio.
3. El dia cerrado debe verse en rojo suave.
4. Al pulsarlo debe mostrar `Este dia el negocio esta cerrado.`

1. En admin, crea una excepcion `custom_hours` para otra fecha futura.
2. En landing, elige el mismo servicio.
3. El dia con horario especial debe verse en amarillo suave.
4. Al pulsarlo debe mostrar `Este dia tiene horario especial.`

1. Crea reservas hasta ocupar los huecos de una fecha de prueba.
2. Recarga landing.
3. El dia lleno debe verse en gris suave.
4. Al pulsarlo debe mostrar `No quedan huecos disponibles para este dia.`

1. Elige un dia disponible normal.
2. Debe permitir seleccionar hora y confirmar reserva.

## Admin

1. Abre una reserva pendiente o confirmada en admin.
2. Comprueba que no aparece un boton separado `Cancelar`.
3. Pulsa `Rechazar`.
4. Vuelve a la landing y comprueba que el hueco se libera.
5. Si existe una cita antigua con status `cancelled`, debe mostrarse como cancelada, sin ofrecer una accion nueva de cancelar.

## Contratos de creacion de cita

1. Crea una cita con `start_datetime` usando:
   `POST /api/businesses/demo-barberia/bookings`
2. Comprueba que se derivan `preferred_date`, `preferred_time`, `start_datetime` y `end_datetime`.

1. Crea otra cita con `preferred_date` + `preferred_time`.
2. Comprueba que sigue funcionando y bloquea el hueco.

## Reagendado y legacy

1. Reagenda una cita desde admin.
2. Comprueba que se actualiza la misma cita y no aparece duplicada.
3. Si hay citas legacy con `preferred_date`, `preferred_time` y `service_id`, pero sin `start_datetime`, deben bloquear disponibilidad si estan en `requested`, `pending` o `confirmed`.
4. Las citas legacy `completed`, `rejected` o `cancelled` no deben bloquear huecos futuros.

## Textos

1. Abre landing y admin en navegador.
2. Comprueba que acentos, `ñ` y simbolo `€` se ven correctamente.
3. Ignora mojibake solo de la consola PowerShell si el navegador muestra bien los textos.
