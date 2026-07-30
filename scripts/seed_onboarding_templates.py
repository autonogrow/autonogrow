"""Versioned, dry-run-first seed for reusable onboarding templates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import SessionLocal  # noqa: E402
from app.models import BusinessOnboardingTemplate  # noqa: E402
from app.services.onboarding_template_catalog import (  # noqa: E402
    SYSTEM_ONBOARDING_TEMPLATES,
    template_has_forbidden_data,
)


def seed_templates(*, apply: bool = False, session_factory=SessionLocal) -> dict[str, int]:
    result = {"created": 0, "updated": 0, "unchanged": 0, "custom_skipped": 0}
    with session_factory() as db:
        for definition in SYSTEM_ONBOARDING_TEMPLATES:
            findings = template_has_forbidden_data(definition)
            if findings:
                raise RuntimeError(f"Unsafe template fields: {', '.join(findings)}")
            key = str(definition["key"])
            version = int(definition["version"])
            configuration = json.dumps(
                definition["configuration"], ensure_ascii=False, sort_keys=True
            )
            row = (
                db.query(BusinessOnboardingTemplate)
                .filter(
                    BusinessOnboardingTemplate.key == key,
                    BusinessOnboardingTemplate.version == version,
                )
                .first()
            )
            if row is None:
                result["created"] += 1
                db.add(
                    BusinessOnboardingTemplate(
                        key=key,
                        version=version,
                        name=str(definition["name"]),
                        category=str(definition["category"]),
                        description=str(definition["description"]),
                        configuration_json=configuration,
                        is_active=True,
                        is_system=True,
                    )
                )
                continue
            if not row.is_system:
                result["custom_skipped"] += 1
                continue
            expected = (
                str(definition["name"]),
                str(definition["category"]),
                str(definition["description"]),
                configuration,
                True,
            )
            current = (
                row.name,
                row.category,
                row.description,
                row.configuration_json,
                row.is_active,
            )
            if current == expected:
                result["unchanged"] += 1
                continue
            result["updated"] += 1
            row.name, row.category, row.description, row.configuration_json, row.is_active = (
                expected
            )
        if apply:
            db.commit()
        else:
            db.rollback()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist the versioned seed")
    args = parser.parse_args()
    result = seed_templates(apply=args.apply)
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
