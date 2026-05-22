CHANNEL_TELEGRAM = "telegram"

ACTIVE_CONVERSATION_STATUSES = (
    "active",
    "waiting_user",
    "checking_availability",
    "awaiting_confirmation",
    "booking_in_progress",
    "reserved",
    "payment_paid",
    "handoff",
)

SENDER_USER = "user"
SENDER_ASSISTANT = "assistant"
SENDER_SYSTEM = "system"
SENDER_ADMIN = "admin"

EMPTY_FORM_DATA: dict = {
    "date": None,
    "time": None,
    "duration": None,
    "phone": None,
    "client_name": None,
    "preferences": None,
    "event_format": None,
    "guests_count": None,
    "service_type": None,
    "service_variant": None,
    "upsell_items": [],
    "comment": None,
    "payment_status": "not_required_yet",
    "upsell_offer_count": 0,
    "reschedule_flow": None,
}
