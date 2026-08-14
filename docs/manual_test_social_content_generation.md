# Prueba manual — Social Content Generation

## Preparación

1. Guardar una copia de la base de prueba, aplicar `alembic upgrade head` y confirmar una sola head `20260814_19`.
2. Activar Instagram Content para un negocio de prueba y acceder como Business Admin.
3. Preparar ideas activas de cada formato y assets propios/ajenos, activos/inactivos y asociados/no asociados a un servicio.

## Recorrido funcional

1. Abrir Admin > Instagram > Ideas recomendadas, aceptar una idea y comprobar que aparece `Generar borrador`.
2. Generarla. Debe aparecer una sola pieza en estado Borrador, enlazada a la idea, con v1 y sin fecha ni job de publicación.
3. Repetir la llamada de generación. Debe devolver la misma pieza y no crear otra versión.
4. Revisar hook, titular, caption, CTA, hashtags, dirección visual, material recomendado/pendiente y metadatos de origen.
5. Probar reel (planos/texto en pantalla), story (frames), carrusel (slides) y post estático.
6. Guardar una edición. Debe aparecer v2, conservarse v1 y mantenerse Borrador.
7. Regenerar. Debe aparecer v3 con hook rotado y conservar v1/v2.
8. Añadir assets finales, enviar a revisión y validar con el flujo 6A/6B. Confirmar que editar después invalida la validación y cancela el job pendiente.

## Seguridad y frescura

1. Intentar generar como Business Staff: 403. Intentar usar propuesta/contenido de otro tenant: 404.
2. Cambiar una señal fuente a resuelta tras aceptar: la generación usa el snapshot y muestra aviso.
3. Marcar la propuesta expirada/resuelta/no aceptada: debe bloquearse con 409.
4. Desactivar/archivar el servicio o retirar autorización de la reseña: debe bloquearse con 409.
5. Confirmar que una reseña no vuelca texto, autor ni PII en el paquete o auditoría.
6. Confirmar que un asset ajeno o inactivo no se recomienda; el asociado al servicio precede al general.
7. Revisar que no se inventan descuento, urgencia, ubicación, precio o resultado garantizado y que hay 3–8 hashtags.
8. Confirmar que no se crea multimedia y que story/reel no llegan al publicador real 6C.1 si el adapter no los soporta.

## Migración y regresión

1. En una SQLite vacía: `upgrade head`, `downgrade 20260814_18`, `upgrade head`.
2. Confirmar que la relación propuesta/contenido usa `SET NULL` y que no hay dos contenidos para una propuesta.
3. Ejecutar pytest completo, Ruff, mypy, validación de Alembic, predeploy y smoke tests.
4. Revisar que cambios locales de 6C.1 no formen parte del commit de Sprint 9B.
