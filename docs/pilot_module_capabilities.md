# Módulos y capabilities de pilotos

## Modelo autoritativo

`business_module_access` es la única fuente server-side de producto por negocio. Representa tres
módulos técnicos: `essential`, `growth` y `social`. `Complete` no existe como módulo: es packaging
comercial para los tres activos. CORE —negocio, identidad, usuarios, roles, Customer, aislamiento,
auditoría y servicios compartidos— nunca se apaga.

Essential es obligatorio en V1 porque contiene la operación de reservas. Growth y Social pueden
combinarse de forma independiente. Cada registro separa:

- `entitled`: el negocio tiene derecho al módulo;
- `active`: el uso operativo está activado;
- integración: conexión y `health_status` permanecen en `business_channel_integrations`;
- worker/provider: permanecen en configuración y unidades systemd existentes.

`available = entitled AND active`. Un módulo activo sin entitlement es inválido. Desactivar no
borra oportunidades, atribuciones, propuestas, publicaciones, jobs ni assets. La reactivación
recupera acceso a esos datos. La migración `20260822_23` crea los tres registros activos para cada
negocio previo; el onboarding materializa la selección Owner para negocios nuevos. El fallback de
compatibilidad ante filas ausentes solo protege fixtures `create_all` y bases locales anteriores a
la migración; `scripts/check_pilot_configuration.py --json` detecta ese estado en un entorno real.

## Enforcement y superficie

Los routers Growth y Social usan dependencies de capability además de rol y acceso al business.
Instagram content/OAuth verifica Social. Un rechazo devuelve 403 con `code=module_not_available`
sin filtrar datos. Los evaluadores business-scoped de oportunidades, señales y propuestas retornan
sin generar trabajo cuando el módulo está apagado. El publisher y los workers globales no se
habilitan ni se reconfiguran aquí.

Business Admin obtiene `/capabilities`, oculta Growth/Social no disponibles y no llama a sus APIs.
Reviews sigue accesible como función Essential cuando Growth está apagado. Owner consulta y cambia
módulos en la pestaña Módulos o por API. Cada cambio exige motivo y queda en audit log. Los costes
opcionales son mensuales, por módulo y moneda; no son billing, suscripción ni precio de catálogo.

## APIs

- Admin: `GET /api/admin/businesses/{slug}/capabilities`.
- Owner: `GET /api/owner/businesses/{id}/modules`.
- Owner: `PATCH /api/owner/businesses/{id}/modules/{essential|growth|social}`.
- Sanity local/staging: `python scripts/check_pilot_configuration.py --json`.

Roles y tenant isolation se aplican antes/junto a capabilities. Un Business Admin nunca puede
cambiar módulos propios o ajenos.
