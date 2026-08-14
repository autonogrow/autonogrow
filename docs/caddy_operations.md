# Operación con Caddy

La plantilla versionada sirve el symlink frontend, proxy de `/api/*`, uploads públicos y probes a
`127.0.0.1:8000`. Bloquea paths internos, limita body, elimina `Server` también en respuestas del
upstream y aplica HSTS exacto `max-age=31536000` sin `includeSubDomains`/preload. Ampliar HSTS exige
revisar todos los subdominios. CSP aún no se activa porque el frontend usa scripts inline y Google
GIS; se registra como WARN, no se inventa una política incompatible.
La raíz redirige a la landing. Los entrypoints HTML no se cachean y los assets se revalidan tras un
máximo de cinco minutos, complementando el cambio atómico para evitar HTML/JS de releases distintas.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
sudo journalctl -u caddy --since '15 minutes ago' --no-pager
sudo tail -n 200 /var/log/caddy/autonogrow-access.log
```

Nunca hacer reload si `validate` falla. Los paths de webhook y signed assets se omiten del access log
porque sus queries contienen material sensible; FastAPI mantiene auditoría por ruta y request ID sin
query. Confirmar `/privacy/`, `/data-deletion/`, `/api/webhooks/instagram` y
`/api/public/instagram-assets/*` desde Internet, no desde localhost.
