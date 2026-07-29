# Incidencias y alertas técnicas

AutonoGrow agrupa los fallos técnicos en `system_incidents`. La tabla se crea con el
mecanismo existente de `Base.metadata.create_all()` al arrancar el backend. La clave
interna se calcula a partir de negocio, proveedor, canal, código y operación; la
referencia visible tiene el formato `AGW-AAAAMMDD-00001`.

## Configuración

Las alertas están desactivadas por defecto. Para activarlas:

```dotenv
INCIDENT_ALERTS_ENABLED=true
INCIDENT_ALERT_EMAIL=operaciones@autonogrow.es
INCIDENT_ALERT_MIN_SEVERITY=high
INCIDENT_DEDUP_WINDOW_MINUTES=30
INCIDENT_RECOVERY_EMAIL_ENABLED=true
SMTP_HOST=smtp.example.net
SMTP_PORT=587
SMTP_USERNAME=autonogrow
SMTP_PASSWORD=secret-from-the-server-vault
SMTP_FROM=alertas@autonogrow.es
SMTP_USE_TLS=true
```

Cuando `INCIDENT_ALERTS_ENABLED=true`, el arranque rechaza una configuración sin
destinatario, host SMTP o remitente válidos. Usuario y contraseña son opcionales,
pero deben configurarse juntos. `SMTP_PASSWORD` solo debe vivir en el fichero de
entorno del servidor, nunca en Git.

## Despliegue

1. Hacer copia de seguridad de la base de datos.
2. Añadir las variables al fichero externo `/etc/autonogrow/backend.env`.
3. Instalar la nueva versión del código y reiniciar el servicio. El arranque crea
   `system_incidents` e índices de forma idempotente.
4. Comprobar `/api/health`, acceder como owner y abrir la sección **Incidencias**.
5. Activar SMTP primero en staging y simular un error 190 antes de producción.

## Prueba manual de Instagram

1. Simular una respuesta de Graph API con HTTP 400 y `error.code=190`.
2. Enviar un mensaje y comprobar el aviso sencillo con referencia `AGW-...`.
3. Confirmar una única fila `high` y un único correo técnico.
4. Repetir el fallo dentro de 30 minutos: aumenta `occurrence_count` sin otro correo.
5. Restaurar la conexión y enviar correctamente.
6. Confirmar estado `resolved` y, si está activo, el correo de recuperación.

Los metadatos se filtran mediante una lista permitida. No se persisten ni se envían
tokens, cabeceras Authorization, payloads, cuerpos de conversaciones o mensajes.
