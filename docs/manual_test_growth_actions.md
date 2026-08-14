# Prueba manual — Growth Actions & Attribution

## Preparación

Aplicar la head Alembic actual (`20260814_16`; Sprint 8A se introdujo en `20260814_15`), arrancar API, worker de canales, Admin y landing. Usar una integración real aprobada para el caso de envío; nunca interpretar el modo asistido o un job en cola como entrega.

## Manicura recurrente

1. Completar una manicura con recurrencia 21 días/ventana 4 y ejecutar mantenimiento en la fecha debida.
2. En Crecimiento comprobar cliente, tipo, servicio, canal y estado.
3. Pulsar **Preparar mensaje**. Verificar que no se envía nada.
4. Editar el textarea y pulsar **Enviar** una vez. Confirmar `Pendiente` mientras el outbox está en cola y `Enviado` solo tras respuesta del proveedor.
5. Abrir el link recibido, reservar el mismo servicio y confirmar atribución `direct_link`.
6. Completar la cita y verificar reserva/cita/facturación atribuida usando el precio snapshot.

## Taller

Repetir con cambio de aceite. Confirmar que el texto usa el periodo configurado y que una reserva de otro servicio no atribuye automáticamente una oportunidad `service_due`.

## Lead

Crear una conversación con intent comercial, confianza >=85, teléfono asociable y sin reserva. Tras 48 horas ejecutar mantenimiento, preparar/enviar y reservar. Sin link debe aparecer `post_action_window` solo si no existe otra acción candidata.

## Cancelación y no-show

Crear cada estado, esperar 3 días y ejecutar el motor. El texto de no-show debe ser neutral. Tras enviar y reservar, la oportunidad queda resuelta sin borrar la acción ni la atribución.

## Seguimiento manual

Programar un seguimiento con nota profesional, llevarlo a vencimiento y preparar el mensaje. Comprobar que el contexto se usa de forma determinista y editable.

## WhatsApp fuera de ventana

Usar una conversación cuyo último inbound válido supere 24 horas. Preparar el borrador y pulsar enviar. Debe aparecer `whatsapp_template_required`, no crearse mensaje/outbox ni mostrarse “enviado”. Copiar el texto sigue disponible.

## Integración suspendida o Instagram no válido

Suspender la integración y repetir. El envío se bloquea con razón segura. Para Instagram comprobar cuenta, business, conversación, autorización y salud; no debe existir fallback simulado.

## Carreras e idempotencia

- Doble clic/retry HTTP: un solo `ConversationMessage`, un solo outbox y la misma acción.
- Dos empleados: ambos recuperan el mismo draft; solo una aprobación crea mensaje.
- Reserva antes de enviar: draft cancelado y oportunidad resuelta.
- Reserva con outbox pending/retry: job cancelado antes de proveedor.
- Reserva mientras el worker ya llama al proveedor: conservar resultado; no atribuir si booking precede a `sent_at`.
- Draft con más de 7 días: cancelado por mantenimiento.

## Multi-business y permisos

Desde negocio A intentar IDs de oportunidad, acción, conversación, customer y booking de B: todos deben quedar ocultos/rechazados. Staff puede operar mensajes y marcar gestionada, pero no crear atribución manual. Admin sí puede hacerlo con booking compatible.

## Métricas

Comprobar 7d, 30d y rango manual. Validar desglose por los cinco tipos y funnel. Una reserva anterior, otro customer/business o dos candidatos ambiguos no deben sumar. Tras cancelar una cita atribuida, la atribución histórica permanece pero deja de contar como completada/facturación actual.
