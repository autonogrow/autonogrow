# Rotación de secretos

`check_secret_rotation_readiness.py` solo informa booleanos y nunca imprime valores. Rotar por separado sesión, OAuth/Meta, SMTP, webhook y keyring. Cambiar SESSION_SECRET invalida sesiones existentes.

Para cifrado de integraciones: añadir nueva versión, marcarla activa, recifrar con el script existente, verificar conteos y conservar la clave anterior durante la ventana de rollback. No retirar una clave mientras exista ciphertext con esa versión. Auditar inicio/resultado sin valores.
