# Manual test: horarios y excepciones de disponibilidad

## Preparacion

1. Ejecuta la seed:
   `C:\Users\localUser\AppData\Local\Programs\Python\Python310\python.exe backend\app\seed.py`
2. Arranca backend:
   `C:\Users\localUser\AppData\Local\Programs\Python\Python310\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`
3. Abre el admin:
   `autonogrow-admin/index.html?b=demo-barberia`
4. Abre la landing:
   `autonogrow-landing/index.html?b=demo-barberia`

## Cambiar horario de un dia

1. En admin, seccion `Horarios`, cambia lunes a un solo tramo `12:00-13:00`.
2. Pulsa `Guardar horarios`.
3. En landing, elige `Corte de pelo` y el proximo lunes disponible.
4. Deben aparecer solo huecos dentro de `12:00-13:00`.

## Cerrar un dia

1. En admin, marca lunes como `Cerrado`.
2. Pulsa `Guardar horarios`.
3. En landing, elige `Corte de pelo` y ese lunes.
4. Debe mostrarse `No hay huecos disponibles para este dia`.

## Anadir horario especial

1. En admin, seccion `Excepciones`, selecciona una fecha concreta.
2. Elige `Horario especial`.
3. Anade un tramo `17:00-18:00`.
4. Guarda la excepcion.
5. En landing, elige esa fecha.
6. Deben aparecer huecos solo dentro de `17:00-18:00`, aunque el horario semanal sea distinto.

## Cerrar una fecha concreta

1. En admin, crea una excepcion de tipo `Cerrado` para una fecha.
2. En landing, elige esa fecha.
3. No debe haber huecos disponibles.
4. Borra la excepcion desde admin.
5. En landing, la fecha debe volver a usar el horario semanal.

## Cambiar antelacion minima

1. En admin, cambia `Antelacion minima` a un valor alto, por ejemplo `10080` minutos.
2. Guarda horarios.
3. En landing, comprueba que desaparecen huecos demasiado cercanos.
4. Devuelve el valor demo: `120` para barberia o `180` para manicura.

## Cambiar margen entre citas

1. En admin, cambia `Margen entre citas` a `30`.
2. Guarda horarios.
3. En landing, crea una cita en un hueco.
4. Vuelve a consultar el mismo dia.
5. El hueco reservado y los huecos demasiado cercanos deben desaparecer.
6. Rechaza la cita desde admin.
7. Comprueba que los huecos vuelven a estar disponibles.

## Reagendado y estados existentes

1. Crea una cita desde landing.
2. En admin, pulsa `Confirmar`.
3. Pulsa `Reagendar`.
4. El modal debe usar los huecos reales configurados.
5. Confirma el cambio.
6. Actualiza admin y comprueba que sigue siendo la misma cita, sin duplicado.
7. Prueba `Rechazar` y `Completada` y confirma que no hay errores.
