-- PostgreSQL schema (Beget managed DB, port 5432)

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    channel VARCHAR(32) NOT NULL,
    external_id VARCHAR(128) NOT NULL,
    name VARCHAR(255),
    phone VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uniq_channel_external_id UNIQUE (channel, external_id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    channel VARCHAR(32) NOT NULL,
    intent VARCHAR(64),
    current_step VARCHAR(64),
    next_step VARCHAR(64),
    status VARCHAR(64) NOT NULL DEFAULT 'active',
    form_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_message_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_status_time
    ON conversations (user_id, status, last_message_time DESC);

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id),
    sender VARCHAR(32) NOT NULL,
    text TEXT NOT NULL,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
    ON messages (conversation_id, created_at ASC);

CREATE TABLE IF NOT EXISTS conversation_summaries (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    messages_from TIMESTAMPTZ NOT NULL,
    messages_to TIMESTAMPTZ NOT NULL,
    messages_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_summaries_conversation_created
    ON conversation_summaries (conversation_id, created_at ASC);

CREATE TABLE IF NOT EXISTS slot_holds (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id),
    user_id BIGINT NOT NULL REFERENCES users(id),
    service_type VARCHAR(64) NOT NULL,
    yclients_service_id VARCHAR(64),
    slot_date DATE NOT NULL,
    slot_time TIME NOT NULL,
    duration_minutes INT,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    expires_at TIMESTAMPTZ NOT NULL,
    expired_notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE slot_holds
    ADD COLUMN IF NOT EXISTS expired_notified_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_slot_holds_lookup
    ON slot_holds (service_type, slot_date, slot_time, status, expires_at);

CREATE INDEX IF NOT EXISTS idx_slot_holds_expired_notifications
    ON slot_holds (status, expired_notified_at, expires_at);

CREATE TABLE IF NOT EXISTS bookings (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id),
    user_id BIGINT NOT NULL REFERENCES users(id),
    slot_hold_id BIGINT REFERENCES slot_holds(id),
    yclients_record_id VARCHAR(128),
    service_type VARCHAR(64) NOT NULL,
    booking_date DATE NOT NULL,
    booking_time TIME NOT NULL,
    duration_minutes INT,
    client_name VARCHAR(255) NOT NULL,
    phone VARCHAR(32) NOT NULL,
    guests_count INT,
    event_format VARCHAR(128),
    preferences TEXT,
    upsell_items JSONB,
    status VARCHAR(64) NOT NULL DEFAULT 'created',
    payment_status VARCHAR(64) NOT NULL DEFAULT 'not_paid',
    admin_notified_at TIMESTAMPTZ,
    yclients_created_at TIMESTAMPTZ,
    yclients_create_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE bookings
    ADD COLUMN IF NOT EXISTS admin_notified_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS yclients_created_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS yclients_create_error TEXT;

CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id),
    user_id BIGINT NOT NULL REFERENCES users(id),
    booking_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider VARCHAR(64) NOT NULL,
    provider_payment_id VARCHAR(128),
    amount NUMERIC(12, 2) NOT NULL,
    currency VARCHAR(8) NOT NULL DEFAULT 'RUB',
    payment_url TEXT,
    status VARCHAR(64) NOT NULL DEFAULT 'pending',
    description TEXT,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at TIMESTAMPTZ,
    payment_notified_at TIMESTAMPTZ
);

ALTER TABLE payments
    ADD COLUMN IF NOT EXISTS payment_notified_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_payments_conversation_status
    ON payments (conversation_id, status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_payment_id
    ON payments (provider, provider_payment_id)
    WHERE provider_payment_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS yclients_sync_state (
    sync_name VARCHAR(64) PRIMARY KEY,
    last_started_at TIMESTAMPTZ,
    last_finished_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    records_seen INT NOT NULL DEFAULT 0,
    records_upserted INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS yclients_records (
    id BIGSERIAL PRIMARY KEY,
    yclients_record_id VARCHAR(128) NOT NULL UNIQUE,
    company_id VARCHAR(64),
    service_type VARCHAR(64),
    yclients_service_id VARCHAR(64),
    yclients_staff_id VARCHAR(64),
    service_title TEXT,
    staff_title TEXT,
    client_name VARCHAR(255),
    client_phone VARCHAR(64),
    status VARCHAR(64),
    attendance INT,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    duration_minutes INT,
    raw_payload JSONB NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_yclients_records_period
    ON yclients_records (start_at, end_at);

CREATE INDEX IF NOT EXISTS idx_yclients_records_lookup
    ON yclients_records (service_type, yclients_staff_id, status, start_at);

CREATE TABLE IF NOT EXISTS resource_busy_intervals (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(32) NOT NULL,
    source_record_id VARCHAR(128) NOT NULL,
    service_type VARCHAR(64) NOT NULL,
    yclients_service_id VARCHAR(64),
    yclients_staff_id VARCHAR(64) NOT NULL,
    title TEXT,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'active',
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uniq_busy_interval_source UNIQUE (source, source_record_id, yclients_service_id, yclients_staff_id)
);

CREATE INDEX IF NOT EXISTS idx_busy_intervals_lookup
    ON resource_busy_intervals (service_type, yclients_staff_id, status, start_at, end_at);

CREATE INDEX IF NOT EXISTS idx_busy_intervals_source_record
    ON resource_busy_intervals (source, source_record_id);

CREATE TABLE IF NOT EXISTS system_logs (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT REFERENCES conversations(id),
    level VARCHAR(32) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    message TEXT,
    payload JSONB,
    admin_notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE system_logs
    ADD COLUMN IF NOT EXISTS admin_notified_at TIMESTAMPTZ;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS handoff_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS handoff_reason TEXT,
    ADD COLUMN IF NOT EXISTS handoff_summary TEXT,
    ADD COLUMN IF NOT EXISTS handoff_notified_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS waitlist_requests (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id),
    user_id BIGINT NOT NULL REFERENCES users(id),
    service_type VARCHAR(64) NOT NULL,
    service_variant VARCHAR(255),
    desired_date DATE NOT NULL,
    desired_time TIME,
    duration_minutes INT,
    guests_count INT,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_checked_at TIMESTAMPTZ,
    notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_waitlist_unique_active
    ON waitlist_requests (user_id, service_type, desired_date, COALESCE(desired_time, TIME '00:00'))
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_waitlist_active_lookup
    ON waitlist_requests (status, desired_date, service_type, last_checked_at);

CREATE TABLE IF NOT EXISTS webhook_events (
    id BIGSERIAL PRIMARY KEY,
    provider VARCHAR(64) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    provider_object_id VARCHAR(128),
    payload JSONB NOT NULL,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_webhook_events_provider_object_event
    ON webhook_events (provider, event_type, provider_object_id)
    WHERE provider_object_id IS NOT NULL;
