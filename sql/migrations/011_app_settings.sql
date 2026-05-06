CREATE TABLE IF NOT EXISTS config.app_settings (
  setting_key TEXT PRIMARY KEY,
  setting_value JSONB NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
