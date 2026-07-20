# Manual test: servicios, huecos y reservas

## Preparacion

1. Ejecuta la seed del backend para cargar servicios demo y disponibilidad:
   `python backend/app/seed.py`
2. Arranca el backend:
   `uvicorn app.main:app --reload --app-dir backend`
3. Abre la pagina publica:
   `autonogrow-landing/index.html?b=demo-barberia`
4. Abre el panel admin:
   `autonogrow-admin/index.html?b=demo-barberia`

## Crear cita

1. En la pagina publica, elige `Corte de pelo`.
2. Elige un dia futuro.
3. Elige una hora disponible, por ejemplo `10:00`.
4. Introduce nombre y telefono.
5. Pulsa `Confirmar reserva`.
6. Debe mostrarse el mensaje `Cita creada correctamente`.

## Confirmar que bloquea hueco

1. Sin cambiar de servicio ni dia, revisa los huecos disponibles.
2. La hora reservada no debe aparecer.
3. En el panel admin, actualiza y confirma que existe una unica cita nueva.

## Rechazar y confirmar que libera hueco

1. En el panel admin, pulsa `Rechazar` sobre la cita.
2. Vuelve a la pagina publica, elige el mismo servicio y dia.
3. La hora rechazada debe aparecer otra vez.

## Reagendar cita

1. Crea otra cita de prueba.
2. En el panel admin, pulsa `Reagendar`.
3. Comprueba que el modal muestra el servicio actual de la cita.
4. Elige otro dia y una hora disponible.
5. Pulsa `Confirmar cambio`.
6. Debe mostrarse `Cita reagendada correctamente`.

## Comprobar que no duplica cita

1. Actualiza el panel admin.
2. Comprueba que la misma cita conserva su id y no aparece una segunda cita para el mismo cliente.
3. Comprueba que la fecha/hora de esa cita se actualizo al nuevo slot.

## Comprobar que no permite doble reserva

1. Abre dos ventanas de la pagina publica con el mismo negocio, servicio y dia.
2. En ambas, selecciona la misma hora.
3. Confirma la reserva en la primera ventana.
4. Confirma la reserva en la segunda ventana.
5. La segunda debe fallar con `Ese hueco ya no está disponible`.
