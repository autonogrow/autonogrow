"""Re-encrypt integration credentials with the configured active key version."""

from app.core.config import get_settings
from app.core.database import SessionLocal, create_db_and_tables
from app.models import (
    BusinessChannelIntegration,
    InstagramOAuthAttempt,
    WhatsAppEmbeddedSignupAttempt,
)
from app.services.instagram_integration_service import reencrypt_integration_secret
from app.services.integration_crypto_service import (
    decrypt_secret,
    encrypt_secret,
    load_encryption_configuration,
)


def main() -> int:
    settings = get_settings()
    configuration = load_encryption_configuration(settings, required=True)
    create_db_and_tables()
    db = SessionLocal()
    changed = 0
    try:
        rows = (
            db.query(BusinessChannelIntegration)
            .filter(BusinessChannelIntegration.encrypted_access_token.is_not(None))
            .all()
        )
        for integration in rows:
            if integration.encryption_key_version == configuration.active_version:
                continue
            reencrypt_integration_secret(integration, settings=settings)
            changed += 1
        for candidate_model in (InstagramOAuthAttempt, WhatsAppEmbeddedSignupAttempt):
            candidates = (
                db.query(candidate_model)
                .filter(candidate_model.candidate_encrypted_access_token.is_not(None))
                .all()
            )
            for candidate in candidates:
                if candidate.candidate_encryption_key_version == configuration.active_version:
                    continue
                plaintext = decrypt_secret(
                    candidate.candidate_encrypted_access_token or "",
                    candidate.candidate_encryption_key_version or "",
                    settings=settings,
                )
                ciphertext, version = encrypt_secret(plaintext, settings=settings)
                candidate.candidate_encrypted_access_token = ciphertext
                candidate.candidate_encryption_key_version = version
                changed += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"Credenciales de integración y candidaturas recifradas: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
