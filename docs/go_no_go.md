# GO / NO-GO

`release_readiness.py --json` es read-only. Revisa árbol Git, metadata, keyring, conexión/head, backup disponible y bloqueos manuales. `GO` exige todo correcto; `GO-WITH-WARNINGS` exige aceptación explícita; cualquier fallo crítico es `NO-GO`.

La decisión no sustituye CI, restore aislado, smoke autenticado, revisión Caddy/systemd ni las validaciones manuales Sprint 7. Registrar quién acepta warnings y su mitigación.
