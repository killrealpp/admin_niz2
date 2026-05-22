from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import get_connection


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    b.id,
                    b.status,
                    b.payment_status,
                    b.service_type,
                    b.booking_date,
                    b.booking_time,
                    b.duration_minutes,
                    b.client_name,
                    b.phone,
                    b.guests_count,
                    b.event_format,
                    b.upsell_items,
                    b.created_at
                FROM bookings b
                ORDER BY b.id DESC
                LIMIT 20
                """
            )
            rows = cur.fetchall()

    if not rows:
        print("Заявок пока нет.")
        return

    for row in rows:
        duration = row["duration_minutes"]
        duration_text = f"{duration // 60} ч" if duration and duration % 60 == 0 else f"{duration} мин"
        extras = ", ".join(row["upsell_items"] or []) or "не указаны"
        print("---")
        print(f"Заявка #{row['id']} | {row['status']} | оплата: {row['payment_status']}")
        print(f"Услуга: {row['service_type']}")
        print(f"Дата/время: {row['booking_date']} {str(row['booking_time'])[:5]} на {duration_text}")
        print(f"Клиент: {row['client_name']} | {row['phone']}")
        print(f"Гости: {row['guests_count']} | формат: {row['event_format']}")
        print(f"Допы: {extras}")
        print(f"Создана: {row['created_at']}")


if __name__ == "__main__":
    main()
