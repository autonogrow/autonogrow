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

`available = entitled AND active`. Un módulo activo sin entitlement no concede acceso. Una fila
ausente equivale a `entitled=false`, `active=false` y `available=false`: nunca se infiere producto
contratado por ausencia de datos. Desactivar no borra oportunidades, atribuciones, propuestas,
publicaciones ni assets; inmoviliza el trabajo recuperable ya encolado y una reactivación no lo
reanuda automáticamente.

La migración `20260822_23` creó los tres registros activos para cada negocio que existía entonces.
La migración `20260901_29` completa configuraciones posteriores: un negocio con cero filas conserva
explícitamente los tres accesos que le daba el antiguo fallback; los huecos de una configuración
parcial se materializan deshabilitados, como ya se comportaban. Onboarding, altas legacy y seed
materializan siempre las tres filas. `scripts/check_pilot_configuration.py --json` detecta cualquier
ausencia o incoherencia restante sin modificar datos.

## Enforcement y superficie

Los routers Growth y Social usan dependencies de capability además de rol, acceso al business y su
estado operativo. Instagram content/OAuth y las mutaciones Instagram/Meta verifican Social; las
lecturas históricas y diagnósticas siguen separadas. Un rechazo devuelve 403 con
`code=module_not_available` sin filtrar datos. Los evaluadores business-scoped retornan sin generar
trabajo cuando el módulo está apagado. Publisher, retry, envíos y workers vuelven a comprobar la
capability inmediatamente antes de reclamar o producir un efecto externo, cubriendo downgrades.

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
