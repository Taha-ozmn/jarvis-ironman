-- Phase 4: automation runtime state
ALTER TABLE automations ADD COLUMN last_fired_at TEXT;
ALTER TABLE automations ADD COLUMN fail_count INTEGER NOT NULL DEFAULT 0;
