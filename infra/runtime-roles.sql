-- EXPLICIT operator step; NOT a migration or startup hook. No credentials here.
-- Creates fresh NOLOGIN principals only. Existing names fail closed for review.
-- Run after migrations in ONE transaction from the private operator connection.
BEGIN;
CREATE ROLE pocket_api_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE pocket_research_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
-- Prevent runtime users creating shadow objects in the shared application schema.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
DO $$ BEGIN
    EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
END $$;
GRANT USAGE ON SCHEMA public TO pocket_api_runtime,pocket_research_runtime;
GRANT SELECT ON public.schema_migration TO pocket_api_runtime,pocket_research_runtime;
GRANT SELECT,INSERT ON public.owner_account,public.owner_session TO pocket_api_runtime;
GRANT UPDATE (display_email) ON public.owner_account TO pocket_api_runtime;
GRANT UPDATE (revoked_at) ON public.owner_session TO pocket_api_runtime;
GRANT SELECT,INSERT,UPDATE ON public.login_rate TO pocket_api_runtime;
GRANT SELECT,INSERT,DELETE ON public.login_challenge TO pocket_api_runtime;
GRANT SELECT,INSERT,UPDATE ON public.research_job,public.research_refresh TO pocket_api_runtime;
GRANT SELECT,INSERT ON public.research_campaign,public.research_campaign_day TO pocket_api_runtime;
GRANT SELECT ON public.research_campaign_work,public.research_campaign_result,
    public.research_dataset,public.research_summary,public.research_result,
    public.research_result_dataset TO pocket_api_runtime;
GRANT SELECT,INSERT,UPDATE ON public.research_job,public.research_read_budget,
    public.research_campaign_day,public.research_refresh TO pocket_research_runtime;
GRANT SELECT,INSERT ON public.raw_archive,public.collection_page,
    public.research_artifact,public.research_dataset,public.research_summary,
    public.research_dataset_artifact,public.research_result,public.research_result_dataset,
    public.research_observation,public.research_campaign,public.research_campaign_work,
    public.research_campaign_result TO pocket_research_runtime;
GRANT USAGE ON SEQUENCE public.research_dataset_id_seq,public.research_result_id_seq TO pocket_research_runtime;
-- No ownership, memberships, ALTER, TRUNCATE, DELETE of history, or future-table defaults.
-- Separate LOGIN credentials and isolated runtime DATABASE_URLs remain owner steps.
COMMIT;
