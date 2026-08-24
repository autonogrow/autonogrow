from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Business,
    BusinessGalleryImage,
    BusinessGrowthSignal,
    BusinessReview,
    BusinessService,
    InstagramRawAsset,
    SocialContentProposal,
    SocialContentProposalSignal,
)
from app.services.capability_service import module_is_available

# Centralized, explainable V1 product policy.
MAX_ACTIVE_PROPOSALS_PER_BUSINESS = 8
MAX_ACTIVE_PROPOSALS_PER_SERVICE = 2
REVIEW_FRESHNESS_DAYS = 90
URGENCY_HORIZON_DAYS = 14
SEASONAL_HORIZON_DAYS = 30
EVERGREEN_WINDOW_DAYS = 14
MIN_AGGREGATED_CUSTOMER_COUNT = 4
MIN_POSITIVE_REVIEW_RATING = 4.0
MAX_EVIDENCE_JSON_CHARS = 4000
MAX_ACCEPTED_CONTEXT_JSON_CHARS = 8000

SAFE_SIGNAL_FIELDS = {
    "low_future_occupancy": {
        "occupancy_rate",
        "booking_count",
        "capacity_minutes",
        "available_minutes",
        "staff_count",
        "period_days",
    },
    "high_due_customer_pool": {"customers_due", "window_days"},
    "low_return_rate": {"return_rate", "sample_size", "returned", "period_days"},
    "service_demand_drop": {"booking_count", "period_days", "capacity_ratio"},
    "seasonal_window": {"days_until_start", "event_title", "event_category"},
}
SAFE_BASELINE_FIELDS = {
    "low_future_occupancy": {"occupancy_rate", "booking_count", "weeks_used"},
    "high_due_customer_pool": {"minimum_customers"},
    "low_return_rate": {"return_rate", "sample_size", "returned", "periods_used", "drop_points"},
    "service_demand_drop": {
        "average_booking_count",
        "period_counts",
        "periods_used",
        "relative_ratio",
    },
    "seasonal_window": set(),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _read_object(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _json(value: Any, *, max_chars: int = MAX_EVIDENCE_JSON_CHARS) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > max_chars:
        raise ValueError("social_content_evidence_too_large")
    return encoded


def _safe_signal_snapshot(signal: BusinessGrowthSignal) -> dict[str, Any]:
    observed = _read_object(signal.observed_json)
    baseline = _read_object(signal.baseline_json)
    return {
        "signal_id": signal.id,
        "type": signal.type,
        "severity": signal.severity,
        "service_id": signal.service_id,
        "observed": {
            key: observed[key]
            for key in SAFE_SIGNAL_FIELDS.get(signal.type, set())
            if key in observed
        },
        "baseline": {
            key: baseline[key]
            for key in SAFE_BASELINE_FIELDS.get(signal.type, set())
            if key in baseline
        },
    }


def _percent(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return f"{round(float(value) * 100)}%"


@dataclass(frozen=True)
class ProposalCandidate:
    dedupe_key: str
    objective: str
    proposal_type: str
    score: int
    service_id: int | None
    reason_code: str
    reason_text: str
    formats: tuple[str, ...]
    cta: str
    angle: str
    target_start: datetime
    target_end: datetime
    expires_at: datetime
    signal_ids: tuple[int, ...] = ()
    source_event_id: int | None = None
    source_review_id: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def priority(self) -> str:
        if self.score >= 70:
            return "high"
        if self.score >= 35:
            return "normal"
        return "low"


@dataclass
class SocialContentEvaluationResult:
    created: int = 0
    updated: int = 0
    resolved: int = 0
    expired: int = 0
    suppressed: int = 0


class SocialContentIntelligenceService:
    def __init__(self, db: Session, *, now: datetime | None = None):
        self.db = db
        self.now = _aware(now or utc_now())
        self.result = SocialContentEvaluationResult()

    def evaluate_business(self, business_id: int) -> SocialContentEvaluationResult:
        business = self.db.get(Business, business_id)
        if business is None:
            raise ValueError("business_not_found")
        if not module_is_available(self.db, business_id, "social"):
            return self.result
        self._expire(business_id)
        signals = (
            self.db.query(BusinessGrowthSignal)
            .filter(
                BusinessGrowthSignal.business_id == business_id,
                BusinessGrowthSignal.status == "active",
            )
            .order_by(BusinessGrowthSignal.id.asc())
            .all()
        )
        services = {
            row.id: row
            for row in self.db.query(BusinessService)
            .filter(
                BusinessService.business_id == business_id,
                BusinessService.active.is_(True),
                BusinessService.archived_at.is_(None),
            )
            .order_by(BusinessService.position.asc(), BusinessService.id.asc())
            .all()
        }
        asset_count = self._asset_count(business_id)
        candidates = self._signal_candidates(signals, services)
        candidates.extend(self._review_candidates(business_id))
        if not any(item.score >= 35 for item in candidates):
            candidates.append(self._evergreen_candidate(services))
        touched: set[str] = set()
        per_service: dict[int, int] = {}
        for candidate in sorted(candidates, key=lambda item: (-item.score, item.dedupe_key)):
            if len(touched) >= MAX_ACTIVE_PROPOSALS_PER_BUSINESS:
                self.result.suppressed += 1
                continue
            if candidate.service_id is not None:
                count = per_service.get(candidate.service_id, 0)
                if count >= MAX_ACTIVE_PROPOSALS_PER_SERVICE:
                    self.result.suppressed += 1
                    continue
                per_service[candidate.service_id] = count + 1
            touched.add(candidate.dedupe_key)
            self._upsert(business_id, candidate, asset_count)
        self._resolve_untouched(business_id, touched)
        return self.result

    def _signal_candidates(
        self,
        signals: list[BusinessGrowthSignal],
        services: dict[int, BusinessService],
    ) -> list[ProposalCandidate]:
        occupancy = [row for row in signals if row.type == "low_future_occupancy"]
        due_service = [
            row
            for row in signals
            if row.type == "high_due_customer_pool"
            and row.service_id in services
            and self._due_count(row) >= MIN_AGGREGATED_CUSTOMER_COUNT
        ]
        consumed: set[int] = set()
        result: list[ProposalCandidate] = []
        if occupancy:
            primary_occupancy = occupancy[0]
            for due in due_service:
                assert due.service_id is not None
                result.append(
                    self._combined_candidate(
                        primary_occupancy, due, services[due.service_id]
                    )
                )
                consumed.update((primary_occupancy.id, due.id))
        for signal in signals:
            if signal.id in consumed:
                continue
            if (
                signal.type == "high_due_customer_pool"
                and signal.service_id is None
                and due_service
            ):
                continue
            if signal.service_id is not None and signal.service_id not in services:
                continue
            service = services.get(signal.service_id) if signal.service_id is not None else None
            candidate = self._candidate_for_signal(signal, service)
            if candidate is not None:
                result.append(candidate)
        return result

    @staticmethod
    def _due_count(signal: BusinessGrowthSignal) -> int:
        value = _read_object(signal.observed_json).get("customers_due", 0)
        return int(value) if isinstance(value, (int, float)) else 0

    def _combined_candidate(
        self,
        occupancy: BusinessGrowthSignal,
        due: BusinessGrowthSignal,
        service: BusinessService,
    ) -> ProposalCandidate:
        evidence: dict[str, Any] = {
            "schema_version": 1,
            "signals": [_safe_signal_snapshot(occupancy), _safe_signal_snapshot(due)],
            "composition": "low_occupancy_and_service_due",
        }
        occupancy_snapshot = evidence["signals"][0]
        due_snapshot = evidence["signals"][1]
        occupancy_rate = _percent(occupancy_snapshot["observed"].get("occupancy_rate"))
        baseline_rate = _percent(occupancy_snapshot["baseline"].get("occupancy_rate"))
        due_count = due_snapshot["observed"].get("customers_due")
        occupancy_text = (
            f"La próxima ventana tiene {occupancy_rate} de ocupación"
            + (f" frente a {baseline_rate} de referencia" if baseline_rate else "")
            if occupancy_rate
            else "La próxima ventana tiene baja ocupación"
        )
        due_text = (
            f" y un grupo agregado de {due_count} clientes está en periodo de retorno"
            if isinstance(due_count, (int, float))
            else " y existe un grupo agregado en periodo de retorno"
        )
        return ProposalCandidate(
            dedupe_key=f"combined:{occupancy.dedupe_key}:{due.dedupe_key}",
            objective="fill_capacity",
            proposal_type="availability_push",
            score=100,
            service_id=service.id,
            reason_code="low_occupancy_with_service_due_pool",
            reason_text=(
                f"{occupancy_text}{due_text} para {service.name}. Puede ser buen momento para darle visibilidad, "
                "sin aplicar descuentos automáticamente."
            ),
            formats=("story", "reel"),
            cta="book_now",
            angle="limited_window",
            target_start=self.now,
            target_end=max(_aware(occupancy.period_end), self.now + timedelta(hours=1)),
            expires_at=max(_aware(occupancy.period_end), self.now + timedelta(hours=1)),
            signal_ids=(occupancy.id, due.id),
            evidence=evidence,
        )

    def _candidate_for_signal(
        self, signal: BusinessGrowthSignal, service: BusinessService | None
    ) -> ProposalCandidate | None:
        evidence: dict[str, Any] = {
            "schema_version": 1,
            "signals": [_safe_signal_snapshot(signal)],
        }
        end = max(_aware(signal.period_end), self.now + timedelta(hours=1))
        expires = min(_aware(signal.expires_at), end) if signal.expires_at else end
        expires = max(expires, self.now + timedelta(hours=1))
        service_name = service.name if service else "el negocio"
        severity_bonus = {"high": 8, "medium": 4, "low": 0, "info": 0}.get(
            signal.severity, 0
        )
        snapshot = evidence["signals"][0]
        observed = snapshot["observed"]
        baseline = snapshot["baseline"]
        if signal.type == "low_future_occupancy":
            occupancy_rate = _percent(observed.get("occupancy_rate"))
            baseline_rate = _percent(baseline.get("occupancy_rate"))
            comparison = (
                f" ({occupancy_rate} frente a {baseline_rate} de referencia)"
                if occupancy_rate and baseline_rate
                else f" ({occupancy_rate})" if occupancy_rate else ""
            )
            return ProposalCandidate(
                f"availability:{signal.dedupe_key}", "fill_capacity", "availability_push",
                90 + severity_bonus, signal.service_id, "low_future_occupancy",
                f"La próxima ventana tiene baja ocupación{comparison}. Conviene comunicar disponibilidad.",
                ("story", "reel", "static_post"), "book_now", "availability", self.now,
                end, expires, (signal.id,), evidence=evidence,
            )
        if signal.type in {"high_due_customer_pool", "low_return_rate"}:
            if (
                signal.type == "high_due_customer_pool"
                and self._due_count(signal) < MIN_AGGREGATED_CUSTOMER_COUNT
            ):
                return None
            due_count = observed.get("customers_due")
            aggregate = (
                f"un grupo agregado de {due_count} clientes"
                if isinstance(due_count, (int, float))
                else "una oportunidad agregada"
            )
            return ProposalCandidate(
                f"return:{signal.dedupe_key}", "reactivate_customers", "return_activation",
                70 + severity_bonus, signal.service_id, signal.reason_code,
                f"Existe {aggregate} en periodo de retorno para {service_name}. Puede recordarse públicamente el servicio sin dirigirse a clientes concretos.",
                ("story", "carousel"), "discover_service", "benefit", self.now, end,
                expires, (signal.id,), evidence=evidence,
            )
        if signal.type == "service_demand_drop" and service is not None:
            current_count = observed.get("booking_count")
            baseline_count = baseline.get("average_booking_count")
            comparison = (
                f": {current_count} reservas frente a {baseline_count} de referencia"
                if isinstance(current_count, (int, float))
                and isinstance(baseline_count, (int, float))
                else ""
            )
            return ProposalCandidate(
                f"demand:{signal.dedupe_key}", "promote_service", "service_push",
                60 + severity_bonus, service.id, signal.reason_code,
                f"{service.name} está recibiendo menos reservas que su patrón observable{comparison}. Puede explicarse el servicio con un ángulo conceptual y verificable.",
                ("reel", "carousel"), "discover_service", "process", self.now, end,
                expires, (signal.id,), evidence=evidence,
            )
        if signal.type == "seasonal_window":
            days_until = int(observed.get("days_until_start", SEASONAL_HORIZON_DAYS))
            score = 75 if days_until <= URGENCY_HORIZON_DAYS else 65
            event_title = observed.get("event_title")
            event_text = f" “{event_title}”" if isinstance(event_title, str) else ""
            return ProposalCandidate(
                f"seasonal:{signal.dedupe_key}", "seasonal_activation", "seasonal_content",
                score, signal.service_id, signal.reason_code,
                f"Se acerca el evento comercial{event_text} en {days_until} días para {service_name}. Conviene preparar una comunicación estacional.",
                ("story", "reel", "static_post"), "check_availability", "seasonal",
                self.now, end, expires, (signal.id,), signal.calendar_event_id,
                evidence=evidence,
            )
        return None

    def _review_candidates(self, business_id: int) -> list[ProposalCandidate]:
        cutoff = self.now - timedelta(days=REVIEW_FRESHNESS_DAYS)
        reviews = (
            self.db.query(BusinessReview)
            .filter(
                BusinessReview.business_id == business_id,
                BusinessReview.status == "usable",
                BusinessReview.social_use_approved.is_(True),
                BusinessReview.rating >= MIN_POSITIVE_REVIEW_RATING,
                BusinessReview.reviewed_at >= cutoff,
                func.length(func.trim(BusinessReview.review_text)) > 0,
            )
            .order_by(BusinessReview.reviewed_at.desc(), BusinessReview.id.desc())
            .limit(1)
            .all()
        )
        return [
            ProposalCandidate(
                dedupe_key=f"review:{row.id}",
                objective="social_proof",
                proposal_type="review_social_proof",
                score=40,
                service_id=row.service_id,
                reason_code="recent_positive_approved_review",
                reason_text="Hay una reseña positiva reciente autorizada para uso social. Puede convertirse en prueba social anonimizada.",
                formats=("static_post", "story"),
                cta="none",
                angle="testimonial",
                target_start=self.now,
                target_end=self.now + timedelta(days=EVERGREEN_WINDOW_DAYS),
                expires_at=self.now + timedelta(days=EVERGREEN_WINDOW_DAYS),
                source_review_id=row.id,
                evidence={
                    "schema_version": 1,
                    "review": {
                        "review_id": row.id,
                        "rating": row.rating,
                        "reviewed_at": _aware(row.reviewed_at).isoformat(),
                        "social_use_approved": True,
                    },
                },
            )
            for row in reviews
        ]

    def _evergreen_candidate(
        self, services: dict[int, BusinessService]
    ) -> ProposalCandidate:
        service = next(iter(services.values()), None)
        iso = self.now.date().isocalendar()
        bucket = f"{iso.year}-W{iso.week:02d}"
        subject = service.name if service else "el negocio"
        return ProposalCandidate(
            dedupe_key=f"evergreen:{service.id if service else 'business'}:{bucket}",
            objective="educate",
            proposal_type="evergreen_content",
            score=10,
            service_id=service.id if service else None,
            reason_code="no_urgent_commercial_content",
            reason_text=f"No hay una necesidad comercial urgente. Puede explicarse una pregunta frecuente sobre {subject}.",
            formats=("carousel", "story"),
            cta="learn_more",
            angle="faq",
            target_start=self.now,
            target_end=self.now + timedelta(days=EVERGREEN_WINDOW_DAYS),
            expires_at=self.now + timedelta(days=EVERGREEN_WINDOW_DAYS),
            evidence={"schema_version": 1, "fallback": "weekly_evergreen"},
        )

    def _asset_count(self, business_id: int) -> int:
        gallery = (
            self.db.query(BusinessGalleryImage)
            .filter(
                BusinessGalleryImage.business_id == business_id,
                BusinessGalleryImage.active.is_(True),
            )
            .count()
        )
        raw = (
            self.db.query(InstagramRawAsset)
            .filter(
                InstagramRawAsset.business_id == business_id,
                InstagramRawAsset.source_kind == "business_upload",
            )
            .count()
        )
        return gallery + raw

    def _upsert(
        self, business_id: int, candidate: ProposalCandidate, asset_count: int
    ) -> None:
        row = (
            self.db.query(SocialContentProposal)
            .filter(
                SocialContentProposal.business_id == business_id,
                SocialContentProposal.dedupe_key == candidate.dedupe_key,
            )
            .first()
        )
        if row is not None and row.status != "active":
            self.result.suppressed += 1
            return
        values = {
            "objective": candidate.objective,
            "proposal_type": candidate.proposal_type,
            "priority": candidate.priority,
            "priority_score": candidate.score,
            "service_id": candidate.service_id,
            "source_event_id": candidate.source_event_id,
            "source_review_id": candidate.source_review_id,
            "reason_code": candidate.reason_code,
            "reason_text": candidate.reason_text[:500],
            "evidence_json": _json(candidate.evidence),
            "recommended_formats_json": _json(list(candidate.formats)),
            "recommended_cta": candidate.cta,
            "angle_code": candidate.angle,
            "available_asset_count": asset_count,
            "asset_requirement": "existing_media" if asset_count else (
                "review" if candidate.proposal_type == "review_social_proof" else "new_photo"
            ),
            "target_window_start": candidate.target_start,
            "target_window_end": candidate.target_end,
            "expires_at": candidate.expires_at,
            "updated_at": self.now,
        }
        if row is None:
            row = SocialContentProposal(
                business_id=business_id,
                status="active",
                detected_at=self.now,
                dedupe_key=candidate.dedupe_key,
                created_at=self.now,
                **values,
            )
            self.db.add(row)
            self.db.flush()
            self.result.created += 1
            row.signal_links.extend(
                SocialContentProposalSignal(signal_id=signal_id)
                for signal_id in candidate.signal_ids
            )
        else:
            for key, value in values.items():
                setattr(row, key, value)
            self.result.updated += 1
            existing_signal_ids = tuple(sorted(link.signal_id for link in row.signal_links))
            wanted_signal_ids = tuple(sorted(candidate.signal_ids))
            if existing_signal_ids != wanted_signal_ids:
                row.signal_links.clear()
                self.db.flush()
                row.signal_links.extend(
                    SocialContentProposalSignal(signal_id=signal_id)
                    for signal_id in candidate.signal_ids
                )
        self.db.flush()

    def _expire(self, business_id: int) -> None:
        rows = (
            self.db.query(SocialContentProposal)
            .filter(
                SocialContentProposal.business_id == business_id,
                SocialContentProposal.status == "active",
                SocialContentProposal.expires_at <= self.now,
            )
            .all()
        )
        for row in rows:
            row.status = "expired"
            row.updated_at = self.now
            self.result.expired += 1

    def _resolve_untouched(self, business_id: int, touched: set[str]) -> None:
        rows = (
            self.db.query(SocialContentProposal)
            .filter(
                SocialContentProposal.business_id == business_id,
                SocialContentProposal.status == "active",
            )
            .all()
        )
        for row in rows:
            if row.dedupe_key not in touched:
                row.status = "resolved"
                row.resolved_at = self.now
                row.updated_at = self.now
                self.result.resolved += 1


def serialize_social_content_proposal(row: SocialContentProposal) -> dict[str, Any]:
    formats = json.loads(row.recommended_formats_json)
    evidence = _read_object(row.evidence_json)
    accepted_context = _read_object(row.accepted_context_json) if row.accepted_context_json else None
    return {
        "id": row.id,
        "business_id": row.business_id,
        "status": row.status,
        "objective": row.objective,
        "type": row.proposal_type,
        "priority": row.priority,
        "priority_score": row.priority_score,
        "service": {"id": row.service.id, "name": row.service.name} if row.service else None,
        "source_signal_ids": [link.signal_id for link in row.signal_links],
        "source_event_id": row.source_event_id,
        "source_review_id": row.source_review_id,
        "reason_code": row.reason_code,
        "reason_text": row.reason_text,
        "evidence": evidence,
        "recommended_formats": formats,
        "recommended_cta": row.recommended_cta,
        "angle_code": row.angle_code,
        "available_assets": {
            "available": row.available_asset_count > 0,
            "count": row.available_asset_count,
            "scope": "business",
        },
        "asset_requirement": row.asset_requirement,
        "target_window_start": row.target_window_start.isoformat(),
        "target_window_end": row.target_window_end.isoformat(),
        "detected_at": row.detected_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "dismissed_at": row.dismissed_at.isoformat() if row.dismissed_at else None,
        "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
        "accepted_by_user_id": row.accepted_by_user_id,
        "accepted_context": accepted_context,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "generated_content": (
            {
                "id": row.generated_content.id,
                "title": row.generated_content.title,
                "status": row.generated_content.status,
            }
            if row.generated_content
            else None
        ),
    }


def acceptance_snapshot(row: SocialContentProposal) -> str:
    return _json(
        {
            "schema_version": 1,
            "proposal_id": row.id,
            "objective": row.objective,
            "type": row.proposal_type,
            "service": (
                {"id": row.service.id, "name": row.service.name} if row.service else None
            ),
            "reason_code": row.reason_code,
            "reason_text": row.reason_text,
            "evidence": _read_object(row.evidence_json),
            "recommended_formats": json.loads(row.recommended_formats_json),
            "recommended_cta": row.recommended_cta,
            "angle_code": row.angle_code,
            "available_asset_count": row.available_asset_count,
            "asset_requirement": row.asset_requirement,
            "target_window_start": row.target_window_start.isoformat(),
            "target_window_end": row.target_window_end.isoformat(),
        },
        max_chars=MAX_ACCEPTED_CONTEXT_JSON_CHARS,
    )
