-- Validation queries for iris_staging. Each says what a healthy result looks like.
-- Run:  docker compose exec db psql -U iris -d iris -f /dev/stdin < sql/validation.sql

-- 1. Volume by SPV hypothesis label (labels always say "hypothesis")
SELECT spv_label, COUNT(*) AS records
FROM iris_staging.corporate_distress_records GROUP BY spv_label ORDER BY records DESC;

-- 2. Duplicate stable IDs: expect 0 rows
SELECT record_id, COUNT(*) FROM iris_staging.corporate_distress_records
GROUP BY record_id HAVING COUNT(*) > 1;

-- 3. Rows missing source, dates or the raw payload: expect 0
SELECT COUNT(*) AS untraceable_rows FROM iris_staging.corporate_distress_records
WHERE source IS NULL OR source_date IS NULL OR retrieved_at IS NULL OR raw_payload IS NULL;

-- 4. Every scored row (score > 0) explains itself: expect 0
SELECT COUNT(*) AS scored_without_evidence FROM iris_staging.corporate_distress_records
WHERE spv_score > 0 AND spv_evidence = '[]';

-- 5. A name match is never promoted to confirmation: expect 0
SELECT COUNT(*) AS bad_name_matches FROM iris_staging.corporate_distress_records
WHERE crosscheck_status = 'name_candidate_only'
  AND crosscheck_evidence NOT LIKE '%NOT evidence of identity%';

-- 6. Rejected data by reason (the audit trail for dropped input)
SELECT reason, COUNT(*) AS records
FROM iris_staging.corporate_distress_rejects GROUP BY reason ORDER BY records DESC;

-- 7. Strongest hypotheses with the rules that fired
SELECT company_name, register_court, register_type || ' ' || register_number AS register,
       spv_score, spv_evidence
FROM iris_staging.corporate_distress_records ORDER BY spv_score DESC, record_id LIMIT 5;

-- 8. Records whose formation date is unknown (informational): the source stated none, nothing was guessed.
--    Use  WHERE formation_date IS NOT NULL  when you only want records with a known date.
SELECT COUNT(*) AS unknown_formation_date FROM iris_staging.corporate_distress_records
WHERE formation_date IS NULL;
