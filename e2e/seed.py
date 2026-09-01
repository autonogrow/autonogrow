from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.database import Base, create_database_engine  # noqa: E402
from app.core.security import create_session_token  # noqa: E402
from app.models import (  # noqa: E402
    AvailabilitySettings,
    Booking,
    Business,
    BusinessService,
    BusinessUser,
    BusinessUserAvailability,
    BusinessUserService,
    Customer,
    CustomerAccountLink,
    InstagramContent,
    InstagramContentEditorialReview,
    InstagramContentRawAsset,
    InstagramContentSettings,
    InstagramContentVersion,
    InstagramRawAsset,
    MessageOutbox,
    ReviewRequest,
    User,
)
from app.models.registry import register_models  # noqa: E402
from app.services.auth_session_service import create_auth_session  # noqa: E402

ALL_DAY_SCHEDULE = {str(day): [{"start": "09:00", "end": "18:00"}] for day in range(7)}
JPEG_BYTES = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EH//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EH//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EH//2Q=="
)


def database_url() -> str:
    value = os.environ.get("DATABASE_URL", "")
    if not value:
        raise RuntimeError("DATABASE_URL is required for the E2E seed")
    return value


def _business(slug: str, name: str, category: str, phone: str) -> Business:
    return Business(
        slug=slug,
        name=name,
        category=category,
        headline=f"Reserva online en {name}",
        description=f"Fixture aislado para los journeys de {name}.",
        phone=phone,
        whatsapp_phone=phone,
        city="Madrid",
        address="Calle E2E 10, Madrid",
        schedule="Todos los días, 09:00 - 18:00",
        reviews_url="https://reviews.e2e.test/business",
        status="active",
        primary_color="#176b5b",
        secondary_color="#20242a",
        accent_color="#e05b46",
        background_color="#f7f7f5",
        timezone="Europe/Madrid",
    )


def _booking(
    *,
    business: Business,
    customer: Customer,
    service: BusinessService,
    start: datetime,
    status: str,
    staff: BusinessUser,
    user: User | None = None,
    token: str,
) -> Booking:
    duration = service.duration_minutes or 45
    return Booking(
        business_id=business.id,
        customer_id=customer.id,
        customer_user_id=user.id if user else None,
        customer_email=user.email if user else None,
        public_manage_token=token,
        created_by_user=user is not None,
        service_id=service.id,
        staff_business_user_id=staff.id,
        service_name=service.name,
        duration_minutes=duration,
        price_amount_snapshot=service.price_amount,
        currency_snapshot="EUR",
        start_datetime=start,
        end_datetime=start + timedelta(minutes=duration),
        preferred_date=start.date().isoformat(),
        preferred_day_label=start.strftime("%Y-%m-%d"),
        preferred_time=start.strftime("%H:%M"),
        status=status,
        source="e2e",
    )


def _seed_instagram(db: Session, business: Business, owner: User, marker: str) -> None:
    local_today = datetime.now(ZoneInfo("Europe/Madrid")).date()
    local_midday = datetime.combine(local_today, time(hour=12), ZoneInfo("Europe/Madrid"))
    fixture_planned_at = local_midday.astimezone(timezone.utc)
    db.add(
        InstagramContentSettings(
            business_id=business.id,
            enabled=True,
            owner_can_validate_instagram_content=False,
            enabled_by_user_id=owner.id,
        )
    )
    review = InstagramContent(
        business_id=business.id,
        title=f"{marker} lanzamiento",
        status="ready_for_review",
        planned_publish_at=fixture_planned_at,
        created_by_user_id=owner.id,
    )
    published = InstagramContent(
        business_id=business.id,
        title=f"{marker} histórico protegido",
        status="published",
        planned_publish_at=fixture_planned_at - timedelta(hours=2),
        created_by_user_id=owner.id,
    )
    removable = InstagramContent(
        business_id=business.id,
        title=f"{marker} borrador eliminable",
        status="draft",
        created_by_user_id=owner.id,
    )
    db.add_all((review, published, removable))
    db.flush()
    versions = []
    for content, caption in (
        (review, f"Caption de revisión {marker}"),
        (published, f"Caption publicada {marker}"),
        (removable, f"Caption borrador {marker}"),
    ):
        version = InstagramContentVersion(
            business_id=business.id,
            content_id=content.id,
            version_number=1,
            caption=caption,
            format="single_image",
            created_by_user_id=owner.id,
        )
        db.add(version)
        versions.append(version)
    db.flush()
    db.add(
        InstagramContentEditorialReview(
            business_id=business.id,
            content_id=review.id,
            version_id=versions[0].id,
            status="approved",
            submitted_at=fixture_planned_at - timedelta(hours=1),
            reviewed_by_user_id=owner.id,
            reviewed_at=fixture_planned_at - timedelta(minutes=30),
            note="Revisión editorial E2E aprobada.",
        )
    )

    raw_dir = Path(os.environ["UPLOADS_DIR"]) / "_instagram_content" / str(business.id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    shared_path = raw_dir / f"{marker.lower()}-shared.jpg"
    removable_path = raw_dir / f"{marker.lower()}-removable.jpg"
    shared_path.write_bytes(JPEG_BYTES)
    removable_path.write_bytes(JPEG_BYTES)
    shared = InstagramRawAsset(
        business_id=business.id,
        uploaded_by_user_id=owner.id,
        original_filename=shared_path.name,
        storage_key=shared_path.relative_to(Path(os.environ["UPLOADS_DIR"])).as_posix(),
        media_type="image/jpeg",
        size_bytes=len(JPEG_BYTES),
        label=f"Material compartido {marker}",
    )
    freeable = InstagramRawAsset(
        business_id=business.id,
        uploaded_by_user_id=owner.id,
        original_filename=removable_path.name,
        storage_key=removable_path.relative_to(Path(os.environ["UPLOADS_DIR"])).as_posix(),
        media_type="image/jpeg",
        size_bytes=len(JPEG_BYTES),
        label=f"Material liberable {marker}",
    )
    db.add_all((shared, freeable))
    db.flush()
    db.add_all(
        (
            InstagramContentRawAsset(
                business_id=business.id,
                content_id=removable.id,
                raw_asset_id=shared.id,
                associated_by_user_id=owner.id,
            ),
            InstagramContentRawAsset(
                business_id=business.id,
                content_id=published.id,
                raw_asset_id=shared.id,
                associated_by_user_id=owner.id,
            ),
            InstagramContentRawAsset(
                business_id=business.id,
                content_id=removable.id,
                raw_asset_id=freeable.id,
                associated_by_user_id=owner.id,
            ),
        )
    )


def reset_database() -> None:
    register_models()
    engine = create_database_engine(database_url())
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        owner = User(
            email="owner@e2e.test",
            google_sub="google-owner-e2e",
            email_verified=True,
            name="Owner E2E",
            is_owner=True,
        )
        admin_a = User(
            email="admin-a@e2e.test",
            google_sub="google-admin-a-e2e",
            email_verified=True,
            name="Admin Salón E2E",
        )
        admin_b = User(email="admin-b@e2e.test", name="Admin Fisio E2E")
        customer_user = User(
            email="customer@e2e.test",
            google_sub="google-customer-e2e",
            email_verified=True,
            name="María E2E",
            preferred_name="María",
            phone="+34612345678",
            phone_normalized="+34612345678",
        )
        professional_users = [
            User(email=f"pro-{index}@e2e.test", name=name)
            for index, name in enumerate(("Lucía", "Carmen", "Diego", "Elena"), start=1)
        ]
        db.add_all((owner, admin_a, admin_b, customer_user, *professional_users))
        business_a = _business("salon-e2e", "Salón E2E", "Peluquería", "+34600111222")
        business_b = _business("fisio-e2e", "Fisio E2E", "Fisioterapia", "+34600999888")
        db.add_all((business_a, business_b))
        db.flush()

        admin_membership_a = BusinessUser(
            business_id=business_a.id, user_id=admin_a.id, role="business_admin", active=True
        )
        admin_membership_b = BusinessUser(
            business_id=business_b.id, user_id=admin_b.id, role="business_admin", active=True
        )
        staff_members = [
            BusinessUser(
                business_id=business_a.id if index < 2 else business_b.id,
                user_id=user.id,
                role="business_staff",
                active=True,
                public_name=user.name,
                bookable=True,
                show_schedule=True,
            )
            for index, user in enumerate(professional_users)
        ]
        db.add_all((admin_membership_a, admin_membership_b, *staff_members))

        services_a = [
            BusinessService(
                business_id=business_a.id,
                name="Corte E2E",
                description="Corte y acabado",
                price_text="35 €",
                price_amount=Decimal("35.00"),
                duration_text="45 min",
                duration_minutes=45,
                active=True,
            ),
            BusinessService(
                business_id=business_a.id,
                name="Color E2E",
                description="Coloración completa",
                price_text="60 €",
                price_amount=Decimal("60.00"),
                duration_text="60 min",
                duration_minutes=60,
                active=True,
            ),
        ]
        services_b = [
            BusinessService(
                business_id=business_b.id,
                name="Sesión Fisio E2E",
                price_text="45 €",
                price_amount=Decimal("45.00"),
                duration_text="45 min",
                duration_minutes=45,
                active=True,
            ),
            BusinessService(
                business_id=business_b.id,
                name="Masaje E2E",
                price_text="30 €",
                price_amount=Decimal("30.00"),
                duration_text="30 min",
                duration_minutes=30,
                active=True,
            ),
        ]
        db.add_all((*services_a, *services_b))
        db.flush()

        for business in (business_a, business_b):
            db.add(
                AvailabilitySettings(
                    business_id=business.id,
                    timezone="Europe/Madrid",
                    slot_interval_minutes=30,
                    buffer_between_bookings_minutes=0,
                    min_notice_minutes=0,
                    max_days_ahead=45,
                    auto_confirm_bookings=False,
                    weekly_schedule_json=json.dumps(ALL_DAY_SCHEDULE),
                )
            )
        for member in staff_members:
            services = services_a if member.business_id == business_a.id else services_b
            for service in services:
                db.add(BusinessUserService(business_user_id=member.id, service_id=service.id))
            for weekday in range(7):
                db.add(
                    BusinessUserAvailability(
                        business_user_id=member.id,
                        weekday=weekday,
                        windows_json=json.dumps(ALL_DAY_SCHEDULE[str(weekday)]),
                        active=True,
                    )
                )

        customer_a = Customer(
            business_id=business_a.id,
            name="María Cliente E2E",
            phone="612 345 678",
            phone_normalized="+34612345678",
        )
        customer_b = Customer(
            business_id=business_b.id,
            name="María Cliente E2E",
            phone="+34612345678",
            phone_normalized="+34612345678",
        )
        guest_a = Customer(business_id=business_a.id, name="Invitado Fixture", phone="611 000 111")
        db.add_all((customer_a, customer_b, guest_a))
        db.flush()
        db.add_all(
            (
                CustomerAccountLink(
                    user_id=customer_user.id,
                    customer_id=customer_a.id,
                    business_id=business_a.id,
                    link_method="e2e_fixture",
                ),
                CustomerAccountLink(
                    user_id=customer_user.id,
                    customer_id=customer_b.id,
                    business_id=business_b.id,
                    link_method="e2e_fixture",
                ),
            )
        )

        now = datetime.now().replace(second=0, microsecond=0)
        next_day = now + timedelta(days=1)
        next_day = next_day.replace(hour=10, minute=0)
        booking_a = _booking(
            business=business_a,
            customer=customer_a,
            service=services_a[0],
            start=next_day,
            status="confirmed",
            staff=staff_members[0],
            user=customer_user,
            token="e2e-customer-booking-a-token",
        )
        pending_a = _booking(
            business=business_a,
            customer=guest_a,
            service=services_a[1],
            start=now.replace(hour=15, minute=0),
            status="requested",
            staff=staff_members[1],
            token="e2e-pending-booking-a-token",
        )
        booking_b = _booking(
            business=business_b,
            customer=customer_b,
            service=services_b[0],
            start=next_day + timedelta(days=1),
            status="confirmed",
            staff=staff_members[2],
            user=customer_user,
            token="e2e-customer-booking-b-token",
        )
        completed = _booking(
            business=business_a,
            customer=guest_a,
            service=services_a[0],
            start=now.replace(hour=9, minute=0) - timedelta(days=1),
            status="completed",
            staff=staff_members[0],
            token="e2e-completed-booking-token",
        )
        completed_user = _booking(
            business=business_a,
            customer=customer_a,
            service=services_a[0],
            start=now.replace(hour=10, minute=30) - timedelta(days=7),
            status="completed",
            staff=staff_members[0],
            user=customer_user,
            token="e2e-completed-customer-booking-token",
        )
        db.add_all((booking_a, pending_a, booking_b, completed, completed_user))
        db.flush()

        review = ReviewRequest(
            business_id=business_a.id,
            booking_id=completed.id,
            customer_name=guest_a.name,
            customer_phone=guest_a.phone,
            reviews_url=business_a.reviews_url,
            message="Gracias por tu visita E2E. Comparte tu opinión.",
            status="pending",
        )
        db.add(review)
        db.flush()
        db.add(
            MessageOutbox(
                business_id=business_a.id,
                booking_id=completed.id,
                review_request_id=review.id,
                customer_name=guest_a.name,
                customer_phone=guest_a.phone,
                channel="whatsapp",
                message_type="booking_completed_review",
                message=review.message,
                whatsapp_url=(
                    "https://wa.me/34611000111?text=Gracias%20por%20tu%20visita%20E2E.%20"
                    "Comparte%20tu%20opini%C3%B3n."
                ),
                status="pending",
            )
        )

        _seed_instagram(db, business_a, owner, "SALON")
        _seed_instagram(db, business_b, owner, "FISIO")
        db.commit()
    finally:
        db.close()
        engine.dispose()


def session_cookie_for(email: str) -> str:
    engine = create_database_engine(database_url())
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        user = db.query(User).filter(User.email == email).one()
        _session, raw_token = create_auth_session(db, user_id=user.id)
        db.commit()
        return create_session_token(raw_token)
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    reset_database()
