"""Read-only capability and readiness sanity check; never calls external providers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.database import SessionLocal  # noqa: E402
from app.models import Business, BusinessModuleAccess  # noqa: E402
from app.models.business_module import PRODUCT_MODULES  # noqa: E402
from app.services.business_readiness_service import evaluate_business_readiness  # noqa: E402


def evaluate() -> dict:
    problems: list[dict[str, object]] = []
    readiness: list[dict[str, object]] = []
    with SessionLocal() as db:
        businesses = db.query(Business).order_by(Business.id).all()
        for business in businesses:
            rows = {
                row.module_key: row
                for row in db.query(BusinessModuleAccess)
                .filter(BusinessModuleAccess.business_id == business.id)
                .all()
            }
            missing = sorted(set(PRODUCT_MODULES) - set(rows))
            if missing:
                problems.append(
                    {"business_id": business.id, "code": "missing_module_rows", "modules": missing}
                )
            essential = rows.get("essential")
            if essential and (not essential.entitled or not essential.active):
                problems.append(
                    {"business_id": business.id, "code": "essential_not_available"}
                )
            invalid = sorted(
                key for key, row in rows.items() if row.active and not row.entitled
            )
            if invalid:
                problems.append(
                    {
                        "business_id": business.id,
                        "code": "active_without_entitlement",
                        "modules": invalid,
                    }
                )
            result = evaluate_business_readiness(db, business)
            readiness.append(
                {
                    "business_id": business.id,
                    "booking_ready": result["booking_ready"],
                    "pilot_ready": result["pilot_ready"],
                    "booking_blockers": result["blocking"],
                    "pilot_blockers": result["pilot_blocking"],
                }
            )
    return {
        "ok": not problems,
        "business_count": len(readiness),
        "capability_problems": problems,
        "readiness": readiness,
        "read_only": True,
        "external_provider_calls": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = evaluate()
    print(json.dumps(result, sort_keys=True) if args.json else result)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
