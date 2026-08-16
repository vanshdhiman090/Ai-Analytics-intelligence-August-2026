-- P0A: anonymous guest ownership for externally created datasets.
-- Existing rows remain NULL. They are not accessible as guest-owned datasets;
-- maintained recruiter-demo fixtures are intentionally NULL and are resolved
-- only while recruiter demo mode is enabled.
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS guest_owner_id UUID;
CREATE INDEX IF NOT EXISTS idx_datasets_guest_owner ON datasets(guest_owner_id);
