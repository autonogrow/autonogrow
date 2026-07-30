# Logging y redacción

Staging/production resuelven `LOG_FORMAT=auto` a JSON; local usa texto. Cada petición obtiene un `X-Request-ID` validado o UUID. Los logs incluyen evento, operación, duración, resultado y release sin identificadores de negocio como labels.

La redacción defensiva cubre token, authorization, cookie, password, secret, api_key, encryption, ciphertext, session, csrf, smtp y database_url sin distinguir mayúsculas. No registrar datos personales ni payloads. Journald gestiona retención; la app nunca ejecuta vacuum de logs.
