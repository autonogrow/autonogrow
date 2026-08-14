# Operación del worker de publicación de Instagram

El proceso se ejecuta separado de FastAPI:

```text
cd backend
python -m app.workers.instagram_publish_worker --once
python -m app.workers.instagram_publish_worker --poll-seconds 2
```

Debe configurarse `INSTAGRAM_PUBLISHING_WORKER_ENABLED=true`. `INSTAGRAM_PUBLISHING_MODE=simulated`
es el valor seguro y predeterminado. El modo `meta` exige además el acuse explícito y toda la
configuración HTTPS/HMAC descrita en `instagram-content-sprint-6c1.md`. El
endpoint “Publicar ahora” solo deja un job vencido en cola; nunca llama al adaptador dentro de la
petición HTTP.

PostgreSQL permite varios procesos mediante `FOR UPDATE SKIP LOCKED`. SQLite solo es seguro con un
worker, coherente con `WORKER_CONCURRENCY_MODE=single`. El claim se confirma antes de ejecutar el
adaptador y la finalización se persiste en una transacción nueva. Un claim `claimed` vencido se
recupera; uno `simulating_publish` vencido pasa a `action_required`, pues su resultado podría ser
incierto. En modo real, un container confirmado se recupera antes de iniciar publish, un media ID
confirmado se finaliza sin repetir publish y una ejecución vencida después del inicio irreversible
pasa a revisión manual.

Los errores temporales anteriores a `media_publish` usan backoff exponencial acotado con jitter
determinista. Un timeout o desconexión durante `media_publish` nunca se reintenta. Los
errores permanentes terminan en `failed`; un resultado desconocido termina en `action_required`.
El reintento conserva la misma fila y clave de idempotencia. Logs y auditoría solo contienen IDs,
códigos y mensajes seguros; nunca caption, rutas de assets, tokens ni respuestas crudas.

Comandos systemd orientativos:

```text
sudo systemctl enable --now autonogrow-instagram-publisher
sudo systemctl status autonogrow-instagram-publisher
sudo journalctl -u autonogrow-instagram-publisher -f
```

Para recuperar una incidencia: corregir primero servicio/validación/integración/fecha y usar el
reintento Owner o Business Admin solo si el resultado no es incierto. No se debe editar manualmente la clave de
idempotencia, scopes, IDs de proveedor ni duplicar filas. La primera activación real sigue el
runbook `instagram_real_publish_runbook.md`.
