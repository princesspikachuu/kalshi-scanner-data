-- MT-019: separate, NOLOGIN, non-owner diagnostic archival authority.
-- OPERATOR-ONLY. Never run as a migration, predeploy hook or active worker.
-- Requires an isolated private owner connection to pocket_staging, and must
-- be applied once by an operator after full verified backup.
-- No credentials or passwords are included. No financial table DELETE grants.
BEGIN;
DO $guard$ BEGIN
    IF current_database() NOT IN ('pocket_staging','pocket_test') THEN
        RAISE EXCEPTION 'Only staging or disposable test database is permitted';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public'
                   AND tablename='research_job' AND tableowner=current_user) THEN
        RAISE EXCEPTION 'Only the research_job owner may install archival fencing';
    END IF;
END $guard$;
CREATE ROLE pocket_archive_maintenance NOLOGIN NOSUPERUSER NOCREATEDB
    NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO pocket_archive_maintenance;
GRANT SELECT ON public.research_job TO pocket_archive_maintenance;
-- No INSERT privileges: the constrained function also creates the manifest.
-- No UPDATE/DELETE/TRUNCATE/OWNERSHIP/MEMBERSHIPS or schema CREATE rights.

CREATE FUNCTION public.mt_reclaim_shadow_diagnostics(
    p_manifest_id uuid, p_kind text, p_manifest jsonb, p_original_rows jsonb
) RETURNS TABLE(id text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public
AS $function$
DECLARE
    v_manifest public.research_job%ROWTYPE;
    v_row public.research_job%ROWTYPE;
    v_record jsonb;
    v_kind text;
    v_prefix text;
    v_expected_field text;
    v_expected_format text;
    v_index integer := 0;
    v_count integer;
    v_deleted integer;
    v_row_id uuid;
    v_manifest_key text;
    v_ids uuid[] := ARRAY[]::uuid[];
BEGIN
    -- SECURITY DEFINER changes current_user; session_user remains login.
    IF session_user <> 'pocket_archive_maintenance' THEN
        RAISE EXCEPTION 'Only the isolated archival login may reclaim diagnostics';
    END IF;
    IF current_database() NOT IN ('pocket_staging','pocket_test') THEN
        RAISE EXCEPTION 'Archive reclamation is restricted to staging';
    END IF;
    IF jsonb_typeof(p_original_rows) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Source snapshot must be a bounded JSON array';
    END IF;
    v_count := jsonb_array_length(p_original_rows);
    IF v_count < 1 OR v_count > 100 THEN
        RAISE EXCEPTION 'Archive snapshot size outside bounded limits';
    END IF;

    IF p_kind NOT IN ('shadow_event_r2_manifest',
                      'diagnostic_batch_r2_manifest') THEN
        RAISE EXCEPTION 'Only nonfinancial diagnostic archive manifests allowed';
    END IF;
    IF jsonb_typeof(p_manifest) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Archive manifest must be a JSON object';
    END IF;
    v_manifest_key:=CASE
        WHEN p_kind='shadow_event_r2_manifest'
        THEN 'demo/shadow/archive-manifest/'||p_manifest_id::text
        ELSE 'demo/shadow/archive-manifest/batch/'||p_manifest_id::text
    END;
    -- Manifest and DELETE live inside the same SECURITY DEFINER transaction,
    -- so the maintenance login cannot INSERT *anything* directly.
    INSERT INTO public.research_job
        (id,asset,parameters,progress,idempotency_key,status,finished_at)
        VALUES (p_manifest_id,'crypto',jsonb_build_object('kind',p_kind),
                p_manifest,v_manifest_key,'succeeded',clock_timestamp());
    SELECT j.* INTO v_manifest FROM public.research_job AS j
        WHERE j.id=p_manifest_id FOR UPDATE;
    IF NOT FOUND OR v_manifest.status <> 'succeeded'
       OR v_manifest.asset <> 'crypto'
       OR v_manifest.created_at < clock_timestamp()-interval '10 minutes'
       OR v_manifest.created_at > clock_timestamp()+interval '1 minute' THEN
        RAISE EXCEPTION 'Missing or stale verified archive manifest';
    END IF;

    v_kind := v_manifest.parameters->>'kind';
    IF v_kind='shadow_event_r2_manifest' THEN
        v_prefix:='demo/shadow/event/';
        v_expected_field:='ids';
        v_expected_format:='shadow-r2-event-batch-v1';
        IF v_manifest.idempotency_key NOT LIKE 'demo/shadow/archive-manifest/%'
           OR v_manifest.idempotency_key LIKE 'demo/shadow/archive-manifest/batch/%' THEN
            RAISE EXCEPTION 'Wrong raw archive namespace';
        END IF;
    ELSIF v_kind='diagnostic_batch_r2_manifest' THEN
        v_prefix:='demo/shadow/event-batch/';
        v_expected_field:='row_ids';
        v_expected_format:='shadow-diagnostic-r2-manifest-v1';
        IF v_count > 8 OR v_manifest.idempotency_key NOT LIKE 'demo/shadow/archive-manifest/batch/%' THEN
            RAISE EXCEPTION 'Wrong or oversized packed archive namespace';
        END IF;
    ELSE
        RAISE EXCEPTION 'Financial or unsupported archival manifest is not permitted';
    END IF;

    IF v_manifest.progress->>'format' IS DISTINCT FROM v_expected_format
       OR v_manifest.progress->>'source_prefix' IS DISTINCT FROM v_prefix
       OR v_manifest.progress->>'restorable' IS DISTINCT FROM 'true'
       OR jsonb_typeof(v_manifest.progress->v_expected_field) IS DISTINCT FROM 'array'
       OR jsonb_array_length(v_manifest.progress->v_expected_field) <> v_count
       OR (v_manifest.progress->>'count')::integer <> v_count
       OR COALESCE((v_manifest.progress->'reference'->>'sha256') ~ '^[a-f0-9]{64}
       OR split_part(v_manifest.progress->'reference'->>'key','/',3)
           <> (v_manifest.progress->'reference'->>'sha256')||'.json.gz'
       OR COALESCE((v_manifest.progress->'reference'->>'size')::bigint,0) <= 0 THEN
        RAISE EXCEPTION 'Unverified or unrelated archival manifest metadata';
    END IF;

    FOR v_record IN SELECT value FROM jsonb_array_elements(p_original_rows) LOOP
        IF jsonb_typeof(v_record) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'Invalid archive source record';
        END IF;
        v_row_id := (v_record->>'id')::uuid;
        IF v_row_id = ANY(v_ids)
           OR (v_manifest.progress->v_expected_field->>v_index) IS DISTINCT FROM v_row_id::text THEN
            RAISE EXCEPTION 'Archive identities must be complete, ordered and unique';
        END IF;
        SELECT j.* INTO v_row FROM public.research_job AS j WHERE j.id=v_row_id FOR UPDATE;
        IF NOT FOUND
           OR v_row.idempotency_key IS DISTINCT FROM (v_record->>'idempotency_key')
           OR v_row.idempotency_key NOT LIKE v_prefix||'%'
           OR v_row.status <> 'succeeded'
           OR v_row.asset <> 'crypto'
           OR v_row.created_at >= clock_timestamp()-interval '24 hours'
           OR v_row.progress ? 'archive'
           OR v_row.parameters IS DISTINCT FROM (v_record->'parameters')
           OR v_row.progress IS DISTINCT FROM (v_record->'progress')
           OR v_row.created_at IS DISTINCT FROM (v_record->>'created_at')::timestamptz
           OR v_row.started_at IS DISTINCT FROM (v_record->>'started_at')::timestamptz
           OR v_row.finished_at IS DISTINCT FROM (v_record->>'finished_at')::timestamptz
           OR v_row.lease_expires_at IS DISTINCT FROM (v_record->>'lease_expires_at')::timestamptz
           OR v_row.available_at IS DISTINCT FROM (v_record->>'available_at')::timestamptz
           OR v_row.lease_token IS DISTINCT FROM (v_record->>'lease_token')::uuid
           OR v_row.max_attempts IS DISTINCT FROM (v_record->>'max_attempts')::integer
           OR v_row.attempts IS DISTINCT FROM (v_record->>'attempts')::integer
           OR v_row.error_code IS DISTINCT FROM (v_record->>'error_code')
        THEN
            RAISE EXCEPTION 'Source record is not an unchanged aged diagnostic';
        END IF;

        IF v_kind='shadow_event_r2_manifest' THEN
            IF COALESCE(v_row.progress->>'event','') NOT IN (
                'FAVORITE_STAT_DECISION','FAVORITE_ENTRY_DECISION',
                'FAVORITE_REPEAT_OPPORTUNITY','FAVORITE_ENTRY_COHORT',
                'FAVORITE_TRIAL_QUALITY','SCALPER_OBSERVATION_BATCH') THEN
                RAISE EXCEPTION 'Financial or control event cannot be reclaimed';
            END IF;
        ELSIF v_row.progress->>'format' IS DISTINCT FROM 'shadow-diagnostic-batch-v1' THEN
            RAISE EXCEPTION 'Only packed nonfinancial diagnostics may be reclaimed';
        END IF;
        v_ids := array_append(v_ids,v_row_id);
        v_index := v_index+1;
    END LOOP;
    IF v_index <> v_count THEN
        RAISE EXCEPTION 'Archive source record count mismatch';
    END IF;

    RETURN QUERY DELETE FROM public.research_job AS r
        WHERE r.id=ANY(v_ids) RETURNING r.id::text;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_deleted <> v_count THEN
        RAISE EXCEPTION 'Atomic diagnostic reclaim did not delete all rows';
    END IF;
END;
$function$;
-- A SECURITY DEFINER function grants PUBLIC EXECUTE unless explicitly revoked.
REVOKE ALL ON FUNCTION public.mt_reclaim_shadow_diagnostics(uuid,text,jsonb,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.mt_reclaim_shadow_diagnostics(uuid,text,jsonb,jsonb)
    TO pocket_archive_maintenance;
COMMIT;
,false) IS NOT TRUE
       OR COALESCE((v_manifest.progress->'reference'->>'key') ~ '^demo/events/[a-f0-9]{64}[.]json[.]gz
       OR split_part(v_manifest.progress->'reference'->>'key','/',3)
           <> (v_manifest.progress->'reference'->>'sha256')||'.json.gz'
       OR (v_manifest.progress->'reference'->>'size')::bigint <= 0 THEN
        RAISE EXCEPTION 'Unverified or unrelated archival manifest metadata';
    END IF;

    FOR v_record IN SELECT value FROM jsonb_array_elements(p_original_rows) LOOP
        IF jsonb_typeof(v_record) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'Invalid archive source record';
        END IF;
        v_row_id := (v_record->>'id')::uuid;
        IF v_row_id = ANY(v_ids)
           OR (v_manifest.progress->v_expected_field->>v_index) IS DISTINCT FROM v_row_id::text THEN
            RAISE EXCEPTION 'Archive identities must be complete, ordered and unique';
        END IF;
        SELECT j.* INTO v_row FROM public.research_job AS j WHERE j.id=v_row_id FOR UPDATE;
        IF NOT FOUND
           OR v_row.idempotency_key IS DISTINCT FROM (v_record->>'idempotency_key')
           OR v_row.idempotency_key NOT LIKE v_prefix||'%'
           OR v_row.status <> 'succeeded'
           OR v_row.asset <> 'crypto'
           OR v_row.created_at >= clock_timestamp()-interval '24 hours'
           OR v_row.progress ? 'archive'
           OR v_row.parameters IS DISTINCT FROM (v_record->'parameters')
           OR v_row.progress IS DISTINCT FROM (v_record->'progress')
           OR v_row.created_at IS DISTINCT FROM (v_record->>'created_at')::timestamptz
           OR v_row.started_at IS DISTINCT FROM (v_record->>'started_at')::timestamptz
           OR v_row.finished_at IS DISTINCT FROM (v_record->>'finished_at')::timestamptz
           OR v_row.lease_expires_at IS DISTINCT FROM (v_record->>'lease_expires_at')::timestamptz
           OR v_row.available_at IS DISTINCT FROM (v_record->>'available_at')::timestamptz
           OR v_row.lease_token IS DISTINCT FROM (v_record->>'lease_token')::uuid
           OR v_row.max_attempts IS DISTINCT FROM (v_record->>'max_attempts')::integer
           OR v_row.attempts IS DISTINCT FROM (v_record->>'attempts')::integer
           OR v_row.error_code IS DISTINCT FROM (v_record->>'error_code')
        THEN
            RAISE EXCEPTION 'Source record is not an unchanged aged diagnostic';
        END IF;

        IF v_kind='shadow_event_r2_manifest' THEN
            IF v_row.progress->>'event' NOT IN (
                'FAVORITE_STAT_DECISION','FAVORITE_ENTRY_DECISION',
                'FAVORITE_REPEAT_OPPORTUNITY','FAVORITE_ENTRY_COHORT',
                'FAVORITE_TRIAL_QUALITY','SCALPER_OBSERVATION_BATCH') THEN
                RAISE EXCEPTION 'Financial or control event cannot be reclaimed';
            END IF;
        ELSIF v_row.progress->>'format' <> 'shadow-diagnostic-batch-v1' THEN
            RAISE EXCEPTION 'Only packed nonfinancial diagnostics may be reclaimed';
        END IF;
        v_ids := array_append(v_ids,v_row_id);
        v_index := v_index+1;
    END LOOP;
    IF v_index <> v_count THEN
        RAISE EXCEPTION 'Archive source record count mismatch';
    END IF;

    RETURN QUERY DELETE FROM public.research_job AS r
        WHERE r.id=ANY(v_ids) RETURNING r.id::text;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_deleted <> v_count THEN
        RAISE EXCEPTION 'Atomic diagnostic reclaim did not delete all rows';
    END IF;
END;
$function$;
-- A SECURITY DEFINER function grants PUBLIC EXECUTE unless explicitly revoked.
REVOKE ALL ON FUNCTION public.mt_reclaim_shadow_diagnostics(uuid,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.mt_reclaim_shadow_diagnostics(uuid,jsonb)
    TO pocket_archive_maintenance;
COMMIT;
,false) IS NOT TRUE
       OR split_part(v_manifest.progress->'reference'->>'key','/',3)
           <> (v_manifest.progress->'reference'->>'sha256')||'.json.gz'
       OR (v_manifest.progress->'reference'->>'size')::bigint <= 0 THEN
        RAISE EXCEPTION 'Unverified or unrelated archival manifest metadata';
    END IF;

    FOR v_record IN SELECT value FROM jsonb_array_elements(p_original_rows) LOOP
        IF jsonb_typeof(v_record) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'Invalid archive source record';
        END IF;
        v_row_id := (v_record->>'id')::uuid;
        IF v_row_id = ANY(v_ids)
           OR (v_manifest.progress->v_expected_field->>v_index) IS DISTINCT FROM v_row_id::text THEN
            RAISE EXCEPTION 'Archive identities must be complete, ordered and unique';
        END IF;
        SELECT j.* INTO v_row FROM public.research_job AS j WHERE j.id=v_row_id FOR UPDATE;
        IF NOT FOUND
           OR v_row.idempotency_key IS DISTINCT FROM (v_record->>'idempotency_key')
           OR v_row.idempotency_key NOT LIKE v_prefix||'%'
           OR v_row.status <> 'succeeded'
           OR v_row.asset <> 'crypto'
           OR v_row.created_at >= clock_timestamp()-interval '24 hours'
           OR v_row.progress ? 'archive'
           OR v_row.parameters IS DISTINCT FROM (v_record->'parameters')
           OR v_row.progress IS DISTINCT FROM (v_record->'progress')
           OR v_row.created_at IS DISTINCT FROM (v_record->>'created_at')::timestamptz
           OR v_row.started_at IS DISTINCT FROM (v_record->>'started_at')::timestamptz
           OR v_row.finished_at IS DISTINCT FROM (v_record->>'finished_at')::timestamptz
           OR v_row.lease_expires_at IS DISTINCT FROM (v_record->>'lease_expires_at')::timestamptz
           OR v_row.available_at IS DISTINCT FROM (v_record->>'available_at')::timestamptz
           OR v_row.lease_token IS DISTINCT FROM (v_record->>'lease_token')::uuid
           OR v_row.max_attempts IS DISTINCT FROM (v_record->>'max_attempts')::integer
           OR v_row.attempts IS DISTINCT FROM (v_record->>'attempts')::integer
           OR v_row.error_code IS DISTINCT FROM (v_record->>'error_code')
        THEN
            RAISE EXCEPTION 'Source record is not an unchanged aged diagnostic';
        END IF;

        IF v_kind='shadow_event_r2_manifest' THEN
            IF v_row.progress->>'event' NOT IN (
                'FAVORITE_STAT_DECISION','FAVORITE_ENTRY_DECISION',
                'FAVORITE_REPEAT_OPPORTUNITY','FAVORITE_ENTRY_COHORT',
                'FAVORITE_TRIAL_QUALITY','SCALPER_OBSERVATION_BATCH') THEN
                RAISE EXCEPTION 'Financial or control event cannot be reclaimed';
            END IF;
        ELSIF v_row.progress->>'format' <> 'shadow-diagnostic-batch-v1' THEN
            RAISE EXCEPTION 'Only packed nonfinancial diagnostics may be reclaimed';
        END IF;
        v_ids := array_append(v_ids,v_row_id);
        v_index := v_index+1;
    END LOOP;
    IF v_index <> v_count THEN
        RAISE EXCEPTION 'Archive source record count mismatch';
    END IF;

    RETURN QUERY DELETE FROM public.research_job AS r
        WHERE r.id=ANY(v_ids) RETURNING r.id::text;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_deleted <> v_count THEN
        RAISE EXCEPTION 'Atomic diagnostic reclaim did not delete all rows';
    END IF;
END;
$function$;
-- A SECURITY DEFINER function grants PUBLIC EXECUTE unless explicitly revoked.
REVOKE ALL ON FUNCTION public.mt_reclaim_shadow_diagnostics(uuid,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.mt_reclaim_shadow_diagnostics(uuid,jsonb)
    TO pocket_archive_maintenance;
COMMIT;
