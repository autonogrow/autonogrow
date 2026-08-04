# 07 — Auditoría de la landing pública

## Estructura real

Existe **una estructura HTML y un flujo JavaScript**, no seis landings independientes. Los temas `classic`, `elegant`, `beauty`, `clinic`, `urban` y `minimal` aplican color, tipografía, bordes, espaciado y, en algunos casos, reordenación CSS. `getLandingLabels()` adapta etiquetas al tipo de negocio; los datos y medios cambian por negocio.

Por tanto:

- comunes: autenticación, hero, navegación por anclas, descripción, servicios, galería opcional, reserva, contacto, CTA WhatsApp y footer;
- dependientes del negocio: textos, categoría, servicios, profesionales, disponibilidad, imágenes, contacto, enlaces y colores;
- solo visuales: la mayor parte de las seis plantillas;
- estructuras funcionales distintas: **una**, con bloques opcionales por datos;
- duplicación principal: reglas CSS repetidas/solapadas por selectores de tema, no HTML ni API.

`data/businesses.json` conserva cinco demos históricas con URLs externas de imágenes; `loadBusiness()` consulta actualmente el backend y no usa ese JSON como fuente de producción. Debe tratarse como fixture/demo hasta decidir su destino en otro sprint.

## Evaluación

| Área | Estado actual | Riesgo/oportunidad conceptual |
|---|---|---|
| Hero | nombre, descripción, imagen y CTA | Falta prueba rápida de confianza: categoría, barrio, próxima disponibilidad o valoración verificable |
| CTA | “Reservar” domina y hay WhatsApp final | Correcto; evitar competir con demasiadas anclas |
| Servicios | cards + repetición en select | La repetición ayuda a explorar pero obliga a volver a seleccionar; una acción “Reservar este servicio” puede preseleccionar |
| Reserva | flujo completo service/staff/calendar/slot/contact/photos | Es la parte más valiosa; demasiados controles se revelan en una sola página y errores usan alertas |
| Sin disponibilidad | ofrece contacto | Buena degradación; debe conservar contexto del servicio al ir a WhatsApp |
| Galería | carrusel con botones/indicadores | Indicadores de 10×10 px no son objetivo táctil suficiente; falta anuncio de cambio |
| Equipo | solo select de profesional | No ayuda a generar confianza antes de reservar; bloque opcional con nombre/especialidad/foto |
| Horarios | disponibilidad calculada, no horario informativo claro | El visitante no puede conocer apertura sin iniciar reserva |
| Reseñas | enlace externo si existe | Falta prueba social visible; no inventar puntuaciones ni copiar reseñas sin fuente/permiso |
| Ubicación | dirección y mapa externo | Útil; podría indicar zona/accesibilidad/transporte si el negocio aporta datos |
| Instagram/WhatsApp | enlaces externos | Correctos, pero el destino externo debe expresarse; WhatsApp no debe sustituir reserva disponible |
| Confianza | marca + información de contacto | Faltan políticas de cancelación/reserva y confirmación esperada cerca del formulario |
| Imágenes | logo/hero/galería | Alt y dimensiones/rendimiento deben normalizarse; evitar recursos demo externos en producción |
| Auth strip | acceso a Mis citas | útil para retorno, pero compite visualmente con la marca del negocio |

## Flujo de reserva actual

1. Elegir servicio.
2. Cargar y elegir profesional disponible.
3. Insertar calendario dinámico y consultar días.
4. Elegir día y cargar huecos.
5. Elegir hora.
6. Introducir nombre, teléfono, notas y fotos opcionales.
7. Crear la reserva.
8. Subir fotos con token de gestión; si falla, la reserva permanece creada.
9. Mostrar confirmación y acceso a cuenta/calendario/contacto.

La lógica evita carreras al cambiar servicio mediante un contador de versión y recarga slots ante conflicto. Son garantías que el rediseño debe preservar.

## Consistencia de temas

La variación temática es válida para negocios locales, pero hoy cada variante amplía el CSS global y crea combinaciones no verificadas en cada breakpoint. La dirección recomendable es una estructura común con tokens por tema:

- color de marca y contraste;
- familia/tamaño tipográfico;
- radio/sombra/borde;
- densidad y tratamiento del hero;
- decoración específica limitada.

No eliminar ninguna plantilla. Primero hacer pruebas de regresión por tema y mapear reglas a tokens; solo después deduplicar selectores.

## Prioridades antes de piloto

1. Asegurar que reservar es visible y realizable a 360/390 px con teclado y lector.
2. Feedback inline accesible para disponibilidad, conflicto y confirmación; eliminar dependencia de `alert` en otro sprint.
3. Añadir horario, equipo y prueba social como bloques opcionales basados en datos reales.
4. Explicar confirmación, cancelación, privacidad de fotos y canal de contacto cerca de la decisión.
5. Optimizar medios: dimensiones, `loading`, formatos, alt útil y ausencia de recursos demo de terceros.
6. Medir conversión por paso antes de alterar el orden; no asumir que una plantilla “bonita” convierte mejor.

## Componentes compartibles

Hero, section heading, service card, media gallery, professional card, availability picker, feedback, confirmation, contact card y CTA pueden ser componentes lógicos en vanilla JS/CSS. Los temas deberían configurar esos componentes, no duplicar su marcado ni su comportamiento.

