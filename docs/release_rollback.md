# Rollback seguro de release

`rollback_release.py` es dry-run y nunca baja Alembic ni restaura datos. Antes de desplegar registrar
release/SHA y symlink frontend anteriores, compatibilidad de esquema y backup conjunto.

Ante fallo: activar mantenimiento; detener ambos workers; decidir si el código anterior es compatible
con la head actual; cambiar el symlink backend según el mecanismo del host y el symlink frontend a su
release previa; arrancar backend; comprobar `/ready`; arrancar workers; ejecutar smoke/certification y
revisar logs. El cambio de symlink frontend es atómico y la release previa no se elimina durante la
ventana.

No ejecutar `alembic downgrade` por rutina. Si el esquema nuevo no admite el código anterior, preferir
forward-fix. Restore implica pérdida de datos posteriores: requiere aprobación, mantenimiento, backup
previamente verificado y un plan explícito de punto temporal. Un fallo solo de Caddy se revierte
restaurando su fichero anterior, ejecutando `caddy validate` y después reload.
