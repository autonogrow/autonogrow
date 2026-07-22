# Prueba manual: jerarquía de landing, confirmación y owner superadmin

## Landing pública

1. Abrir negocios de prueba con cada plantilla, especialmente `beauty`, en escritorio y móvil.
2. Confirmar que el primer bloque del contenido muestra, en este orden: logo si existe,
   nombre, categoría, titular y descripción.
3. Repetir con y sin logo, titular, descripción y galería. No deben quedar huecos extraños
   ni debe aparecer la galería antes de la identidad.
4. Completar una reserva y comprobar que el scroll termina al inicio del bloque verde de
   confirmación, dejando visibles el resumen y **Añadir a mi calendario**.
5. Forzar un error de reserva y comprobar que la página permanece junto al formulario.

## Owner superadmin

1. Entrar como owner y abrir `autonogrow-admin/?b={slug}` para un negocio donde el owner
   no figure en `business_users`.
2. Comprobar configuración, servicios, equipo, disponibilidad, reservas, mensajes y galería.
3. Modificar un servicio y la ficha de un miembro; asignarle servicios.
4. Eliminar y reactivar un miembro sin citas bloqueantes. El único administrador activo
   debe seguir protegido.
5. Verificar que las acciones quedan registradas con el usuario owner como actor.
6. Entrar como administrador de otro negocio, personal y customer. Deben conservar sus
   límites y recibir `403` al intentar acceder a un negocio o acción no autorizados.
