# Runbook de alta de piloto

Objetivo: pasar de negocio nuevo a piloto trazable sin editar la base de datos. Operar siempre desde
Owner/Business Admin; no usar fixtures E2E ni activar providers/workers.

1. En Owner → Altas, crear nombre, slug, plantilla opcional y módulos. Essential permanece activo;
   elegir Growth/Social según el piloto.
2. Abrir Módulos y confirmar entitlement/activation. Dejar costes vacíos si no existe coste piloto
   acordado; no usar hipótesis de pricing.
3. En Usuarios y acceso, asignar al menos un Business Admin real del negocio. Personal bookable y
   acceso autenticado son conceptos distintos.
4. Completar identidad, timezone y un contacto público. No pedir datos legales/técnicos innecesarios.
5. Crear al menos un servicio activo/reservable con duración; precio es opcional pero mejora la
   medición de volumen gestionado.
6. Configurar horario semanal real y reglas de booking. Personal es recomendado si el negocio asigna
   citas por profesional.
7. Completar branding/landing suficiente y revisar la preview `noindex`; no duplicar estas pantallas
   dentro de otro wizard.
8. Si Social está activo, revisar Instagram como conectado/con atención; no arrancar publisher. Si
   está apagado, omitirlo. WhatsApp Cloud no bloquea: validar assisted con teléfono internacional.
9. Registrar baseline Owner opcional antes de iniciar actividad. Indicar fuente/metodología en notas.
10. Comprobar Owner readiness. Corregir todos los booking blockers. Activar el negocio con el hash
    vigente; después confirmar `pilot_ready` y tratar warnings de integración/backup.
11. Hacer reserva invitada real de prueba, confirmarla en Admin, comprobar página móvil, login
    opcional y repeat booking. Borrar/corregir solo datos ficticios conforme al checklist, nunca usar
    un reset genérico sobre un piloto real.
12. Ejecutar `python scripts/check_pilot_configuration.py --json`, identificar build en
    `/api/config/build` y asociar el backup verificado del entorno.

Referencias: [business onboarding](business_onboarding_operations.md),
[readiness](business_readiness.md), [capabilities](pilot_module_capabilities.md),
[valor](pilot_value_attribution.md), [E2E](playwright_e2e.md) y
[robustez backend](backend_pilot_robustness.md).
