# Runbook de recuperación de integraciones Meta

## Triage

1. Identificar negocio/canal desde Owner, job e incidencia; no copiar credenciales ni IDs a tickets.
2. Distinguir control comercial de salud. Un canal suspendido/revocado por Owner no se reactiva desde este runbook.
3. Revisar último check, fallos consecutivos, token, suscripción y activo.
4. Usar «Comprobar ahora» una vez; la deduplicación evita ejecuciones paralelas.

## Acciones

- `warning` transitorio: esperar retry; no reconectar por un único timeout.
- `degraded` y subscription missing: «Reintentar suscripción». Solo usa el activo ya estructurado y operación idempotente.
- `action_required`: pedir al cliente reconectar mediante onboarding oficial.
- `revoked`: entrega queda bloqueada; iniciar OAuth/Embedded Signup nuevo y esperar aprobación Owner.
- `suspended`: revisar Business Manager/WhatsApp Manager. AutonoGrow no registra el número, introduce PIN ni cambia WABA.
- `error` por mismatch tenant: no corregir IDs manualmente; escalar como incidente de aislamiento.

No borrar integración, token vigente, conversaciones ni mensajes para resolver un fallo temporal. No activar entrega/automatización como parte de la recuperación.

## Jobs atascados

Un `processing` con lock vencido será reclamado de nuevo y aumenta attempt_count. Tras agotar intentos queda `dead_letter`. Antes de reintentar manualmente comprobar disponibilidad de Meta, configuración de versión y cifrado. Un fallo de descifrado no se reintenta: requiere revisar la rotación de claves sin exponer secretos.

## Limpieza

Los attempts activos vencidos se marcan expired y pierden su credencial candidata. Los terminales con credencial residual se limpian inmediatamente; el registro temporal se elimina después de la retención. La auditoría mínima permanece. La base heredada `backend/data/autonogrow.db` requiere revisión manual y queda fuera del mantenimiento automático.

## Cierre

Confirmar health healthy, contador cero, suscripción/activo active, job completed y auditoría `integration_recovered` o `subscription_retry_succeeded`. Verificar por separado que el control Owner continúa en el estado esperado.
