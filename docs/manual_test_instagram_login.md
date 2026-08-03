# Prueba manual — Instagram Login Sprint 4B

Usar staging HTTPS, una aplicación Meta de pruebas y cuentas profesionales sin datos
reales. No copiar tokens, codes o URLs completas a tickets o capturas.

## Configuración y seguridad

- [ ] El backend arranca con `INSTAGRAM_LOGIN_ENABLED=false` y variables vacías.
- [ ] Habilitar Login con configuración incompleta impide arrancar staging.
- [ ] Una redirect URI HTTP, con query o de un origen no permitido es rechazada.
- [ ] Meta tiene registrada exactamente `/api/integrations/instagram/callback`.
- [ ] Inicio sin sesión devuelve 401 y sin CSRF devuelve 403.
- [ ] Staff y Admin de otro negocio reciben 403.
- [ ] Canal no concedido, suspendido o revocado no inicia OAuth.
- [ ] Dos inicios equivalentes invalidan el primero.
- [ ] Logs y auditoría no contienen query, state, code, token ni respuesta Meta.
- [ ] La ruta antigua de simulación Instagram devuelve 410 fuera de tests.

## Autorización y callback

- [ ] El botón muestra el precheck y navega en ventana principal, nunca iframe.
- [ ] La URL solicita solo identidad profesional y mensajería.
- [ ] Cancelar muestra un mensaje seguro y permite empezar de nuevo.
- [ ] State desconocido, expirado, usado, de otra sesión u otro usuario es rechazado.
- [ ] Callback sin sesión no consume el intento.
- [ ] Code ausente o usado queda en error seguro, sin reflejarlo.
- [ ] Error de red o token no intercambiable no expone respuesta Meta.
- [ ] Permisos parciales muestran que faltan permisos necesarios.
- [ ] Scope inesperado no se guarda como concedido.
- [ ] Cuenta personal se rechaza; Business y Creator se aceptan.

## Candidatura y Owner

- [ ] Tras OAuth se ve username, estado pendiente y ninguna credencial.
- [ ] No existe integración utilizable antes de aprobación inicial.
- [ ] Owner ve username, fecha, expiración, permisos, webhook y error seguro.
- [ ] Webhook correcto permite aprobar; fallo muestra reintento y bloquea aprobación.
- [ ] Rechazar limpia ciphertext candidato y devuelve la conexión inicial a disponible.
- [ ] Aprobar crea una sola integración y limpia ciphertext candidato.
- [ ] Aprobar deja envío y automatización desactivados.
- [ ] Activar envío no activa automatización.
- [ ] Suspender/revocar apaga ambas capacidades y cancela candidaturas.

## Reconexión, sustitución y aislamiento

- [ ] Reconectar la misma cuenta actualiza credenciales sin duplicar integración.
- [ ] Un fallo de reconexión conserva el token anterior.
- [ ] Autorizar otra cuenta crea candidatura `replacement` y conserva la activa.
- [ ] Owner ve la cuenta activa y la candidata antes de aprobar.
- [ ] Aprobar sustitución cambia la cuenta una sola vez y conserva historial cerrado.
- [ ] Un remitente de la cuenta nueva no reabre conversaciones de la anterior.
- [ ] Rechazar sustitución deja intacta la cuenta activa.
- [ ] Una cuenta vinculada o pendiente en otro negocio se rechaza sin revelar el negocio.

## Regresión

- [ ] Inbound Instagram firmado sigue resolviendo por account ID.
- [ ] Outbound Instagram solo funciona con control Owner y envío habilitado.
- [ ] WhatsApp inbound/outbound no cambia.
- [ ] Owner manual avanzado sigue oculto al Business Admin.
- [ ] Ruff, mypy, Bandit, Alembic, pytest y predeploy terminan correctamente.
