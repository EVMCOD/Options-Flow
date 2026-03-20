-- PostgreSQL initialization script.
-- Alembic runs the full schema migration; this file is a no-op extension point.
-- Add custom roles, extensions, or RLS policies here if needed.

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
