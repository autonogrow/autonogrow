# Pipeline CI del backend

`.github/workflows/backend-ci.yml` se ejecuta en pull requests y pushes a `main` con Python 3.12.
Instala únicamente `requirements-dev.txt` y usa datos, claves y tokens ficticios. No hay secretos de
GitHub ni llamadas deliberadas a Meta, Google, SMTP u otros proveedores.

Orden: Ruff lint, formato incremental, mypy crítico, Bandit (severidad media o superior), pip-audit,
pytest con cobertura, migración de una base vacía y confirmación current/head. Bandit excluye tests
mediante configuración; los hallazgos bajos actuales son falsos positivos de nombres de campos,
valores de prueba y subprocess con argumentos cerrados. No se excluyen vulnerabilidades altas o
críticas.

El formato se limita inicialmente a la infraestructura nueva/modificada porque aplicar Ruff a todo
el histórico reformatearía 82 archivos sin valor funcional. `ruff check .` sí cubre backend, tests,
scripts y Alembic. La ampliación de formato debe hacerse en un cambio aislado.

La cobertura medida es 64,72%. El umbral inicial es 60%, ligeramente inferior y suficiente para
impedir regresiones sin incentivar tests vacíos. El objetivo debe subir gradualmente.

El job `e2e` instala Chromium y ejecuta los journeys críticos mediante `scripts/run_e2e.py`. Usa una
SQLite temporal, frontends locales y providers externos deshabilitados; no necesita secretos. Sólo
sube screenshots y traces cuando falla. La guía reproducible está en `docs/playwright_e2e.md`.
