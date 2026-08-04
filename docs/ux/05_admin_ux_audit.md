# 05 — Auditoría UX del Business Admin

## Diagnóstico

El panel tiene cobertura funcional alta, pero su modelo de navegación refleja dominios técnicos y de implementación más que frecuencia de uso. Para una persona que abre AutonoGrow entre clientes, “qué tengo que atender ahora” debería dominar sobre “qué puedo configurar”. La UI actual trata Resumen, Crecimiento, Reservas, Conversaciones, outbox, Servicios, Equipo, Horarios, Canales, datos y Reseñas como destinos equivalentes.

Fortalezas: textos mayoritariamente en español, acciones por tarjeta, feedback local, filtros útiles, separación de capacidades Meta, reservas con estado claro y degradación a contacto cuando no hay profesional. Deben conservarse.

## Diez fricciones prioritarias

| # | Problema / dónde | Usuario | Gravedad | Frecuencia | Consecuencia | Propuesta conceptual |
|---:|---|---|---|---|---|---|
| 1 | Once pestañas de igual peso en la navegación principal | Todo Admin | Alta | Cada sesión | Barrido horizontal y dificultad para recordar dónde vive cada tarea | Cinco destinos por intención; configuración en “Más” |
| 2 | Resumen muestra 12 tarjetas equivalentes y no prioriza citas de hoy, mensajes sin responder ni bloqueos | Propietario/recepción | Alta | Diaria | Más tiempo para descubrir urgencias; se pierde confianza en el dashboard | Bloque “Ahora” con agenda y bandeja; configuración en segundo plano |
| 3 | Reservas abre en Pendientes y se representa como tarjetas, no como agenda temporal | Recepción/profesional | Alta | Varias veces/día | Encontrar carga del día y huecos requiere cambiar vista e interpretar listas | Agenda Hoy como entrada operativa; lista Pendientes como cola secundaria |
| 4 | Reagendar abre un proceso completo en modal sin semántica de diálogo, foco, Escape ni contexto persistente suficiente | Recepción | Alta | Semanal | Riesgo de desorientación/acción en cita equivocada, sobre todo teclado/móvil | Página/drawer de tarea o diálogo accesible con resumen fijo de la cita |
| 5 | Conversaciones reúne filtros, lista, hilo, sugerencias, plantillas, reglas, integración y conversación de prueba | Recepción/Admin | Alta | Diaria | Sobrecarga; en móvil se pierde contexto al apilar columnas | Bandeja centrada en responder; configuración/plantillas en destino secundario |
| 6 | “Mensajes automáticos” separa el outbox de Conversaciones aunque ambos hablan de comunicaciones | Propietario | Media-alta | Semanal | Dos modelos mentales y búsqueda duplicada de “un mensaje que no salió” | Unificar bajo Clientes y mensajes, con pestaña Seguimientos/Entregas |
| 7 | Configuración está fragmentada en Servicios, Equipo, Horarios, Canales, Datos y Reseñas | Propietario | Alta | Alta al comenzar; baja después | Onboarding no parece una secuencia y faltan señales de completitud | Checklist inicial y hub “Más”; preservar páginas especializadas |
| 8 | Canales mezcla lenguaje amable con rastros técnicos y el texto “en esta fase…” ya no refleja que existen flujos Meta reales | Propietario | Media | Alta al conectar/error | Duda sobre si la conexión es real y quién debe aprobar | Flujo por pasos: permiso → conectar → revisión → capacidad → estado |
| 9 | Errores y confirmaciones alternan entre alertas nativas, texto inline, tarjetas y consola | Todos | Alta | Cuando algo falla | No siempre queda claro si la acción se guardó, puede repetirse una mutación | Feedback compartido con resultado, siguiente acción y “estado desconocido” |
| 10 | Editores largos generados para servicios/personal/horarios no advierten cambios sin guardar y se rerenderizan tras mutaciones/polling | Administrador frecuente | Media-alta | Semanal | Pérdida de foco/borrador y errores al editar varios elementos | Edición enfocada, dirty-state y actualización localizada |

## Evaluación por tarea

- **Encontrar citas de hoy:** posible mediante Reservas → Hoy, pero requiere conocer la pestaña interna. Debe ser una acción directa desde Inicio.
- **Confirmar/reagendar:** los botones están próximos a la cita; confirmar es corto. Reagendar introduce más decisiones y necesita mejor contexto/foco.
- **Responder mensajes:** la división lista/hilo es adecuada en escritorio. Plantillas y automatización ocupan el mismo contexto y dificultan el uso principal.
- **Servicios/horarios/personal:** la cobertura es completa. Falta una secuencia de incorporación y una visión de “configuración suficiente para aceptar reservas”.
- **Conectar Meta:** se preserva correctamente la separación entre solicitud, candidatura, aprobación y capacidades. La representación debería ser un stepper de estado, no sumar tarjetas técnicas.
- **Comprender estados:** reservas tienen traducción razonable; salud y automatización contienen más capas. Un badge debe responder una sola pregunta.

## Jerarquía recomendada sin cambio funcional

1. Inicio: citas inmediatas, mensajes pendientes, alertas accionables y progreso inicial.
2. Agenda: Hoy/semana y cola Pendientes; acciones de reserva.
3. Clientes y mensajes: conversaciones, seguimiento/outbox y reseñas vinculadas.
4. Crecimiento: tareas y resultados, no configuración base.
5. Más: servicios, equipo, horarios, canales, web y ajustes.

## Riesgos operativos a preservar

- No convertir la visibilidad de una pestaña en autorización; personal y Admin siguen dependiendo del backend.
- No fusionar “canal aprobado”, “envío activo” y “automatización activa”. Pueden mostrarse juntos, pero son controles independientes.
- Una reserva confirmada puede generar comunicación. El feedback debe distinguir “reserva actualizada” de “mensaje entregado/pendiente/no entregado”.
- El polling no debe sobrescribir notas, respuestas o formularios en curso.

## Microcopy Admin

| Actual | Ubicación | Problema | Propuesta | Avanzado |
|---|---|---|---|---|
| Intervalo de slots | Horarios/onboarding | anglicismo técnico | Duración mínima de los huecos | No |
| Mensajes automáticos | nav | puede confundirse con respuestas automáticas | Seguimientos por WhatsApp | Estado técnico en detalle |
| Outbox / estado de entrega interno | mensajes/errores | modelo de cola | Envíos pendientes / Historial de envíos | Sí |
| modo interno / entrega asistida | conversaciones | describe implementación | Responder desde AutonoGrow / Preparar respuesta | Sí |
| Integración de canal | automatización | abstracto | Cuenta conectada para mensajes | Sí |
| Token/caducidad, si aparece | detalle de integración | credencial, no necesidad de usuario | La autorización caduca el… | Sí, Owner |
| Comprobación encolada | Canales | expone cola | Estamos comprobando la conexión | Sí |
| health-check / healthy, si llega sin mapear | Canales | inglés/técnico | Comprobar conexión / Funciona correctamente | Sí |
| No se pudo conectar con el backend | errores | no ofrece acción | No pudimos cargar los datos. Reintenta. | Backend solo diagnóstico |
| “En esta fase no se solicitan…” | Canales | texto histórico frente a OAuth/Embedded reales | AutonoGrow nunca te pedirá que pegues una contraseña o token de Meta | Sí para vía Owner heredada |

