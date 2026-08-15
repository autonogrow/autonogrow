# Hotfix Sprint 10A: carga Owner de Contenido Instagram

El panel Owner carga el workspace activo con tres requests constantes: settings, material bruto y
la colección detallada de contenidos. La colección incluye los datos editoriales que antes se
obtenían mediante un request adicional por contenido. Las mutaciones reutilizan su respuesta o,
cuando la operación solo devuelve un job, hacen una lectura focalizada del contenido afectado.

El bucket global `authenticated` conserva el límite de 180 requests cada 60 segundos. Owner,
Admin y Customer comparten ese bucket por IP, por lo que la actividad simultánea desde una misma
salida de red consume la misma cuota.

## Deuda para producción

El limiter actual guarda los buckets en memoria y solo coordina las solicitudes atendidas por un
solo proceso. Un despliegue con varios workers tendría contadores independientes y no ofrecería un
límite global consistente. Antes de escalar horizontalmente debe adoptarse un almacén compartido,
por ejemplo Redis, junto con métricas y una política explícita para proxies y resolución de la IP
cliente. Esa infraestructura queda deliberadamente fuera de este hotfix.
