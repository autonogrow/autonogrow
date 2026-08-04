# 11 — Flujos críticos actuales y recomendados

Las recomendaciones reorganizan presentación y feedback; no cambian endpoints, permisos, readiness, candidaturas, aprobación, capacidades ni auditoría.

## 1. Alta inicial de un negocio

**Actual:** 1) Owner → Nueva empresa. 2) Elige plantilla/nombre/slug. 3) Crea onboarding. 4) Navega 15 pasos. 5) Readiness. 6) Preview. 7) Motivo y activar.

**Recomendado:** 1) “Nueva alta”. 2) Identidad mínima + plantilla. 3) Crear borrador. 4) Mostrar ficha y checklist por bloques: imprescindible, recomendable, avanzado. 5) Completar bloqueantes. 6) Revisar resumen con enlaces “Cambiar”. 7) Activar con motivo y versión de readiness.

## 2. Completar datos del negocio

**Actual:** Owner pasos Identidad/Contacto/Landing o Admin → Datos del negocio; hay dos superficies según fase.

**Recomendado:** 1) Desde checklist/ficha abrir “Información del negocio”. 2) Agrupar identidad, contacto y contenido público con resumen. 3) Guardar por bloque con feedback. 4) Previsualizar. 5) Volver al checklist conservando completitud. Mantener las dos autorizaciones, pero enlazarlas al mismo modelo mental.

## 3. Crear servicios

**Actual:** Owner puede crear inicial en onboarding; Admin → Servicios crea/edita cards.

**Recomendado:** 1) Más → Servicios o CTA del checklist. 2) Lista compacta. 3) Crear servicio en panel enfocado. 4) Validar nombre/duración/precio. 5) Confirmar y ofrecer “Añadir otro” o asignar personal. No cambiar CRUD.

## 4. Configurar disponibilidad

**Actual:** Admin → Horarios → semana + excepciones; disponibilidad individual vive en Equipo.

**Recomendado:** 1) Más → Horarios. 2) Explicar “horario general” y “horario de cada profesional”. 3) Configurar semana. 4) Añadir excepciones. 5) Revisar conflicto/resumen. 6) Enlazar a personal solo cuando haya ajuste individual.

## 5. Añadir personal

**Actual:** Equipo → formulario dinámico → perfil/rol/capacidad → servicios → disponibilidad; eliminar puede abrir modal por citas.

**Recomendado:** 1) Más → Equipo → Añadir. 2) Datos visibles y función. 3) Asignar servicios. 4) Elegir “usa horario general” o personalizar. 5) Guardar. 6) Si se elimina, mostrar citas afectadas y remediación antes de confirmar.

## 6. Publicar landing

**Actual:** Owner activa tras readiness; Admin puede editar datos/estado y abrir enlace público.

**Recomendado:** 1) Checklist “Página web”. 2) Preview con datos faltantes. 3) Readiness server-side vigente. 4) Resolver bloqueantes. 5) Owner activa con motivo cuando corresponde. 6) Mostrar URL, fecha y estado. Evitar dos botones que parezcan publicar saltándose el control Owner.

## 7. Conectar Instagram

**Actual:** 1) Owner concede acceso. 2) Admin → Canales. 3) Instagram Login/OAuth. 4) callback verifica identidad/webhook y crea candidatura. 5) `pending_approval`. 6) Owner localiza tarjeta/candidatura. 7) aprueba. 8) capacidades de envío/automatización siguen separadas.

**Recomendado:** mismo flujo con stepper visible: Permitido → Conectar con Instagram → Cuenta recibida → En revisión → Aprobada → Envío/automatización configurables. Explicar quién actúa y mantener detalles OAuth/webhook solo en Owner avanzado.

## 8. Conectar WhatsApp

**Actual:** 1) permiso Owner. 2) Admin abre Embedded Signup. 3) SDK devuelve code/event/IDs. 4) backend verifica y crea candidatura. 5) Owner aprueba/rechaza. 6) capacidades separadas.

**Recomendado:** 1) checklist previo (autoridad y acceso al negocio Meta). 2) flujo oficial. 3) confirmación “recibimos el número terminado en …”. 4) revisión Owner en cola transversal. 5) aprobación con identidad enmascarada. 6) activar entrega solo mediante control separado.

## 9. Aprobación Owner

**Actual:** Negocios → encontrar tarjeta → abrir canales/integración → revisar candidate → retry webhook si aplica → approve/reject con motivo.

**Recomendado:** 1) Altas y aprobaciones. 2) ordenar por antigüedad/expiración. 3) abrir candidatura con negocio, canal, activo enmascarado, scopes/recepción en avanzado y alertas. 4) aprobar/rechazar con motivo. 5) mostrar resultado/audit ID. 6) ofrecer configurar capacidades, sin activarlas implícitamente.

## 10. Reconexión de un canal

**Actual:** health periódico marca `reconnection_required`; Admin ve “Volver a conectar” o Owner solicita reconexión; nuevo OAuth/Embedded crea candidatura; Owner vuelve a aprobar.

**Recomendado:** 1) alerta explica impacto/último éxito. 2) confirmar que es recuperable. 3) “Volver a conectar”. 4) repetir flujo oficial. 5) crear nueva candidatura. 6) Owner revisa diferencias de activo. 7) aprobar. 8) health-check confirma recuperación. No restaurar capacidades revocadas automáticamente.

## 11. Confirmar una reserva

**Actual:** Admin → Reservas → Pendientes → tarjeta → Confirmar → PATCH status → refresco; puede aparecer mensaje en outbox.

**Recomendado:** 1) Inicio/Agenda muestra cola. 2) abrir cita con cliente/servicio/hora. 3) Confirmar. 4) feedback separa “cita confirmada” y “aviso al cliente pendiente/enviado”. 5) siguiente cita. Mantener idempotencia del backend y botón desactivado durante mutación.

## 12. Reagendar una reserva

**Actual:** tarjeta → modal → carga servicio/profesional/slots → selección → PATCH `/api/bookings/{id}/reschedule` → cierra/refresca.

**Recomendado:** 1) abrir acción desde cita. 2) diálogo/drawer accesible con resumen actual fijo. 3) seleccionar nuevo día/hora. 4) comparar “antes/después”. 5) confirmar. 6) resultado de cita y comunicación por separado. 7) restaurar foco a la cita.

## 13. Responder una conversación

**Actual:** Conversaciones → filtros/lista → detalle+sugerencias → escribir/elegir sugerencia → enviar integrado o asistido → refrescos; reglas/plantillas en misma pantalla.

**Recomendado:** 1) Mensajes abre no leídos. 2) seleccionar cliente. 3) hilo conserva contexto/canal y estado de automatización. 4) escribir o adoptar sugerencia. 5) enviar. 6) estado entrega inequívoco. 7) plantillas/reglas en Configuración de mensajes, no compitiendo con compose.

## 14. Activar una automatización

**Actual:** Owner habilita feature/capacidad/plan/créditos; Admin configura enable, umbral, límite y reglas; además existe pausa por conversación. La integración debe estar operativa.

**Recomendado:** 1) Owner concede capacidad comercial y saldo. 2) Admin abre Canales/Automatización. 3) checklist de canal saludable, créditos y plantilla/reglas. 4) elegir alcance y comportamiento al límite. 5) revisar ejemplo/impacto. 6) activar. 7) mostrar uso y pausa. Conservar todas las compuertas y no resumirlas en un toggle único.

## 15. Solicitar una reseña

**Actual:** completar cita → acción de review request → copiar/abrir WhatsApp → marcar sent/opened/status → Reseñas pendiente/historial.

**Recomendado:** 1) cita completada ofrece “Pedir reseña”. 2) revisar canal/texto/enlace. 3) crear solicitud. 4) enviar integrado o abrir WhatsApp asistido según capacidad. 5) mostrar entrega separada del estado de solicitud. 6) seguimiento en Clientes y mensajes → Reseñas.

## Garantías de todos los flujos

- Un cambio de navegación no elude autorización ni aislamiento de `business_id/slug`.
- Nunca renderizar access tokens, códigos OAuth, secretos o payload completo.
- Reintentar no equivale a duplicar; desactivar botones y respetar idempotencia backend.
- Errores recuperables conservan entrada/contexto; fallos permanentes explican remediación.
- Cada acción Owner crítica conserva motivo, actor, fecha y auditoría.

