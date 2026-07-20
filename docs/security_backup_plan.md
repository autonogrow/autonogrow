# Plan mínimo de backup

## Alcance

Respaldar juntos, con una marca temporal coherente:

- La base SQLite de `backend/data/`.
- Todo `backend/uploads/`.

No incluir `backend/.env` sin cifrar en el paquete normal. Las credenciales deben guardarse en un gestor de secretos o en un backup cifrado separado y con acceso restringido.

## Frecuencia y retención

- Un backup diario.
- Conservar 7 diarios, 4 semanales y 3 mensuales.
- Cifrar en reposo y durante la transferencia.
- Mantener al menos una copia fuera del servidor de aplicación.
- Ejecutar una restauración de prueba mensual y registrar resultado, duración y responsable.

## SQLite

No copiar el fichero de base de datos en caliente sin coordinación. Usar una de estas opciones:

1. `VACUUM INTO 'ruta-temporal/autonogrow-backup.db'` desde una conexión controlada.
2. La API de backup de SQLite, que crea una instantánea consistente mientras la aplicación sigue funcionando.

Después, empaquetar esa instantánea con una copia de `backend/uploads/`, cifrarla y verificar el checksum. La restauración debe hacerse primero en un entorno aislado y comprobar tablas, recuentos y una muestra de imágenes.

El script `scripts/backup_sqlite_uploads.py` implementa la instantánea con `VACUUM INTO`, el ZIP de uploads y una retención local configurable por número de juegos. Ejemplo: `.venv\Scripts\python.exe scripts\backup_sqlite_uploads.py --keep 14`. No incluye `.env`, pero tampoco cifra ni replica el resultado: esas dos tareas corresponden al job operativo del VPS.

## Límites actuales

Este sprint define el procedimiento, no automatiza almacenamiento, cifrado, alertas ni rotación. Antes de producción deben elegirse destino, claves, responsable y objetivo de recuperación (RPO/RTO).
