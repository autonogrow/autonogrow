# Growth Actions & Attribution (Sprint 8A)

## Alcance y seguridad

Sprint 8A convierte una `CustomerOpportunity` en trabajo asistido y medible. El flujo es siempre `oportunidad -> borrador -> revisión/edición -> aprobación explícita -> entrega real`. No existe envío comercial automático, secuencia, campaña, promoción ni generación con IA. Abrir el modal solo crea o recupera un borrador.

## Entidades

`OpportunityAction` conserva negocio, oportunidad, cliente, tipo, estado, canal y referencias opcionales a conversación, mensaje y reserva. También conserva actores y timestamps de creación, edición, aprobación, envío, fallo, cancelación y finalización. El texto sugerido/final pertenece al borrador; después del envío el mensaje real vive en `ConversationMessage` y la acción solo lo referencia.

Los tipos V1 son `contact_customer`, `mark_handled` y `open_conversation`. `dismiss` continúa siendo un estado terminal de `CustomerOpportunity`, evitando duplicar semántica.

`BookingAttribution` enlaza oportunidad, acción y booking mediante `direct_link`, `post_action_window` o `manual`. Sus constraints hacen únicos tanto la acción como el booking atribuido. Conserva el precio y moneda capturados en la reserva; nunca reconstruye importes ni borra el historial si la cita se cancela después.

`Booking.price_amount_snapshot` y `currency_snapshot` se capturan al crear la reserva. Reservas históricas sin importe fiable mantienen `NULL`.

## Ciclo de vida e idempotencia

- `draft`: editable y nunca enviado; expira a los 7 días.
- `approved`: aprobación explícita registrada y mensaje en cola.
- `sending`: outbox reclamado por el worker.
- `sent`: el proveedor aceptó el envío según la semántica existente.
- `failed`: fallo final persistido con razón segura.
- `cancelled`: borrador/cola invalidado o cancelado.
- `completed`: la acción quedó gestionada o produjo una reserva atribuida.

V1 permite una acción de cada tipo por oportunidad mediante `UNIQUE (business_id, opportunity_id, action_type)`. Esta decisión conservadora evita spam; deja historial de distintos tipos sin habilitar seguimientos repetidos. `message_id` también es único. El endpoint de envío bloquea la fila en PostgreSQL, devuelve el mismo resultado ante doble clic y nunca crea un segundo `ConversationMessage`.

El outbox existente sigue siendo la autoridad de entrega. Claim, retry, éxito y fallo sincronizan la acción. Un estado `queued` se muestra como pendiente, no como enviado. El worker vuelve a comprobar que la oportunidad siga pendiente antes de llamar al proveedor.

Si una reserva aparece antes del envío, los drafts se cancelan y los outbox aún `pending/retry` se invalidan. Si el proveedor ya está en una llamada externa, esta no se puede deshacer con seguridad: el resultado se conserva, pero una reserva anterior a `sent_at` no se atribuye.

## Plantillas y links

`OpportunityMessageTemplateService` contiene plantillas deterministas por tipo. Los routers no incluyen copy comercial y no se utiliza LLM. La interfaz del servicio permite introducir overrides por negocio en el futuro sin crear ahora un gestor complejo.

Cada borrador de contacto incluye un enlace a la landing con token firmado y el servicio, cuando existe. El token contiene solo IDs firmados; la reserva se atribuye únicamente si negocio, cliente, acción y tiempos coinciden. No se guarda un bearer token en texto plano.

## Canales

La selección prioriza la conversación origen y después una conversación conocida por teléfono exacto dentro del mismo negocio. Nunca inventa teléfono, email o destinatario. Una conversación puede mostrarse para copiar texto aunque su integración no permita envío.

WhatsApp reutiliza `conversation_delivery_capabilities()` y `send_outbound_message()`: exige integración utilizable, autorización comercial y ventana de atención de 24 horas. Fuera de ventana, sin soporte de template oficial, devuelve `whatsapp_template_required`, no crea mensaje y ofrece copia/manual.

Instagram reutiliza la misma resolución de integración, salud, autorización, conversación y outbox. No duplica llamadas ni lógica Meta. Integraciones suspendidas, expiradas o cruzadas bloquean el envío.

## Atribución

La atribución directa valida el token firmado y exige que la acción esté realmente enviada. Si no hay token válido, se aplica una ventana conservadora de 14 días: mismo negocio, mismo cliente, booking posterior a `sent_at` y oportunidad compatible. `service_due` exige el mismo servicio. Si hay más de una acción candidata no se atribuye automáticamente.

Owner/business admin pueden crear atribución manual mediante el endpoint explícito; staff no recibe ese privilegio. Una atribución resuelve la oportunidad, conserva historial y cancela otros borradores obsoletos. Completar la cita fija `completed_at`; cancelarla posteriormente no elimina la atribución, pero deja de contar como cita completada actual.

## Métricas y funnel

`GET /growth-metrics` soporta 7 días, 30 días y rango manual (máximo 366 días). Devuelve detectadas, pendientes, gestionadas, descartadas, acciones preparadas, mensajes enviados, reservas atribuidas y citas completadas atribuidas, tanto total como por tipo.

El funnel persistente usa oportunidades, acciones, atribuciones y eventos de auditoría: `detected -> viewed -> actioned -> sent -> booked -> completed`. La UI describe el importe como **Ingresos registrados en reservas vinculadas** para no afirmar causalidad. Solo se muestra cuando todas las citas completadas del conjunto tienen snapshot fiable y la moneda coincide; de lo contrario devuelve `NULL`.

Los eventos `opportunity_viewed`, `action_prepared`, `action_edited`, `action_sent`, `action_failed`, `opportunity_handled`, `booking_attributed` y `attributed_booking_completed` reutilizan `AuditLog`. El texto y los tokens no entran en metadata.

## Permisos y multi-tenant

Owner, business admin y business staff pueden ver, preparar, editar, enviar y marcar gestionada usando el permiso operativo de conversaciones. Solo admin/owner puede atribuir manualmente. Cada lookup incluye `business_id`; conversación, customer, booking e integración se vuelven a validar en su tenant.

## Evolución

`OpportunityAction.action_type` y `channel` no hacen que la entidad dependa exclusivamente de WhatsApp/Instagram. Sprint 8B podrá asociar futuros `BusinessGrowthSignal` a campañas, contenido o conjuntos de acciones sin alterar la atribución actual. RRSS, promociones, señales agregadas y automatización total permanecen fuera de Sprint 8A.
