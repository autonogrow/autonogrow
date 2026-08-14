# Pruebas manuales — Business Growth Signals

## Preparación

1. Migrar a `20260814_16` y arrancar backend/Admin.
2. Ejecutar primero `python scripts/run_maintenance.py --task growth-opportunities --apply --json` y después `python scripts/run_maintenance.py --task growth-signals --apply --json`.
3. Verificar siempre dos negocios distintos.

## Agenda floja — peluquería

Configurar profesionales y horarios reales, crear seis semanas comparables con reservas suficientes y dejar martes/miércoles de la próxima semana con ocupación menor o igual al 45 %, al menos 20 puntos por debajo. Debe aparecer “Agenda con ocupación baja” con minutos, porcentaje y baseline. Citas canceladas no deben sumar; un día cerrado no debe crear capacidad.

## Ocupación recuperada

Añadir citas activas dentro de la ventana futura hasta superar el threshold y reevaluar. La señal existente debe pasar a `resolved`, sin crear otra. Varias evaluaciones sin cambios deben mantener una sola fila.

## Pool de retorno — uñas

Generar al menos cinco `service_due`, cuatro del mismo servicio. Deben aparecer señal global y señal de servicio, contando clientes únicos. Crear rebooking/resolver oportunidades hasta quedar bajo threshold: las señales activas deben resolverse. “Ver oportunidades relacionadas” debe abrir Sprint 7/8A sin preparar ni enviar mensajes.

## Caída de demanda — uñas

Mantener el servicio activo durante 120 días, con tres periodos de baseline de al menos cinco reservas de media y un periodo actual igual o inferior al 60 %, con caída mínima de tres. La explicación debe mostrar periodo actual y media. Desactivar/archivar el servicio, reducir capacidad más del 30 % o usar un servicio nuevo: no debe aparecer señal.

## Retorno — fisioterapia

Usar únicamente servicios con recurrencia configurada y citas completadas con snapshot. Crear al menos 10 casos actuales y 30 históricos; reducir el retorno actual 15 puntos y hasta un máximo del 50 %. Debe mostrar muestras y tasas, sin recomendaciones clínicas. Seguimientos manuales por profesional no deben entrar en la fórmula.

## Evento estacional — taller

Como Admin crear “Campaña cambio de neumáticos” a menos de 30 días, asociada opcionalmente al servicio. Debe generarse `seasonal_window` informativa. Probar evento desactivado, fuera de ventana y repetición anual. Staff puede verlo pero recibe 403 al crear/modificar/eliminar eventos.

## Lifecycle

Descartar una señal y reevaluar: no debe recrearse en el mismo bucket. Cambiar a una nueva semana/mes sí permite una nueva señal. Las resueltas/expiradas permanecen en consultas históricas.

## Multi-business y privacidad

Repetir datos equivalentes en A y B. List/detail/dismiss/event CRUD de A nunca debe leer IDs de B. La respuesta agregada no debe contener nombres ni listas de clientes.
