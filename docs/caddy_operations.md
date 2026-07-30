# Operación con Caddy

La plantilla sirve frontend, proxy de API/uploads y probes con timeouts cortos. Bloquea `/internal/*`, `.env` y backups, limita body, elimina Server y aplica headers. Métricas deben obtenerse desde loopback, no por Internet.

Validar con `caddy validate --config deploy/Caddyfile.example` en el host. Adaptar dominio y rutas antes de instalar. Los access logs JSON rotan por tamaño/edad; no incluir query strings sensibles ni cabeceras de autenticación.
