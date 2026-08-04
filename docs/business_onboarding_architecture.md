# Arquitectura de onboarding multiempresa

## Incorporación de canales Meta

Instagram Login y WhatsApp Embedded Signup producen candidaturas temporales cifradas. El
onboarding del negocio solo concede quién puede iniciar el flujo; no acredita activos, no
crea tokens y no sustituye la aprobación Owner. Para WhatsApp, consulta
[WhatsApp Embedded Signup](whatsapp_embedded_signup_architecture.md).

El owner crea un `Business` en `draft`, abre una única sesión activa y lo mueve a `onboarding`. La configuración se escribe en tablas de dominio; la sesión solo conserva progreso, resúmenes seguros, versión de pasos y actor/fecha.

Los 15 identificadores estables son `template`, `business_identity`, `contact_and_location`, `services`, `staff`, `schedules`, `booking_rules`, `branding`, `landing_content`, `automations`, `integrations`, `credits_and_plan`, `readiness_review`, `preview` y `activation`.

Estados del negocio: `draft → onboarding → configuration_pending|ready → active → suspended → active`. Los estados no activos admitidos pueden archivarse; `archived` no vuelve a activo. Solo los endpoints owner de activación, suspensión, reactivación y archivado ejecutan transiciones comerciales.

Los perfiles de personal no son usuarios ni membresías. Sus asignaciones a servicios viven en `business_staff_profile_services`. PostgreSQL usa bloqueos de fila al activar, inicializar créditos y recuperar la sesión activa; SQLite conserva constraints e índices parciales equivalentes para desarrollo y tests.

## Permisos y aislamiento

Todo `/api/owner/.../onboarding`, readiness, preview, clonación y cambio de estado exige owner. El business admin conserva únicamente edición delegable de su propio negocio y no puede cambiar plan, créditos o estado. Los endpoints públicos siguen filtrando exclusivamente `status = active`.
