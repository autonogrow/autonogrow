# Operación del channel worker

PostgreSQL admite `WORKER_CONCURRENCY_MODE=multi`: cada proceso reclama filas con `FOR UPDATE SKIP
LOCKED`, confirma la reclamación y procesa después. SQLite exige `single`. El panel owner muestra
workers activos/stale y trabajo actual sin hostname. Dimensionar el pool sumando todos los procesos;
empezar con un worker en staging.

Arranque local: `cd backend && python -m app.workers.channel_worker`.

En un despliegue futuro:

```text
sudo systemctl status autonogrow-worker
sudo systemctl start autonogrow-worker
sudo systemctl stop autonogrow-worker
sudo systemctl restart autonogrow-worker
sudo journalctl -u autonogrow-worker -f
```

SIGTERM y SIGINT solicitan parada ordenada. Los trabajos ya reclamados que no terminen vuelven a ser elegibles al expirar `lock_expires_at`. El heartbeat se considera stale después de `WORKER_STALE_AFTER_SECONDS`.

La limpieza es dry-run por defecto: `python scripts/cleanup_queue_history.py`; para aplicar: `python scripts/cleanup_queue_history.py --apply`.
