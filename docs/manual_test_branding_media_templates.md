# Pruebas manuales: marca, multimedia y plantillas

## Preparación

1. Desde `backend`, activar el entorno y ejecutar `python -m app.seed`.
2. Iniciar la API con `uvicorn app.main:app --reload`.
3. Servir la raíz del repositorio en `http://127.0.0.1:5500` (por ejemplo, con Live Server).
4. Abrir `autonogrow-owner/index.html` y comprobar que la API responde en `http://127.0.0.1:8000`.

## Owner Panel

1. Abrir una tarjeta, desplegar **Marca y apariencia**, subir un PNG/JPG/WEBP como logo y verificar la miniatura de la tarjeta.
2. Abrir el Admin y la Landing del mismo negocio; verificar que ambos muestran el logo y que la Landing mantiene visible el nombre.
3. Eliminar el logo. Verificar que la Landing vuelve a mostrar el nombre sin huecos ni errores.
4. Subir tres fotos con texto alternativo. Cambiar posición, desactivar una, guardar y comprobar las miniaturas.
5. Eliminar una foto y verificar que desaparece también de la Landing.
6. Elegir una paleta, guardar y recargar Owner; comprobar que persiste.
7. Cambiar manualmente principal, acento y fondo; comprobar que la paleta cambia a **Personalizado**, guardar y recargar.
8. Cambiar entre `classic`, `elegant`, `beauty`, `clinic`, `urban` y `minimal` y abrir la Landing para comprobar la variación visual.

## Admin del negocio

1. En **Datos del negocio → Marca y apariencia**, cambiar/subir/eliminar el logo.
2. Añadir fotos, editar texto alternativo y posición, activar/desactivar y eliminar.
3. Seleccionar una paleta: los cuatro colores deben rellenarse automáticamente.
4. Modificar un selector o hexadecimal: la paleta debe pasar a **Personalizado**.
5. Guardar, recargar Admin y Owner y comprobar que los colores personalizados persisten.

## Landing

1. Con logo: verificar logo y nombre visibles. Sin logo: verificar el nombre en texto.
2. Con fotos activas: verificar carrusel, anterior/siguiente, indicadores y avance automático cada cinco segundos.
3. Sin fotos activas: verificar que la sección completa del carrusel no aparece.
4. Comprobar en cada cambio que `--color-primary`, `--color-secondary`, `--color-accent` y `--color-background` reflejan exactamente la configuración.
5. Probar una plantilla inválida o vacía mediante API y comprobar el fallback visual `classic`.
6. Completar una reserva para confirmar que agenda, huecos y formulario siguen funcionando.

## Altas rápidas

1. En **Nuevo negocio**, seleccionar `fisioterapia`.
2. Verificar categoría, titular, descripción, horario, tres servicios, paleta `blue_clinic` y plantilla `clinic`.
3. Crear el negocio y comprobar en Admin y Landing que servicios, colores y plantilla se aplicaron.
4. Repetir una comprobación breve con `manicura`, `barberia` y `taller`.

## Validaciones y límites

1. Intentar subir SVG, GIF o un archivo cuyo MIME/extensión no coincida: debe rechazarse.
2. Intentar logo mayor de 3 MB y foto mayor de 5 MB: debe rechazarse.
3. Intentar activar/subir más de diez fotos activas: debe rechazarse.
4. Enviar un color distinto de `#RRGGBB`: debe devolver validación 422.
5. Ejecutar dos veces `python -m app.seed` después de guardar colores personalizados. Verificar que `theme_key=custom`, colores, plantilla, logo y galería no cambian.
6. Probar un negocio sin logo ni fotos: listado, Admin y Landing deben cargar normalmente.

## Bugfix subida frontend

1. En Owner, desplegar **Marca y apariencia** y pulsar **Subir logo**: debe abrirse el selector de archivo.
2. Elegir JPG, PNG o WEBP: la subida debe comenzar automáticamente, mostrar confirmación y refrescar logo y badge sin recarga manual.
3. Pulsar **Subir foto**, elegir una imagen y comprobar que aparece la miniatura y cambia el badge de fotos.
4. Repetir logo y foto desde Admin. Los inputs de archivo deben permanecer ocultos y los botones deben abrirlos.
5. Confirmar que Admin refresca logo y galería; abrir Landing y comprobar logo y carrusel.
6. Ante un archivo inválido, comprobar un mensaje con status HTTP y detalle del backend; revisar también el objeto de error en consola.
7. Verificar que las peticiones multipart no establecen manualmente `Content-Type`.
