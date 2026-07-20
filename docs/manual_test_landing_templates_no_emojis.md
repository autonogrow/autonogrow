# Pruebas manuales: plantillas de landing sin emojis

## Preparación

1. En `backend`, ejecutar `python -m app.seed` y arrancar `uvicorn app.main:app --reload`.
2. Servir la raíz del repositorio en `http://127.0.0.1:5500`.
3. Abrir Owner, Admin y Landing con la caché del navegador desactivada durante la prueba.

## Textos y símbolos

1. Recorrer Landing, Admin y Owner y comprobar que no aparecen emojis fijos en títulos, botones, pestañas, tarjetas ni mensajes.
2. Comprobar que **Catálogo** no aparece como título o acción genérica.
3. Verificar los textos neutros: **Servicios**, **Reservar cita**, **Galería**, **Contacto**, **Horario** y **Ubicación**.
4. Confirmar que los datos escritos por usuarios no se modifican.

## Diferencias entre plantillas

1. `classic`: hero, servicios, reserva, galería opcional e información/contacto en un recorrido equilibrado.
2. `elegant`: hero amplio, galería alta cerca del inicio, tarjetas más editoriales y reserva estrecha destacada.
3. `beauty`: galería antes del hero cuando existen fotos, servicios en tres columnas y superficies redondeadas.
4. `clinic`: lectura alineada a la izquierda, tratamientos en filas, reserva destacada e información práctica antes de instalaciones.
5. `urban`: hero de alto contraste, galería inmediata, servicios grandes y CTA visible arriba.
6. `minimal`: sin accesos secundarios, una sola columna y galería al final.
7. Comparar específicamente `classic` con `beauty`, `clinic` con `urban`, y `minimal` con `elegant`.

## Labels adaptadas

1. En `clinic`, comprobar **Tratamientos**, **Reservar consulta** e **Instalaciones**.
2. En `beauty`, comprobar **Servicios**, **Reservar cita** y **Trabajos**, sin símbolos decorativos.
3. En `urban`, comprobar **Reserva tu hora** y botón **Reservar**.
4. Con `template_key` vacío o inválido, comprobar fallback visual `classic` y labels por defecto.
5. Una categoría clínica debe mantener labels profesionales aunque use el fallback.

## Negocios y regresiones

1. Crear un taller con la alta rápida: debe usar `minimal`, hablar de diagnóstico/revisión y no mostrar textos de belleza.
2. Crear una manicura con `beauty`: no debe mostrar emojis y la galería debe ser protagonista cuando tenga fotos.
3. Comprobar que los selectores de plantilla en Admin y Owner muestran su descripción breve.
4. Subir logo y fotos; verificar logo, carrusel, anterior/siguiente, indicadores y autoplay.
5. Aplicar una paleta y luego colores personalizados; verificar las cuatro variables CSS tras recargar.
6. Completar una reserva desde selección de servicio hasta confirmación.
7. Repetir en móvil: hero, servicios, calendario, formulario, galería y contacto no deben desbordar horizontalmente.

## Revisión visual de plantillas

1. Revisar `classic`, `elegant`, `beauty`, `clinic`, `urban` y `minimal` a ancho desktop y a 390 px.
2. En Minimal, comprobar que cards, bordes, botones y galería quedan contenidos; ninguna línea debe salir de la sección.
3. Confirmar que `document.documentElement.scrollWidth` no supera `window.innerWidth`.
4. En móvil, comprobar botones a ancho cómodo, hero más corto, cards a una columna y calendario a dos columnas.
5. En Beauty y Elegant, comprobar que la galería mantiene protagonismo sin tapar la reserva.
6. En Clinic, confirmar jerarquía limpia de tratamientos, reserva y contacto.
7. En Urban, confirmar contraste legible y servicios contenidos dentro del bloque oscuro.
8. Completar una reserva tras cambiar de plantilla para verificar que el pulido CSS no altera el formulario.

## Corrección visual template Minimal

1. Confirmar que el título **Servicios** y su subtítulo tienen padding lateral y no quedan pegados al panel.
2. Verificar que cada servicio se presenta como una card con borde suave, esquinas redondeadas y padding interno.
3. En desktop, comprobar que nombre/metadatos y descripción/botón forman dos columnas con separación suficiente.
4. Confirmar que el botón de reserva no queda pegado al borde derecho.
5. Verificar que no hay contenido cortado, separadores bruscos ni líneas fuera del contenedor.
6. A 390 px, comprobar cards a una columna, botón a ancho completo y ausencia de scroll horizontal.
7. Completar una reserva y confirmar que logo, colores y galería siguen funcionando.

## Corrección global de espaciado en landing

1. Verificar que Servicios, Reserva, Sobre el negocio, Galería y Contacto comparten padding lateral coherente.
2. Comprobar que el formulario, calendario, días y huecos quedan contenidos dentro del panel de reserva.
3. Confirmar que horario, dirección y enlaces se presentan dentro de una card con separación entre filas y acciones.
4. Verificar que el carrusel, controles e indicadores respetan el padding de la sección.
5. Confirmar que el bloque final de contacto tiene aire lateral y que sus botones no tocan los extremos.
6. A 390 px, comprobar todas las secciones, cards e inputs sin cortes ni scroll horizontal.
7. Confirmar que Minimal ya no muestra ninguna sección cruda o pegada al borde.
8. Revisar Classic, Elegant, Beauty, Clinic y Urban para confirmar que conservan su composición propia.
9. Completar una reserva y verificar logo, colores personalizados, fotos y carrusel.
