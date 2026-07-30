# Operación del onboarding

1. Ejecutar `alembic upgrade head` fuera del proceso web.
2. Verificar que la head es `20260730_05`.
3. Revisar el seed con `python scripts/seed_onboarding_templates.py` (dry-run).
4. Aplicarlo explícitamente con `python scripts/seed_onboarding_templates.py --apply`.
5. Abrir el panel owner, crear o reanudar el negocio y resolver los bloqueantes de readiness.

El seed es idempotente por `key + version`, actualiza solo plantillas del sistema y no sobrescribe plantillas personalizadas. No se ejecuta al arrancar FastAPI. Las sesiones `blocked` siguen siendo reanudables. Suspender conserva datos e histórico; archivar requiere una operación owner y no borra filas.

Rollback: suspender negocios recién activados, guardar backup, ejecutar `alembic downgrade 20260730_04` y desplegar el código compatible. El downgrade transforma estados no compatibles en `inactive`; revisar esa clasificación antes de volver a publicar.
