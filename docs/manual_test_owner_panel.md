# Pruebas manuales — Owner Panel

## Preparación

1. Activa el entorno virtual y arranca el backend desde `backend`:
   `..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload`.
2. Sirve la raíz del repositorio en el puerto 5500 (por ejemplo, con Live Server).
3. Abre `http://127.0.0.1:5500/autonogrow-owner/index.html`.

> Seguridad: el Owner Panel no tiene autenticación y es exclusivamente para desarrollo local. No se debe exponer en producción. Incorporar autenticación de propietario (por ejemplo, `OWNER_TOKEN` y `X-Owner-Token`, o una solución completa de sesión) es deuda crítica previa al despliegue.

## Listado y métricas

- [ ] Se muestran todos los negocios existentes, incluidos los inactivos.
- [ ] El resumen global coincide con la suma de las tarjetas: total, activos, reservas, mensajes y reseñas pendientes.
- [ ] Cada tarjeta muestra nombre, categoría, ciudad, estado y métricas.
- [ ] Los badges Datos, Servicios, Horarios, Reseñas y WhatsApp reflejan la configuración real.
- [ ] “Abrir landing” y “Abrir admin” conservan el slug correcto en `?b=`.

## Alta con slug automático

1. En “Nuevo negocio”, deja Slug vacío.
2. Completa nombre, categoría, ciudad y teléfono.
3. Elige una plantilla de horario y crea el negocio.

- [ ] Aparece un mensaje de éxito con el slug normalizado, sin acentos ni espacios.
- [ ] Los enlaces a landing y admin apuntan al nuevo slug.
- [ ] El negocio aparece en el listado sin recargar la página.

## Alta con slug manual y servicios

1. Introduce un slug con mayúsculas, acentos o espacios y añade dos servicios.
2. Completa nombre, precio, duración, descripción y estado de cada servicio.
3. Crea el negocio.

- [ ] El slug queda normalizado y no puede repetirse.
- [ ] Los servicios aparecen en la landing cuando están activos.
- [ ] El admin abre el negocio correcto y muestra sus settings.
- [ ] “Horarios” muestra `Europe/Madrid` y la plantilla elegida.
- [ ] Un negocio sin servicios puede crearse y su badge Servicios queda pendiente.

## Activación y visibilidad

1. Pulsa “Desactivar” en una tarjeta.
2. Abre la landing de ese negocio.

- [ ] La tarjeta pasa a Inactivo.
- [ ] La API pública devuelve negocio no encontrado y la landing no lo publica.
- [ ] El Owner Panel y el admin interno siguen pudiendo localizarlo.
- [ ] Al pulsar “Activar”, vuelve a estar disponible públicamente.

## Seed conservador

1. Modifica un dato del negocio creado desde su admin.
2. Ejecuta `..\.venv\Scripts\python.exe -m app.seed` desde `backend`.
3. Recarga Owner Panel, landing y admin.

- [ ] El negocio creado manualmente sigue existiendo.
- [ ] Sus datos, servicios y horarios no se han sobrescrito.
- [ ] Los negocios demo existentes siguen funcionando.

## Validaciones técnicas

- [ ] `..\.venv\Scripts\python.exe -m compileall backend/app`
- [ ] `..\.venv\Scripts\python.exe -m app.seed` (desde `backend`)
- [ ] `GET /api/owner/businesses`
- [ ] `GET /api/owner/businesses/{slug}`
- [ ] `POST /api/owner/businesses`
- [ ] `PATCH /api/owner/businesses/{slug}` para desactivar y reactivar
- [ ] Landing y admin del nuevo negocio cargan sus datos y servicios

## Fuera de v0

La clonación de negocios queda como deuda técnica: no se añade `POST /api/owner/businesses/{slug}/clone` para mantener esta primera versión pequeña, explícita y segura frente a duplicados de servicios o configuración.
