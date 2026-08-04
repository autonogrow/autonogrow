# 10 — Arquitectura de información propuesta

## Principios

1. Organizar por trabajo del usuario, no por tablas/endpoints.
2. Dar acceso directo a tareas diarias; relegar configuración ocasional.
3. Presentar estados por capas sin fusionar permisos ni seguridad.
4. Permitir deep link a entidad/tarea y restaurar contexto.
5. Hacer que móvil sea una priorización real, no el desktop apilado.

## Business Admin

La propuesta de partida es adecuada con un ajuste: “Clientes y mensajes” puede llamarse **Mensajes** en navegación móvil por espacio, pero en escritorio debe incluir el contexto de cliente, conversaciones, seguimientos y reseñas. “Crecimiento” debe permanecer solo si muestra acciones/resultados con valor distinto del checklist inicial.

```text
Business Admin
├── Inicio
│   ├── Ahora: próxima cita, citas por confirmar, mensajes nuevos
│   ├── Alertas accionables: canal, disponibilidad, envío
│   ├── Resumen del día
│   └── Primeros pasos (solo mientras esté incompleto)
├── Agenda
│   ├── Hoy (predeterminada)
│   ├── Semana / próximas
│   ├── Pendientes
│   ├── Historial
│   └── Cita: confirmar, reagendar, notas, completar, reseña
├── Clientes y mensajes
│   ├── Conversaciones
│   ├── Seguimientos / envíos
│   ├── Plantillas (secundario)
│   └── Reseñas
├── Crecimiento
│   ├── tareas recomendadas
│   └── resultados relevantes
└── Más
    ├── Servicios
    ├── Equipo
    ├── Horarios y excepciones
    ├── Canales
    ├── Página web (datos, marca, galería)
    └── Configuración
```

“Reseñas” podría vivir en Crecimiento, pero su acción nace en una cita y su estado es comunicación; se recomienda Clientes y mensajes, con acceso contextual desde la cita. “Datos del negocio” pasa a “Página web” porque describe el resultado visible; datos legales/operativos futuros irían a Configuración.

### Acceso directo

Diario: Inicio, Agenda, Mensajes, búsqueda/alertas, confirmar/reagendar/responder. Secundario: servicios, equipo, horarios una vez configurados, canales, web, plantillas y reglas. Acciones destructivas nunca deben esconderse en un menú sin mostrar contexto/impacto.

## Owner

```text
Owner
├── Resumen
│   ├── decisiones pendientes
│   ├── canales que requieren acción
│   ├── incidencias nuevas
│   └── salud operativa resumida
├── Negocios
│   ├── lista compacta, búsqueda/filtros
│   └── ficha de negocio
│       ├── resumen comercial
│       ├── usuarios y marca
│       ├── canales/capacidades
│       ├── automatización/créditos
│       └── actividad/auditoría filtrada
├── Altas y aprobaciones
│   ├── onboarding en curso
│   ├── candidaturas Instagram
│   ├── candidaturas WhatsApp
│   └── revisión/decisión
├── Integraciones
│   ├── todas por estado/canal
│   ├── requiere reconexión
│   └── ficha técnica segura
├── Incidencias
├── Operaciones
│   ├── procesamiento de mensajes
│   ├── mantenimiento
│   └── detalle técnico
├── Auditoría
└── Configuración (secundaria)
```

La propuesta solicitada se acepta casi completa. El orden recomendado coloca Integraciones antes de Incidencias cuando el volumen Meta sea el trabajo Owner dominante; puede validarse con telemetría. Auditoría no existe aún en frontend y requiere verificar endpoint/modelo antes de implementación: la IA no autoriza inventar una API.

### Ficha vs cola

- Una **cola transversal** responde “¿qué debo decidir ahora?”.
- Una **ficha de negocio** responde “¿cuál es la historia/configuración de este cliente?”.
- Una **ficha de integración** responde “¿qué capa falla y cómo la recupero?”.

No duplicar mutaciones: varias vistas pueden enlazar al mismo proceso de decisión, con un único componente y endpoint.

## Móvil Business Admin

```text
Barra inferior
├── Inicio
├── Agenda
├── Mensajes
└── Más
```

La acción contextual principal aparece dentro de cada vista, no como botón flotante global ambiguo. Crecimiento vive en Más o como card de Inicio en móvil; si pruebas de uso muestran frecuencia, puede aparecer dentro de Inicio. La barra inferior debe tener cuatro destinos estables, label visible, `aria-current` y área táctil recomendada de 44 px.

Owner móvil no necesita imitar la barra Business Admin: es una herramienta operativa más densa. Usar cabecera + menú y listas compactas; decisiones críticas siguen siendo realizables, pero la supervisión masiva puede optimizarse para tablet/desktop sin bloquear 360 px.

## Modelo de páginas/URL conceptual

Sin imponer router ni backend nuevo:

```text
Admin ?b=slug#home | #agenda | #messages | #growth | #more/services ...
Owner #overview | #businesses?business=ID | #approvals?channel=... | #integrations?...
Landing ?b=slug#reserva
Customer (perfil/reservas en la misma página inicialmente)
```

Los hashes exactos deben diseñarse con compatibilidad: los actuales `#bookings`, `#conversations`, etc. deben redirigir/mapear a la nueva sección durante una ventana de migración. Los filtros complejos pueden vivir en query; nunca incluir tokens, secretos ni PII sensible.

## Estados y feedback

Patrón común:

```text
Estado para persona: “Necesita volver a conectar Instagram”
Contexto: “No estamos recibiendo mensajes desde 03/08, 18:42”
Acción: “Volver a conectar”
Detalle avanzado: health=action_required · subscription=missing · attempt=…
```

Para mutaciones: en progreso → resultado confirmado → siguiente acción. Si la mutación pudo completarse pero falló el refresco, decir “El cambio puede haberse guardado; recarga para comprobarlo”, no afirmar fracaso.

## Qué no cambia

- Roles, permisos y aislamiento por negocio.
- Endpoints y modelos en el rediseño inicial.
- Candidatura y aprobación Owner.
- Separación de envío integrado y automatización.
- Motivos/auditoría de acciones críticas.
- Cifrado y no exposición de credenciales.

