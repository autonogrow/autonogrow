# Separación de uploads públicos y privados

## Estado implementado

La raíz configurada por `UPLOADS_DIR` (o `backend/uploads` en local) se divide lógicamente así:

```text
uploads/
├── businesses/                 # público
│   └── {business_slug}/
│       ├── logo/
│       └── gallery/
└── {business_slug}/            # privado
    └── {booking_id}/            # adjuntos de reserva
```

FastAPI monta estáticamente únicamente `uploads/businesses` en `/uploads/businesses`. La antigua ruta estática `/uploads/{business_slug}/{booking_id}/...` ya no existe.

Los adjuntos se descargan mediante:

```text
GET /api/businesses/{business_slug}/bookings/{booking_id}/attachments/{attachment_id}/content
```

El endpoint combina `attachment_id`, `booking_id` y `business_id`, verifica que el path final permanezca dentro de `UPLOADS_DIR` y permite:

- owner;
- business_admin/business_staff con membership activa en ese negocio;
- customer propietario de la reserva;
- reserva anónima con `X-Booking-Token` válido.

El token no se añade a URLs ni query strings. Si en el futuro la landing necesita previsualizar adjuntos anónimos, debe hacer un `fetch` autorizado y crear un object URL temporal en el navegador, no exponer el booking token en la URL.

## Operación en VPS

Configurar, por ejemplo:

```env
UPLOADS_DIR=/var/lib/autonogrow/uploads
DATABASE_URL=sqlite:////var/lib/autonogrow/data/autonogrow.db
```

El usuario del servicio debe tener lectura/escritura, y Nginx/Caddy no debe servir toda la raíz de uploads. Puede servir directamente solo `/var/lib/autonogrow/uploads/businesses`; los adjuntos deben pasar siempre por FastAPI.

## Evolución a S3/R2

Separar buckets o prefijos:

- `public/businesses/...`: lectura pública o CDN.
- `private/bookings/...`: bucket privado.

Guardar en base de datos una key, no una URL pública. Para privados, el backend mantiene las mismas comprobaciones y devuelve el fichero por streaming o una URL firmada de vida muy corta. Nunca usar `booking_manage_token` como firma del objeto ni incluirlo en logs, nombres o metadata del proveedor.

## Pendientes

- Migrar físicamente adjuntos antiguos si alguna instalación los guardó fuera de la estructura actual.
- Definir antivirus/análisis de contenido si se aceptan formatos adicionales.
- Añadir storage abstraído antes de S3/R2; no es necesario para el VPS SQLite inicial.
