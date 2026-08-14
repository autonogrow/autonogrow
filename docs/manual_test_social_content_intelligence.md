# Prueba manual — Social Content Intelligence

## Preparación

1. Aplicar Alembic hasta `20260814_18` y arrancar backend/Admin.
2. Crear o usar un negocio `active` con servicios activos.
3. Ejecutar primero `python scripts/run_maintenance.py --apply --task growth-signals` y después
   `python scripts/run_maintenance.py --apply --task social-content-intelligence`.
4. Abrir Admin > Contenido Instagram > Ideas recomendadas.
5. Confirmar que la UI no promete generar ni publicar contenido.

## Peluquería: agenda baja + color en retorno

1. Preparar histórico/capacidad que produzca `low_future_occupancy` y al menos cuatro oportunidades
   `service_due` agregadas para Color.
2. Reevaluar Growth y Social Content Intelligence.
3. Debe existir una única idea combinada de prioridad alta para Color, Story + Reel, CTA Reservar.
4. No debe aparecer una segunda idea global redundante ni un descuento automático.

## Uñas: recurrencia + Navidad

1. Configurar un evento Navidad en los próximos 14 días vinculado a Manicura.
2. Mantener un pool agregado de retorno de Manicura y reevaluar.
3. Comprobar ideas de retorno/estacional dentro de límites, evento y servicio correctos.
4. Confirmar que ninguna tarjeta muestra nombres, IDs de cliente, teléfonos o emails.

## Taller: evento + disponibilidad

1. Configurar un evento propio del Taller dentro de 30 días y una señal de ocupación baja.
2. Reevaluar y verificar prioridad: disponibilidad urgente antes que evento estacional.
3. Confirmar ventanas y expiraciones en API; ninguna idea debe sobrevivir a su necesidad temporal.

## Fisio: agenda baja sin claims

1. Generar baja ocupación y, opcionalmente, retorno agregado para Seguimiento.
2. Verificar que el texto habla de disponibilidad/seguimiento y no garantiza curación, eliminación
   del dolor ni otro resultado médico.
3. Confirmar que no se propone descuento.

## Reseña: prueba social

1. Insertar/importar una `BusinessReview` de menos de 90 días, rating >= 4, texto no vacío,
   `status=usable` y `social_use_approved=true`.
2. Reevaluar: debe aparecer una idea Testimonio con Post + Story.
3. Comprobar que API/UI no copian el texto ni un autor. Cambiar aprobación a false, usar texto vacío
   o fecha antigua y confirmar que deja de ser candidata.
4. Una `ReviewRequest` enviada no debe crear prueba social: es solo una solicitud saliente.

## Evergreen y material

1. Dejar el negocio sin señales urgentes ni reseña utilizable.
2. Reevaluar dos veces: debe existir una única FAQ evergreen del bucket semanal.
3. Añadir una imagen activa a galería y reevaluar. La idea debe indicar material disponible con
   scope negocio, sin duplicar el binario ni atribuirlo falsamente a un servicio.

## Aceptar, descartar, resolver y expirar

1. Pulsar “Usar idea”; verificar `accepted`, `accepted_at`, usuario y snapshot agregado. No debe
   aparecer un `InstagramContent` nuevo.
2. Pulsar dos veces sobre aceptar mediante API: la segunda respuesta debe ser idempotente.
3. Descartar otra idea; reevaluar y comprobar que el mismo `dedupe_key` no se reactiva.
4. Resolver la señal de una idea activa y reevaluar: la propuesta pasa a `resolved`.
5. Avanzar sobre `expires_at` o usar una propuesta vencida: pasa a `expired`.

## Aislamiento y API

1. Probar listado, detalle, summary y filtros con admin y staff autorizados.
2. Intentar leer/mutar el ID desde el slug de otro negocio: debe responder 404.
3. Probar usuario sin membership: 403; sin sesión: 401.
4. Inspeccionar responses y snapshot buscando nombre, teléfono, email, `customer_id`, memoria
   sensible y conversación cruda: no debe aparecer ninguno.
