# Gestión de dependencias

El proyecto usa exclusivamente `pip-tools`:

- `backend/requirements.in`: dependencias directas de producción conservadas en versiones
  compatibles con el entorno verificado.
- `backend/requirements.txt`: lock completo y exacto de producción.
- `backend/requirements-dev.in`: producción más herramientas de desarrollo.
- `backend/requirements-dev.txt`: lock completo y exacto para desarrollo/CI.

No se añaden hashes por ahora: los locks son multiplataforma y las versiones son exactas, mientras
que los hashes multiplicarían artefactos Windows/Linux y dificultarían el flujo actual. CI nunca
instala los `.in`.

```bash
cd backend
pip-compile --strip-extras requirements.in
pip-compile --strip-extras requirements-dev.in
pip install -r requirements.txt
pip install -r requirements-dev.txt
pip check
```

Para una actualización rutinaria, editar solo la dependencia directa objetivo y ejecutar
`pip-compile --upgrade-package PAQUETE`; validar toda la suite. Para seguridad, revisar el aviso de
`pip-audit`, actualizar la versión mínima compatible y documentar el CVE. Una actualización mayor
requiere rama/sprint propio y prueba de migración. Para rollback, restaurar ambos locks anteriores,
recrear el virtualenv y repetir validaciones; no mezclar locks de revisiones distintas.
