# Prueba manual: actualización automática del panel

## Preparación

1. Arranca el backend y abre el panel Admin autenticado en dos ventanas para el mismo negocio.
2. En la primera ventana abre **Conversaciones**, selecciona un hilo y deja escrito un borrador sin enviarlo.
3. Anota la posición del hilo y comprueba el indicador de sincronización de la cabecera.

## Conversaciones visibles

1. Desde la segunda ventana o desde Instagram, añade un mensaje al hilo seleccionado.
2. Con la primera pestaña visible, comprueba que el hilo se actualiza en unos 5 segundos y la lista en unos 10 segundos.
3. Si el hilo estaba al final, debe seguir el mensaje nuevo.
4. Repite mientras lees mensajes antiguos: no debe moverse el scroll y debe aparecer **Hay mensajes nuevos**.
5. Pulsa el aviso y comprueba que baja al final.
6. Confirma que el borrador, los filtros y la conversación seleccionada se conservan.

## Pestaña oculta y vuelta a primer plano

1. Oculta la primera pestaña y genera otro mensaje, una reserva y un cambio de outbox.
2. Espera al menos 30 segundos. Al volver, debe ejecutarse además una actualización inmediata de lista, hilo, sugerencias y contadores.
3. Comprueba que el indicador pasa por **Actualizando** y muestra la hora de la última actualización.

Los navegadores pueden ralentizar o suspender temporizadores ocultos. Este polling mejora la sincronización del panel, pero las notificaciones fiables en segundo plano corresponden a la futura integración PWA/Web Push.

## Fallo temporal

1. Detén temporalmente el backend con el panel abierto.
2. Comprueba que los datos ya visibles no desaparecen y el indicador cambia a **Error temporal**.
3. Arranca de nuevo el backend: el panel debe reintentar con backoff y volver a **Conectado**.
4. Verifica que el botón **Actualizar** sigue funcionando como respaldo.

## Acciones locales

Comprueba que enviar un mensaje, usar o descartar una sugerencia, cambiar el estado de una conversación, guardar automatización y cambiar una reserva provocan un refresco inmediato sin recargar la página.
