# Operación del worker de publicación simulada

El proceso se ejecuta separado de FastAPI:

```text
cd backend
python -m app.workers.instagram_publish_worker --once
python -m app.workers.instagram_publish_worker --poll-seconds 2
```

Debe configurarse `INSTAGRAM_PUBLISHING_WORKER_ENABLED=true` y mantenerse
`INSTAGRAM_PUBLISHING_SIMULATED_MODE=true`. El proceso se niega a arrancar en modo no simulado. El
endpoint “Publicar ahora” solo deja un job vencido en cola; nunca llama al adaptador dentro de la
petición HTTP.

PostgreSQL permite varios procesos mediante `FOR UPDATE SKIP LOCKED`. SQLite solo es seguro con un
worker, coherente con `WORKER_CONCURRENCY_MODE=single`. El claim se confirma antes de ejecutar el
adaptador y la finalización se persiste en una transacción nueva. Un claim `claimed` vencido se
recupera; uno `simulating_publish` vencido pasa a `action_required`, pues su resultado podría ser
incierto.

Los errores temporales y timeouts usan backoff exponencial acotado con jitter determinista. Los
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
reintento Owner. No se debe editar manualmente la clave de idempotencia ni duplicar filas.
