# Permisos de automatización, planes y cuota

## Matriz de permisos

| Acción | Owner | Business admin | Business staff | Cliente |
|---|---:|---:|---:|---:|
| Ver límite contratado | Sí | Sí, solo su negocio | No | No |
| Cambiar límite | Sí | No | No | No |
| Ver consumo | Sí | Sí, solo su negocio | No | No |
| Ajustar consumo | Sí, con motivo | No | No | No |
| Reiniciar periodo | Sí, con motivo | No | No | No |
| Pausar/reactivar automatización operativa | Sí | Sí, si la función está habilitada | No | No |
| Editar plantillas autorizadas | Sí | Sí, solo su negocio | No | No |
| Cambiar plan o funciones contratadas | Sí | No | No | No |
| Habilitar canales por negocio | Sí | No | No | No |
| Ver incidencias globales | Sí | No | No | No |
| Ver aviso sencillo de su incidencia | Sí | Sí, solo su negocio | Según acceso operativo | No |
| Resolver incidencias globales | Sí | No | No | No |

La autorización se aplica en FastAPI mediante dependencias de owner o business admin y
se vuelve a comprobar dentro de los endpoints sensibles. Los esquemas Pydantic usan
`extra="forbid"`; un campo comercial inyectado en una petición admin devuelve 422.

## Definición de consumo

`auto_limit_per_period` es el límite contratado, almacenado de forma compatible en
`monthly_auto_limit`. `auto_used_current_period` es un contador del sistema y no es
editable desde `/api/admin/...`.

Una unidad se consume únicamente después de que una respuesta **automática** haya sido
entregada correctamente. No consumen cuota:

- envíos fallidos;
- mensajes manuales;
- sugerencias sin enviar;
- mensajes bloqueados por límite, función o canal no habilitado.

El límite mínimo es cero, que bloquea nuevos envíos automáticos. El máximo explícito es
1.000.000 por periodo. No existe por ahora un valor `null` o un modo ilimitado implícito.
Al alcanzar el límite, se aplica `on_limit_reached`. El owner define la lista de opciones
permitidas y el business admin solo puede escoger dentro de ella.

El periodo usa meses UTC (`period_yyyymm`). Su inicio es el primer día del mes y el fin
es el primer día del mes siguiente. El sistema reinicia el consumo al detectar un nuevo
mes; el owner también puede reiniciarlo manualmente con un motivo obligatorio.

## Ajustes owner y auditoría

Endpoints exclusivos del owner:

- `GET/PATCH /api/owner/businesses/{business_id}/automation-settings`
- `POST /api/owner/businesses/{business_id}/automation-usage-adjustment`
- `POST /api/owner/businesses/{business_id}/automation-period-reset`

Los ajustes manuales de consumo y periodo requieren motivo. El panel solicita
confirmación mostrando el negocio afectado. Los audit logs guardan actor owner,
negocio, acción, valor anterior, valor nuevo, motivo, fecha y `X-Request-ID` cuando está
disponible. No incluyen credenciales ni secretos.

Acciones auditadas: `automation_limit_changed`, `automation_usage_adjusted`,
`automation_period_reset`, `business_plan_changed`, `automation_feature_enabled`,
`automation_feature_disabled` y cambios de comportamiento permitido.

## Compatibilidad y despliegue

La migración ligera añade de forma idempotente `plan_key`,
`automation_feature_enabled`, `instagram_channel_enabled`,
`whatsapp_channel_enabled` y `allowed_limit_behaviors_json` a
`conversation_automation_settings`. Los valores por defecto mantienen habilitadas las
funciones existentes. No se renombran ni reinician el límite, consumo o periodo actuales.

Para desplegar: hacer copia de seguridad, instalar el código, reiniciar el backend para
aplicar la migración idempotente, comprobar OpenAPI/healthcheck y validar primero en
staging la lectura admin y un ajuste owner auditado.
