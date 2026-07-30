# Pruebas de restauración

`test_postgresql_restore.py` requiere `RESTORE_TEST_DATABASE_URL` y un nombre `autonogrow_restore_* `. Rechaza el origen como destino y no actúa sin `--apply`. Crea la DB aislada, restaura, verifica head, tablas, relaciones y conteos agregados, y la elimina salvo `--keep-temporary-database`.

Nunca descifra tokens: solo valida presencia conjunta de ciphertext y versión. Una restauración real de staging/production requiere aprobación, mantenimiento, backup previo y el runbook de incidente.
