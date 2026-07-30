# Automatización de backup PostgreSQL

`run_backup_set.py` coordina `backup_postgresql.py` y `backup_uploads.py` con un identificador común. Sin `--apply` solo muestra el plan. PostgreSQL usa `pg_dump --format=custom`, contraseña por entorno del subproceso, archivo parcial, rename atómico, modo 0600, `pg_restore --list`, SHA-256 y manifest.

Uploads rechaza symlinks y nombres semejantes a secretos, crea tar.gz y vuelve a leer toda su estructura. El backup normal excluye entorno y keyring: conservar secretos de recuperación por separado, cifrados y con acceso restringido.
