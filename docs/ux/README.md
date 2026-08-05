# Auditoría UX/UI y arquitectura frontend — Sprint 5A.1

Fecha de corte: 4 de agosto de 2026. Rama analizada: `main` (`dd17208`).

## Resumen ejecutivo

AutonoGrow ya cubre el ciclo funcional principal —captación, reserva, operación, mensajería e integraciones Meta—, pero la interfaz expone esa amplitud como una colección plana de funciones. El mayor riesgo para un piloto no es la falta de capacidad, sino la dificultad para reconocer qué hacer ahora, qué es configuración ocasional y qué estado requiere intervención.

Los hallazgos prioritarios son:

1. Business Admin presenta 11 secciones de igual peso. Citas de hoy, mensajes y tareas pendientes compiten con configuración poco frecuente.
2. Owner concentra configuración comercial, usuarios, marca, canales, salud, credenciales y automatización dentro de cada tarjeta de negocio. No existe una cola transversal de aprobaciones ni una vista propia de integraciones.
3. La landing tiene una sola estructura funcional y seis variantes CSS. La variación es principalmente visual; equipo, prueba social y datos prácticos no tienen secciones suficientemente explícitas.
4. Los cinco frontends duplican botones, tarjetas, estados, formularios y feedback. `autonogrow-shared/` solo comparte autenticación y estilos legales.
5. `admin.js` y `owner.js` mezclan navegación, API, estado y renderizado. El sistema funciona, pero su coste de cambio y prueba crece con cada sprint.
6. La base semántica es razonable —`lang`, títulos, etiquetas y botones reales—, aunque pestañas, modales, foco, mensajes dinámicos y áreas táctiles necesitan trabajo para aspirar a WCAG 2.2 AA.

La recomendación es conservar HTML/CSS/JavaScript vanilla y evolucionar por estrangulamiento: primero tokens, shell y primitivas compatibles con las clases actuales; después reorganizar una familia funcional por sprint sin alterar endpoints, permisos ni contratos de seguridad.

## Arquitectura recomendada

- Business Admin: **Inicio**, **Agenda**, **Clientes y mensajes**, **Crecimiento** y **Más**. En móvil: Inicio, Agenda, Mensajes y Más.
- Owner: **Resumen**, **Negocios**, **Altas y aprobaciones**, **Integraciones**, **Incidencias**, **Operaciones**, **Auditoría** y Configuración secundaria.
- Landing: mantener una estructura accesible y configurable, con bloques opcionales de confianza, equipo y reseñas; preservar las seis identidades visuales como temas.
- Shared: tokens de marca y semánticos, shell, botones, formularios, badges, feedback, diálogos y utilidades JS de API/DOM/accesibilidad.

Esta arquitectura no cambia la separación de roles ni las compuertas actuales: permiso comercial, candidatura, aprobación Owner, envío integrado y automatización continúan siendo estados independientes.

## Método y límites

Se inspeccionaron los HTML, CSS y JavaScript de `autonogrow-admin`, `autonogrow-owner`, `autonogrow-customer`, `autonogrow-landing` y `autonogrow-shared`, y se cruzaron sus llamadas con el OpenAPI generado por el backend. Las cifras de CSS/JS son recuentos mecánicos aproximados sobre el código fuente; no equivalen a componentes únicos ni a deuda confirmada.

No había Chrome, Edge, Firefox, Playwright ni Selenium ejecutables en el entorno. La sección responsive es, por tanto, una auditoría estática de reglas y estructura. Los problemas marcados como “probable” deben reproducirse en navegador con sesión y datos representativos antes de considerarse defectos visuales confirmados. No se modificó código funcional.

## Documentos

1. [Inventario frontend](01_frontend_inventory.md)
2. [Navegación actual](02_current_navigation.md)
3. [Mapa frontend/API](03_frontend_api_map.md)
4. [Contratos DOM](04_dom_contracts.md)
5. [Auditoría Business Admin](05_admin_ux_audit.md)
6. [Auditoría Owner](06_owner_ux_audit.md)
7. [Auditoría landing](07_landing_ux_audit.md)
8. [Responsive y accesibilidad](08_responsive_accessibility.md)
9. [Componentes compartidos, CSS y JavaScript](09_shared_components.md)
10. [Arquitectura de información propuesta](10_proposed_information_architecture.md)
11. [Flujos críticos](11_critical_user_flows.md)
12. [Roadmap de rediseño](12_redesign_roadmap.md)
13. [Sistema visual compartido](13_design_system.md)
14. [Shell responsive](14_shell_responsive.md)
15. [Dashboard operativo del Business Admin](15_admin_dashboard.md)
16. [Agenda y gestión de reservas del Business Admin](16_admin_agenda.md)
17. [Clientes y conversaciones del Business Admin](17_admin_conversations.md)
18. [Configuración del negocio en Business Admin](18_admin_business_configuration.md)
19. [Canales y automatizaciones del Business Admin](19_admin_channels_automations.md)
20. [Reseñas y crecimiento del Business Admin](20_admin_growth_reviews.md)
21. [QA transversal del Business Admin](21_admin_cross_section_qa.md)
22. [Dashboard operativo del panel Owner](22_owner_dashboard.md)
23. [Negocios, altas y aprobaciones del panel Owner](23_owner_businesses_approvals.md)
24. [Integraciones, incidencias y operaciones del panel Owner](24_owner_integrations_operations.md)

## Principios de implementación

- Preservar IDs, `data-*`, hashes, parámetros, funciones globales y selectores documentados hasta migrar cada consumidor.
- Mantener permisos Owner/Admin y filtros por negocio en servidor; la nueva navegación nunca sustituye autorización.
- Mostrar primero lenguaje operativo y reservar OAuth, WABA, token, webhook, job e IDs para un detalle avanzado.
- Introducir componentes compartidos mediante alias de clases y mejoras progresivas, no sustituciones masivas.
- Validar cada etapa a 360, 390, 768, 1024 y 1440 px, con teclado, zoom 200/400 % y al menos NVDA o VoiceOver.
