# Auditoría pre-pilotos — Sprint 10C

Auditoría realizada sobre el HEAD inicial `1ab27d82421ae4ebc9d49367a2b25e126e8eed25`, antes de crear
el modelo nuevo. El repositorio estaba limpio en `main`; el HEAD local estaba un commit por delante
de `origin/main`, por lo que no se hizo pull, push ni deploy.

## Inventario general

| Área | Estado previo | Hallazgo y decisión 10C |
|---|---|---|
| Creación de business / Owner onboarding | Listo para piloto | Flujo Owner completo, slug/timezone/contacto, plantilla y 15 pasos; se amplió la creación con selección de módulos. No DB manual. |
| Business Admin / configuración inicial | Listo con fricción | Checklist y pantallas reales ya existían; se reutilizan. Se añade readiness piloto y navegación modular, no otro wizard. |
| Usuarios, roles, servicios, profesionales, horarios | Listo para piloto | RBAC y tenant scoping existentes; config suficiente para llegar a reserva. Personal es recomendado, no blocker universal. |
| Branding, landing pública y reserva | Listo para piloto | Página pública y CTA de booking/contacto ya funcionales; sin redesign. Debe verificarse visualmente por piloto y viewport. |
| Customer portal y Google login | Listo con fallback | Identidad/linking conservador; la reserva invitada evita que OAuth opcional bloquee. |
| Instagram | Funciona pero requiere operador técnico | Onboarding, health, contenido y publishing existen. Social readiness distingue conexión de entitlement; provider/publisher permanecen apagados. |
| WhatsApp | Listo en modo asistido; Cloud incompleto | `wa.me` permite piloto. Meta verification, webhook y embedded signup no bloquean cuando no se contratan como requisito. |
| Automatizaciones, calendario, reseñas | Listo para piloto | Superficies y tests existentes. Reviews se conserva accesible con Growth apagado. |
| Growth: oportunidades, acciones, señales, atribución | Listo para piloto controlado | Cadena de atribución existente reutilizada; ahora requiere Growth y los evaluadores omiten businesses apagados. |
| Social: contenido, assets, publicaciones | Listo con deuda operativa | Propuestas/drafts/historial existen; Social apagado impide trabajo nuevo sin borrar. Analytics económico Social sigue incompleto. |
| Empty states / ayuda / errores | Fricción no bloqueante | La QA UX previa cubre estados principales y mensajes de acción. Persisten términos técnicos en vistas Owner/operativas; no se añadió tutorial paralelo. Revisión manual por business sigue en checklist. |
| Datos demo / fixtures | Separados de piloto | Seeds y Playwright son test data, no datos piloto. No existe marcador seguro de demo; no se creó reset ni seed destructivo. |
| Backups / restore / mantenimiento | Listo con operación técnica | Backup sets DB+uploads, verificación, restore test y dry-run maintenance existentes. Cada entorno requiere evidencia reciente de restore. |
| Health / smoke / build / deploy / rollback | Listo para staging QA | Probes, build metadata, smoke, certificación y frontend atómico existentes; runbook 10C añade capability/readiness sanity y límites de rollback DB. |
| Staging/certificados | Funciona pero requiere operador | Certificación automática/manual existente. No se desplegó; TLS, servicios y evidencia deben verificarse en la campaña. |
| Seguridad/config/secrets | Listo con deuda conocida | RBAC, CSRF, signed URLs, redacción y predeploy existentes. La revisión local no sustituye rotación ni inspección de secrets del host. |
| Mobile / accesibilidad | Listo con deuda | Shell responsive, focus/labels y auditorías estructurales existen; se requiere QA manual con contenido real. No hay cobertura E2E completa WebKit/Firefox. |
| Legal | Incompleto no bloqueante para QA cerrada | No se encontró un paquete legal final de privacidad, DPA, retención/erasure y consentimiento del piloto. Es requisito antes de producción pública/datos reales según jurisdicción. |

No se detectó blocker de arquitectura previo que impidiera crear, asignar y configurar un negocio sin
editar DB. Los posibles blockers se conservan como gates: booking principal, aislamiento tenant,
migración reproducible, backup restaurable, configuración segura y página pública real.

## Auditoría de modularidad previa

| Concepto buscado | Clasificación previa | Evidencia / conclusión |
|---|---|---|
| Plans / subscriptions / billing | Falta | No había modelo comercial autoritativo; no se implementa billing ni pricing final. |
| Feature flags | Parcial | Flags globales de provider/worker y features; no expresaban derecho por business. |
| Business service activation | Parcial | Servicios reservables y canal Instagram habilitado; son dominio/integración, no módulos comerciales. |
| Module activation / entitlements | Falta | No había combinación Essential/Growth/Social por business. |
| Capabilities | Legacy/parcial | “Capabilities” de canales/automation eran permisos técnicos dispersos, no producto autoritativo. |
| Permissions asociadas a plan | Falta | RBAC existente, pero sin plan/módulo. Se mantiene separado. |
| Pricing / module cost | Falta | No había coste por módulo; se añade coste mensual opcional y sin precios hardcodeados. |
| Attribution / métricas Growth | Existe y se usa | `BookingAttribution`, acciones y métricas se reutilizan; no se duplica la cadena. |
| Baseline / ROI | Falta | Se añade baseline opcional y ROI conservador solo con coste y revenue directo completos. |

La carencia justificó una única migración y una fuente autoritativa server-side. `Complete` no se
modela; equivale a Essential+Growth+Social. CORE comprende business, usuarios, roles, Customer,
identidad, auditoría, datos compartidos e integraciones base y no se destruye al apagar módulos.

## Fricciones, mensajes y estados vacíos

Las vistas Citas, Clientes, Servicios, Personal, Reseñas, Conversaciones, Oportunidades, Crecimiento,
Contenido, assets, Calendario y Automatizaciones ya contaban con estados vacíos/QA estructural en
10B-6. Se preservaron y las superficies de módulos apagados ahora desaparecen en lugar de mostrar
errores, ceros o candados repetidos. El checklist enlaza a las pantallas existentes. La capa de API
devuelve `module_not_available` con texto accionable y sin detalles internos.

Business Admin conserva términos de producto (“Instagram necesita atención”, “módulo no disponible”)
y Owner conserva health/provider/job IDs donde son necesarios para soporte. “Raw asset”, OAuth,
HMAC, retries y delivery mode continúan únicamente en superficies técnicas/Owner o documentación.
No se certifica perfección de copy ni accesibilidad visual hasta la prueba manual en staging.

## Datos, recovery y alcance deliberado

- No se reutilizan fixtures E2E como datos piloto y no se ejecutaron seeds.
- No se creó reset: falta un marcador explícito, auditable y seguro de business demo. Para piloto real
  no habrá reset destructivo; se usan correcciones, migración y backup/restore.
- Desactivar módulos conserva oportunidades, atribuciones, señales, propuestas, publicaciones y assets.
- Mantenimiento/storage reconciliation siguen dry-run por defecto; no se amplió retención ni borrado.
- No se cambió estado de publisher/workers, no se habilitó provider ni se llamó a Meta/WhatsApp.
- Landing comercial pública existente: no se creó otra. Sus CTA siguen separados del alta interna;
  verificar copy/legal/contacto real antes de una campaña pública.

## Deuda aceptada para staging QA

Meta verification/WhatsApp Cloud, publisher real, pricing definitivo, billing, retención avanzada,
Redis/rate limiter distribuido, escalado horizontal, marketplace, nuevas redes y E2E completo en
WebKit/Firefox quedan fuera. Para incorporar datos personales reales siguen siendo necesarias la
evidencia de restore del entorno, revisión legal/privacidad, contacto de soporte, verificación manual
móvil/accesible y aceptación explícita de warnings de cada piloto.

