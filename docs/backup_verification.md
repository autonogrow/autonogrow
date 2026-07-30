# Verificación de backups

Ejecutar `python scripts/verify_backup.py MANIFEST --json`. Se comprueban manifest, confinamiento, existencia, tamaño, SHA-256 y estructura. Para PostgreSQL se usa `pg_restore --list`; para uploads se rechazan miembros absolutos, `..`, symlinks y hardlinks.

Un resultado `valid` no sustituye restore. No editar manifests para ocultar fallos. Proteger conjuntos legales o de incidente con `protected=true`; la poda conserva mínimo, retención y juegos completos.
