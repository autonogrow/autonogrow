# 06 — Auditoría UX del panel Owner

## Diagnóstico

Owner contiene los controles correctos y conserva distinciones de seguridad importantes, pero los distribuye dentro de tarjetas de negocio cada vez más densas. El operador necesita trabajar por excepción —aprobaciones, reconexiones, incidencias, suspensiones— y hoy debe trabajar principalmente por entidad: localizar negocio, abrir detalles y examinar varios subpaneles.

## Representación de estados requerida

El modelo backend distingue las capas; la interfaz las presenta juntas y puede parecer una única “conexión”. El rediseño debe usar esta matriz:

| Pregunta | Estado | Control/área actual | No implica |
|---|---|---|---|
| ¿Se vende este canal al negocio? | disponible/no disponible | acceso comercial Owner | que pueda conectarse aún |
| ¿Puede iniciar conexión? | permitido / owner-only | channel access/policy | cuenta conectada |
| ¿Hay una candidatura? | pending_approval | OAuth/Embedded candidate | aprobación ni entrega |
| ¿Owner valida el activo? | approved | decisión candidate/control | envío activo |
| ¿Puede AutonoGrow enviar? | delivery capability | checkbox Owner | automatización |
| ¿Puede responder sin humano? | automation capability + feature/settings/credits | Owner + reglas Admin | salud técnica |
| ¿Funciona la credencial/activo/suscripción? | healthy/warning/degraded/action_required/revoked | health | permiso comercial |
| ¿Se ha detenido temporalmente? | suspended | channel/business | revocación definitiva |
| ¿Se retiró acceso? | revoked | channel control | reconexión automática |
| ¿Debe repetir el flujo oficial? | reconnection_required | health action | aprobación automática de nueva candidatura |

Cada fila necesita etiqueta, explicación breve, fecha/actor y acción propia. Nunca condensarlas en un único badge “Activo”.

## Diez fricciones prioritarias

| # | Problema / dónde | Gravedad | Frecuencia | Consecuencia | Propuesta conceptual |
|---:|---|---|---|---|---|
| 1 | No existe cola global de aprobaciones; candidaturas están dentro de cada tarjeta | Crítica | Diaria en altas | Retraso u omisión de aprobaciones | “Altas y aprobaciones” transversal, ordenado por antigüedad/riesgo |
| 2 | Cada tarjeta mezcla estado, marca, usuarios, canales, integración y créditos | Alta | Cada búsqueda | Sobrecarga y scroll; comparar negocios es difícil | Lista compacta → ficha de negocio con subnavegación |
| 3 | Cargar lista dispara varias peticiones por negocio (usuarios/media/canales/health/integration/automation) | Alta | Cada entrada | latencia, estados parciales y carga proporcional a cartera | Resumen agregado y detalle lazy al abrir negocio |
| 4 | Estado comercial, aprobación, capacidades y salud aparecen próximos sin una jerarquía causal | Crítica | Cada incidencia de canal | Operador puede activar la capa incorrecta o creer que ya entrega | Timeline/matriz de capas con verbos explícitos |
| 5 | Salud muestra `health`, token, subscription, asset y fallos en inglés técnico | Alta | Diaria en incidencias | Se interpreta el código, no la acción necesaria | Resumen “Funciona / Vigilar / Requiere acción”, detalle técnico desplegable |
| 6 | Suspender, revocar, borrar credenciales, mantenimiento y jobs usan `prompt`/`confirm` nativos | Alta | Semanal | contexto insuficiente, accesibilidad pobre, no se muestra impacto ni recuperación | diálogo con recurso, consecuencias, motivo, confirmación y referencia de auditoría |
| 7 | Operaciones imprime JSON y “Colas y worker” prioriza implementación | Media-alta | Durante incidencias | mayor tiempo de diagnóstico y riesgo de acción sobre job equivocado | vista operacional por impacto; datos crudos en “Detalle técnico” |
| 8 | Las pestañas no persisten URL ni permiten deep link/back | Media | Muchas veces/día | volver/refrescar pierde contexto; soporte no puede compartir una vista | rutas/hash estables con negocio/canal/attempt como contexto |
| 9 | Onboarding de 15 pasos mezcla alta mínima con automatizaciones, integraciones, créditos y readiness | Alta | Cada alta | proceso largo y términos internos; aumenta abandono/errores | alta mínima, checklist de preparación y configuración avanzada separada |
| 10 | No hay destino de Auditoría aunque acciones exigen motivo y backend audita | Alta | Investigaciones | difícil explicar quién aprobó/suspendió/reintentó | pestaña de auditoría filtrable y enlace desde cada estado/acción |

## Navegación y trazabilidad

El resumen actual son seis métricas por encima de Negocios, no un espacio de trabajo. Conviene convertirlo en una bandeja de decisiones: aprobaciones venciendo, canales con acción requerida, incidencias nuevas y negocios bloqueados para activar. Cada elemento debe conservar `business_id`, canal, attempt/job/incidente y fecha sin exponerlos como título principal.

Las acciones peligrosas necesitan:

1. recurso y estado actual;
2. efecto sobre clientes, recepción y automatización;
3. si es reversible y cómo;
4. motivo obligatorio;
5. confirmación explícita con verbo exacto;
6. resultado y enlace al evento de auditoría.

## Microcopy Owner

| Actual | Por qué confunde | Propuesta visible | Mantener técnico |
|---|---|---|---|
| Colas y worker | implementación interna | Procesamiento de mensajes | sí, detalle |
| Inbox pendientes | anglicismo | Entradas pendientes | sí |
| Outbox pendientes | anglicismo | Envíos pendientes | sí |
| Dead letters | no comunica remediación | Casos que requieren revisión | sí |
| Worker inactivo/stale | no explica impacto | El procesamiento no tiene actividad reciente | sí |
| Salud: degraded/action_required | inglés y metáfora abstracta | Funciona con avisos / Requiere acción | código en detalle |
| Token | credencial | Autorización de Meta | sí |
| Suscripción | se confunde con plan | Recepción de mensajes | webhook/subscription sí |
| Activo | ambiguo con negocio activo | Cuenta o número conectado | asset ID sí |
| Fallos consecutivos | no explica qué hacer | Comprobaciones fallidas seguidas | contador sí |
| Reintentar suscripción | técnico | Reparar recepción de mensajes | sí |
| WABA / phone_number_id | identificadores Meta | Cuenta de WhatsApp / número conectado | sí, copiable y enmascarado |
| Readiness | anglicismo | Revisión previa | código en detalle |
| Job #ID | unidad interna | Tarea de recepción/envío | ID en detalle |
| Plan y creditos | acento y mezcla comercial/técnica | Plan y créditos | claves internas sí |

No ocultar el dato técnico cuando soporte lo necesita; presentarlo tras la explicación operacional y copiarlo de forma segura, sin tokens ni secretos.

