# Pruebas manuales — Customer Memory

## Preparación

1. Aplicar `alembic upgrade head` y confirmar una sola head `20260814_17`.
2. Entrar en Admin con un negocio de prueba y tener conversaciones vinculables por teléfono a reservas reales.
3. Probar con admin y staff; no usar información médica, credenciales ni tarjetas reales.

## Peluquería

1. Abrir “Clientes y mensajes”, elegir una conversación de un cliente con varias visitas y pulsar “Ver cliente”.
2. En Memoria, añadir tipo Horario: “Prefiere citas por la tarde”.
3. Añadir Preferencia: “Suele pedir tonos naturales”.
4. Confirmar que Actividad muestra solo completadas, última visita, “Servicio más frecuente” e intervalo observado cuando hay cuatro visitas.

## Taller

1. Añadir Nota: “Prefiere dejar el vehículo a primera hora”.
2. Confirmar que no se confunde la nota con el historial de servicios y que canceladas/no-show no incrementan visitas.
3. Editar el texto, recargar y verificar persistencia.

## Uñas y recurrencia

1. Añadir Preferencia: “Le gustan diseños minimalistas”.
2. Usar cuatro citas completadas con intervalos conocidos y una reserva con recurrencia capturada.
3. Verificar que el intervalo aparece como “Comportamiento observado” y la UI aclara que la recurrencia configurada tiene prioridad.

## CustomerOpportunity

1. Generar una oportunidad `service_due` existente.
2. Abrir Crecimiento > Oportunidades y desplegar “Ver contexto”.
3. Verificar que muestra un contexto breve y no altera motivo, due date, prioridad ni acción de la oportunidad.
4. Eliminar la memoria, recargar y comprobar que desaparece.

## Editar, sustituir y obsoleta

1. Editar una memoria y comprobar el valor nuevo.
2. Usar “Sustituir” sobre “Prefiere mañanas” y guardar “Prefiere tardes”.
3. Confirmar mediante `GET .../memory?status=all` que la anterior está `superseded`, conserva fecha y apunta a la nueva.
4. Marcar otra como “Obsoleta”; debe desaparecer de activas y conservarse en histórico.

## Expiración

1. Crear “Solo puede venir por las tardes durante agosto” con fecha de caducidad temporal.
2. Tras vencer, solicitar el summary y verificar que no aparece en memoria activa.
3. Confirmar por API histórica que el estado es `expired` y la fila sigue presente.

## Seguridad y privacidad

1. Intentar guardar un password/token, una clave privada de prueba y `4111 1111 1111 1111`; la API debe responder 422.
2. Marcar una nota operativa como sensible y confirmar el indicador visual.
3. Revisar audit logs: deben contener ids/categoría/key/actor, nunca el contenido.
4. No guardar diagnósticos ni historia clínica; Customer Memory no es un expediente sanitario.

## Multi-business

1. Crear customers y memorias en negocios A y B.
2. Como staff de A, intentar leer/editar/borrar ids de B: acceso denegado o 404 sin contenido.
3. Usar el mismo teléfono en ambos negocios y confirmar que la ficha y las oportunidades nunca mezclan memorias.
