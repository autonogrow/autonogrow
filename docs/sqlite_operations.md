# Operación de SQLite

Cada conexión creada por la aplicación aplica:

```text
PRAGMA foreign_keys = ON
PRAGMA journal_mode = WAL       # solo fichero real
PRAGMA busy_timeout = 5000
PRAGMA synchronous = NORMAL
```

El timeout también se pasa a `sqlite3.connect`. Las bases en memoria omiten WAL. Los valores se
configuran con `SQLITE_BUSY_TIMEOUT_MS`, `SQLITE_JOURNAL_MODE` y `SQLITE_SYNCHRONOUS`; Settings
rechaza modos desconocidos y timeouts fuera de 1–60000 ms.

WAL crea ficheros `-wal` y `-shm` junto a la base tanto en Linux como en Windows. El usuario del
servicio necesita escritura sobre el directorio completo. En Windows, antivirus/sincronizadores
pueden prolongar locks; en Linux, no ubicar SQLite en NFS. Un backup en caliente debe usar la API de
backup, no copiar solo el `.db` mientras hay WAL activo.

`database is locked` se clasifica separadamente mediante `is_sqlite_locked_error`; no se ocultan
otros `OperationalError`. Ante locks repetidos, identificar transacciones largas y número de
workers. No aumentar el timeout indefinidamente ni ejecutar varios workers Uvicorn con escritura
concurrente sobre esta arquitectura.
