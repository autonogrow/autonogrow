from typing import Any


def build_admin_booking_message(booking: dict[str, Any]) -> str:
    return f"""📩 Nueva solicitud de cita

Cliente: {booking.get("customer_name")}
Teléfono: {booking.get("customer_phone") or "No indicado"}
Servicio: {booking.get("service_name")}
Día: {booking.get("preferred_day_label") or booking.get("preferred_date")}
Hora: {booking.get("preferred_time")}

Estado: {booking.get("status")}
"""
