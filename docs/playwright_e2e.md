# Playwright E2E crítico

La suite E2E usa Playwright para Python y `pytest-playwright`, en coherencia con el tooling Python
del repositorio. Ejecuta 16 journeys de alto valor contra Chromium. No se introducen Node, Vite ni
un segundo servidor frontend.

## Instalación

Desde la raíz del repositorio:

```powershell
.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.venv\Scripts\python.exe -m playwright install chromium
```

En Linux/CI, instalar Chromium y sus dependencias con:

```bash
python -m playwright install --with-deps chromium
```

La V1 ejecuta la suite completa sólo en Chromium para mantenerla rápida. Los riesgos específicos de
Firefox, WebKit y dispositivos físicos quedan para la campaña manual y una futura matriz smoke.

## Ejecución

El runner normal, con cero retries, es:

```powershell
.venv\Scripts\python.exe scripts\run_e2e.py
```

Modos interactivos:

```powershell
.venv\Scripts\python.exe scripts\run_e2e.py --headed
.venv\Scripts\python.exe scripts\run_e2e.py --debug
```

Se pueden pasar opciones adicionales a pytest, por ejemplo:

```powershell
.venv\Scripts\python.exe scripts\run_e2e.py -k repeat_booking -x
```

## Entorno aislado

`e2e/conftest.py` arranca Uvicorn automáticamente en `127.0.0.1:8765`. `e2e/server.py` monta el
backend real y los frontends estáticos de landing, customer, admin y owner. No hace falta arrancar
procesos manuales.

Cada test recrea el schema en una SQLite efímera bajo el directorio temporal del sistema y aplica
un seed determinista. Incluye Salón E2E, Fisio E2E, Owner, Admin, cliente identificado, servicios,
profesionales, citas, contenido Instagram y materiales brutos. Los uploads también viven fuera del
repositorio y ningún test depende del orden de ejecución.

El login usa cookies reales firmadas o el endpoint Google real de la aplicación con verificación de
token sustituida sólo dentro del proceso E2E. `e2e.server` falla al arrancar salvo que
`APP_ENV=test`; un test de seguridad ejecuta esa barrera con `APP_ENV=production`. No existe un
endpoint de bypass E2E en la aplicación.

Google se intercepta localmente, `wa.me` se registra y responde localmente, y Meta no se configura.
Los flags de workers, publisher de Instagram, webhooks y providers permanecen deshabilitados.

## Datos y diagnóstico

Los tests esperan locators, respuestas y estados; no usan pausas fijas. Los contextos usan
`Europe/Madrid`, desktop `1440x900` y móvil `390x844`. Cada journey falla ante errores de consola,
respuestas 5xx o requests esenciales fallidas inesperadas.

La única excepción de red esperada es el `409` del `DELETE` de un raw asset referenciado: el journey
declara método, status y fragmento de URL, exige observar esa respuesta y comprueba que abre el
Association Manager. La línea genérica que Chromium escribe en consola sólo se admite después de
observar exactamente ese conflicto controlado.

En fallo se guardan bajo `test-results/`:

- screenshot de página completa;
- trace de Playwright con snapshots, red y fuentes.

En éxito no se conservan artefactos. Para abrir un trace:

```powershell
.venv\Scripts\python.exe -m playwright show-trace test-results\<archivo>.zip
```

CI sube `test-results/` únicamente cuando el job E2E falla. El log del servidor se escribe en
`%TEMP%\autonogrow-e2e\server.log` en Windows y su equivalente temporal en Linux.
