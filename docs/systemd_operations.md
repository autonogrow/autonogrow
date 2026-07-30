# Operación con systemd

`deploy/` contiene ejemplos para backend, worker, checks cada cinco minutos, backup diario, verificación semanal, recordatorio mensual de restore y mantenimiento diario. No se instalan ni activan desde el repositorio.

Revisar usuario/grupo no root, rutas, `EnvironmentFile`, `ReadWritePaths`, flock, UMask, timeouts y hardening antes de copiar a `/etc/systemd/system`. Ejecutar `systemd-analyze verify`, luego daemon-reload y habilitar solo tras Sprint 7. Consultar con `systemctl status`, `list-timers` y `journalctl -u`; configurar retención de journald en el host.
