from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.migration_state import alembic_config
from app.core.security import require_business_admin
from app.models import (
    AuditLog,
    Business,
    BusinessUser,
    Conversation,
    Customer,
    CustomerAccountLink,
    User,
)
from app.routers.conversations import admin_update_conversation_customer
from app.routers.customers import list_customers
from app.schemas.conversation import ConversationCustomerAssociationUpdate
from app.services.conversation_service import (
    auto_associate_conversation_customer,
    serialize_conversation,
)


@pytest.fixture
def records():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    business_a = Business(slug="identity-a", name="Identity A", status="active")
    business_b = Business(slug="identity-b", name="Identity B", status="active")
    admin = User(email="admin@identity.test")
    staff = User(email="staff@identity.test")
    db.add_all(
        [
            business_a,
            business_b,
            admin,
            staff,
            BusinessUser(business=business_a, user=admin, role="business_admin", active=True),
            BusinessUser(business=business_a, user=staff, role="business_staff", active=True),
        ]
    )
    db.commit()
    yield db, business_a, business_b, admin, staff
    db.close()
    engine.dispose()


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/api/admin/businesses/identity-a/conversations/1/customer",
            "headers": [],
            "client": ("testclient", 50000),
        }
    )


def add_customer(
    db: Session,
    business: Business,
    *,
    name: str,
    phone_normalized: str | None = None,
    phone: str | None = None,
) -> Customer:
    customer = Customer(
        business=business,
        name=name,
        phone=phone if phone is not None else phone_normalized,
        phone_normalized=phone_normalized,
    )
    db.add(customer)
    db.flush()
    return customer


def add_conversation(
    db: Session,
    business: Business,
    *,
    channel: str = "whatsapp",
    external_user_id: str = "34612345678",
    phone: str | None = "34612345678",
) -> Conversation:
    conversation = Conversation(
        business=business,
        channel=channel,
        external_user_id=external_user_id,
        external_conversation_id=external_user_id,
        customer_phone=phone,
        status="pending",
    )
    db.add(conversation)
    db.flush()
    return conversation


def test_whatsapp_unique_phone_associates_and_serializes_channel_identity(records) -> None:
    db, business, _, _, _ = records
    customer = add_customer(db, business, name="María", phone_normalized="+34612345678")
    conversation = add_conversation(db, business)

    matched = auto_associate_conversation_customer(
        db, business=business, conversation=conversation
    )
    result = serialize_conversation(db, conversation)

    assert matched.id == customer.id
    assert conversation.customer_id == customer.id
    assert result["customer_id"] == customer.id
    assert result["customer"]["name"] == "María"
    assert result["customer_memory_eligible"] is False
    assert result["association_status"] == "associated"
    assert result["channel_identity"] == {
        "display_name": None,
        "username": None,
        "phone": "34612345678",
        "phone_normalized": "+34612345678",
    }
    assert result["external_user_id"] == "34612345678"


@pytest.mark.parametrize("candidate_count", [0, 2])
def test_whatsapp_missing_or_ambiguous_phone_stays_unassociated(
    records, candidate_count: int
) -> None:
    db, business, _, _, _ = records
    for index in range(candidate_count):
        add_customer(
            db,
            business,
            name=f"Candidate {index}",
            phone_normalized="+34612345678",
            phone="+34612345678" if index == 0 else "612 345 678",
        )
    conversation = add_conversation(db, business)

    assert (
        auto_associate_conversation_customer(db, business=business, conversation=conversation)
        is None
    )
    assert conversation.customer_id is None


def test_manual_association_correction_detach_and_audit_are_stable(records) -> None:
    db, business, _, admin, _ = records
    phone_customer = add_customer(
        db, business, name="Phone match", phone_normalized="+34612345678"
    )
    selected = add_customer(db, business, name="Selected")
    replacement = add_customer(db, business, name="Replacement")
    conversation = add_conversation(db, business)

    first = admin_update_conversation_customer(
        business.slug,
        conversation.id,
        ConversationCustomerAssociationUpdate(customer_id=selected.id),
        request(),
        actor=admin,
        db=db,
    )["conversation"]
    assert first["customer_id"] == selected.id

    corrected = admin_update_conversation_customer(
        business.slug,
        conversation.id,
        ConversationCustomerAssociationUpdate(customer_id=replacement.id),
        request(),
        actor=admin,
        db=db,
    )["conversation"]
    assert corrected["customer_id"] == replacement.id
    auto_associate_conversation_customer(db, business=business, conversation=conversation)
    assert conversation.customer_id == replacement.id

    detached = admin_update_conversation_customer(
        business.slug,
        conversation.id,
        ConversationCustomerAssociationUpdate(customer_id=None),
        request(),
        actor=admin,
        db=db,
    )["conversation"]
    assert detached["customer_id"] is None
    auto_associate_conversation_customer(db, business=business, conversation=conversation)
    assert conversation.customer_id is None
    assert phone_customer.id != replacement.id

    audits = (
        db.query(AuditLog)
        .filter(AuditLog.action == "conversation_customer_association_changed")
        .order_by(AuditLog.id)
        .all()
    )
    assert len(audits) == 3
    metadata = json.loads(audits[-1].metadata_json)
    assert metadata == {
        "actor_user_id": admin.id,
        "conversation_id": conversation.id,
        "method": "manual",
        "new_customer_id": None,
        "previous_customer_id": replacement.id,
    }


def test_cross_business_customer_is_hidden_and_staff_cannot_mutate(records) -> None:
    db, business_a, business_b, admin, staff = records
    conversation = add_conversation(db, business_a)
    other_customer = add_customer(db, business_b, name="Other")

    with pytest.raises(HTTPException) as hidden:
        admin_update_conversation_customer(
            business_a.slug,
            conversation.id,
            ConversationCustomerAssociationUpdate(customer_id=other_customer.id),
            request(),
            actor=admin,
            db=db,
        )
    assert hidden.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        require_business_admin(business_a.slug, staff, db)
    assert denied.value.status_code == 403


def test_customer_search_is_scoped_and_reports_memory_eligibility(records) -> None:
    db, business_a, business_b, _, _ = records
    registered = add_customer(
        db, business_a, name="María Registered", phone_normalized="+34600111222"
    )
    guest = add_customer(db, business_a, name="Guest")
    foreign = add_customer(db, business_b, name="María Foreign")
    account = User(email="registered@identity.test")
    db.add(account)
    db.flush()
    db.add(
        CustomerAccountLink(
            user=account,
            customer=registered,
            business_id=business_a.id,
            link_method="test",
        )
    )
    db.commit()

    results = list_customers(
        business_a.slug, q="María", limit=20, offset=0, db=db
    )
    assert results == [
        {
            "id": registered.id,
            "customer_id": registered.id,
            "name": registered.name,
            "phone": registered.phone,
            "phone_normalized": registered.phone_normalized,
            "email": registered.email,
            "status": registered.status,
            "notes": registered.notes,
            "memory_eligible": True,
        }
    ]
    assert guest.id not in {item["customer_id"] for item in results}
    assert foreign.id not in {item["customer_id"] for item in results}


def test_instagram_requires_verified_provider_identity_and_account_link(records) -> None:
    db, business, _, _, _ = records
    customer = add_customer(db, business, name="Instagram customer")
    user = User(
        email="instagram@identity.test",
        instagram_provider_user_id="scoped-user",
        instagram_verified=True,
    )
    db.add(user)
    db.flush()
    db.add(
        CustomerAccountLink(
            user=user,
            customer=customer,
            business_id=business.id,
            link_method="verified_instagram",
        )
    )
    verified = add_conversation(
        db,
        business,
        channel="instagram",
        external_user_id="scoped-user",
        phone=None,
    )
    unknown = add_conversation(
        db,
        business,
        channel="instagram",
        external_user_id="other-scoped-user",
        phone=None,
    )

    assert auto_associate_conversation_customer(
        db, business=business, conversation=verified
    ).id == customer.id
    assert auto_associate_conversation_customer(
        db, business=business, conversation=unknown
    ) is None
    assert unknown.customer_id is None
    assert serialize_conversation(db, unknown)["channel_identity"]["username"] is None


def test_customer_instagram_is_a_visual_fallback_not_a_meta_sender_identity(records) -> None:
    db, business, _, _, _ = records
    customer = add_customer(db, business, name="Fallback customer")
    user = User(email="fallback@identity.test", instagram_username="customer.context")
    db.add(user)
    db.flush()
    db.add(
        CustomerAccountLink(
            user=user,
            customer=customer,
            business_id=business.id,
            link_method="profile_context",
        )
    )
    conversation = add_conversation(
        db,
        business,
        channel="instagram",
        external_user_id="meta-sender-without-username",
        phone=None,
    )
    conversation.customer = customer
    db.commit()

    fallback = serialize_conversation(db, conversation)
    assert fallback["channel_identity"]["username"] is None
    assert fallback["customer"]["instagram_username"] == "customer.context"
    assert fallback["integrated_delivery_available"] is False

    conversation.customer_username = "meta.sender"
    db.commit()
    meta = serialize_conversation(db, conversation)
    assert meta["channel_identity"]["username"] == "meta.sender"
    assert meta["customer"]["instagram_username"] == "customer.context"


def test_many_conversations_and_channels_can_share_one_customer(records) -> None:
    db, business, _, _, _ = records
    customer = add_customer(db, business, name="Shared")
    whatsapp = add_conversation(db, business, external_user_id="34600000001")
    instagram = add_conversation(
        db,
        business,
        channel="instagram",
        external_user_id="ig-shared",
        phone=None,
    )
    whatsapp.customer = customer
    instagram.customer = customer
    db.commit()

    assert {item.customer_id for item in customer.conversations} == {customer.id}
    assert {item.channel for item in customer.conversations} == {"whatsapp", "instagram"}


def test_customer_delete_sets_null_and_manual_history_prevents_reassociation(records) -> None:
    db, business, _, admin, _ = records
    customer = add_customer(
        db, business, name="Disposable", phone_normalized="+34612345678"
    )
    conversation = add_conversation(db, business)
    admin_update_conversation_customer(
        business.slug,
        conversation.id,
        ConversationCustomerAssociationUpdate(customer_id=customer.id),
        request(),
        actor=admin,
        db=db,
    )

    db.delete(customer)
    db.commit()
    db.refresh(conversation)

    assert conversation.customer_id is None
    assert serialize_conversation(db, conversation)["association_status"] == "unassociated"
    assert auto_associate_conversation_customer(
        db, business=business, conversation=conversation
    ) is None


def test_registered_customer_controls_memory_visibility(records) -> None:
    db, business, _, _, _ = records
    guest = add_customer(db, business, name="Guest")
    registered = add_customer(db, business, name="Registered")
    user = User(email="memory@identity.test")
    db.add(user)
    db.flush()
    db.add(
        CustomerAccountLink(
            user=user,
            customer=registered,
            business_id=business.id,
            link_method="test",
        )
    )
    guest_conversation = add_conversation(db, business, external_user_id="guest")
    registered_conversation = add_conversation(
        db, business, external_user_id="registered"
    )
    guest_conversation.customer = guest
    registered_conversation.customer = registered
    db.flush()

    assert serialize_conversation(db, guest_conversation)["customer_memory_eligible"] is False
    assert (
        serialize_conversation(db, registered_conversation)["customer_memory_eligible"]
        is True
    )


def test_conversation_customer_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'conversation-customer.db').as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.upgrade(config, "20260827_27")
    command.upgrade(config, "20260830_28")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    columns = {item["name"]: item for item in inspector.get_columns("conversations")}
    assert columns["customer_id"]["nullable"] is True
    assert "ix_conversations_customer_id" in {
        item["name"] for item in inspector.get_indexes("conversations")
    }
    foreign_keys = {
        item["name"]: item for item in inspector.get_foreign_keys("conversations")
    }
    customer_fk = foreign_keys["fk_conversations_customer_id_customers"]
    assert customer_fk["referred_table"] == "customers"
    assert customer_fk["options"]["ondelete"] == "SET NULL"
    engine.dispose()

    command.downgrade(config, "20260827_27")
    engine = create_engine(database_url)
    assert "customer_id" not in {
        item["name"] for item in inspect(engine).get_columns("conversations")
    }
    engine.dispose()
