# Plantillas de onboarding

El catálogo versionado incluye genérica, barbería/peluquería, manicura/estética, taller, restaurante y clínica/consulta. Puede sugerir servicios, horarios, reglas, branding, textos y automatizaciones.

Cada aplicación crea filas propias con `business_id` destino y `source_key`; repetirla en la misma sesión no duplica servicios. Cambiar plantilla exige confirmación y, por defecto, conserva lo editado. Nunca se admiten credenciales, tokens, account IDs, clientes, emails o teléfonos reales. El seed ejecuta un escaneo recursivo de claves prohibidas.

Para una nueva versión, añadir una entrada con versión superior al catálogo y ejecutar el seed dry-run/apply. No mutar una versión ya usada si el cambio rompe su significado operativo.
