# Operación del channel worker

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
