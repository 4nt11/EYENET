-- forum-only-filter.sql
--
-- Scrub a RESTORED STAGING copy of the eyenet DB to FORUM+OPERATOR data only.
-- Run against a disposable staging postgres, NEVER against dev.
--
-- Strategy:
--   * SET session_replication_role = replica disables FK checks for the txn
--     so delete order does not matter, but the END STATE must be consistent
--     (no row pointing at a deleted row).
--   * The two "cross-source bridge" columns are nullable; NULL them instead
--     of cascading (keep the forum artifact, forget its TG sub-reference).
--   * A handful of bare-UUID soft refs (linkage/persona/observation/profile/
--     corpus_cursor/search_document) have no FK but still deserve cleanup or
--     prod will boot with logical orphans.
--
-- Audit DB (eyenet_audit) is NOT filtered - it is the hash-chained operator
-- action log and must stay intact. Restore it as-is.

BEGIN;
SET session_replication_role = replica;

-- 1. The one source of truth: what we KEEP.
CREATE TEMP TABLE keep_src AS
    SELECT id FROM source WHERE kind IN ('FORUM', 'OPERATOR');

-- Freeze the to-delete sets BEFORE we start deleting. (If computed inline,
-- a later DELETE would change the set mid-run.)
CREATE TEMP TABLE del_msg    AS SELECT id FROM message        WHERE source_id NOT IN (SELECT id FROM keep_src);
CREATE TEMP TABLE del_actor  AS SELECT id FROM actor          WHERE source_id NOT IN (SELECT id FROM keep_src);
CREATE TEMP TABLE del_group  AS SELECT id FROM group_         WHERE source_id NOT IN (SELECT id FROM keep_src);
CREATE TEMP TABLE del_cand   AS SELECT id FROM group_candidate WHERE source_id NOT IN (SELECT id FROM keep_src);
CREATE TEMP TABLE del_coll   AS SELECT id FROM collector      WHERE source_id NOT IN (SELECT id FROM keep_src);
CREATE TEMP TABLE del_ident  AS SELECT id FROM identity       WHERE source_id NOT IN (SELECT id FROM keep_src);
CREATE TEMP TABLE del_attach AS SELECT a.id FROM attachment a JOIN del_msg m ON a.message_id = m.id;

CREATE INDEX ON del_msg (id);
CREATE INDEX ON del_actor (id);
CREATE INDEX ON del_group (id);
CREATE INDEX ON del_cand (id);
CREATE INDEX ON del_coll (id);
CREATE INDEX ON del_ident (id);
CREATE INDEX ON del_attach (id);

-- 2. Cross-source bridges: NULL (nullable FKs), do not cascade.
UPDATE infrastructure_artifact
   SET resolved_to_source_id = NULL
 WHERE resolved_to_source_id IS NOT NULL
   AND resolved_to_source_id NOT IN (SELECT id FROM keep_src);

UPDATE message
   SET forward_origin_actor_id = NULL
 WHERE forward_origin_actor_id IN (SELECT id FROM del_actor);

UPDATE message
   SET reply_to_msg_id = NULL
 WHERE reply_to_msg_id IN (SELECT id FROM del_msg);

UPDATE message
   SET forward_of_msg_id = NULL
 WHERE forward_of_msg_id IN (SELECT id FROM del_msg);

-- collector_group_membership has CHECK (joined_via='CANDIDATE' <-> joined_via_candidate_id IS NOT NULL),
-- so we cannot NULL the FK. Delete the memberships whose candidate is leaving instead;
-- realistically these are non-FORUM collectors anyway and are caught by the collector branch,
-- but belt-and-suspenders this path too.
DELETE FROM collector_group_membership
 WHERE joined_via_candidate_id IN (SELECT id FROM del_cand);

UPDATE group_candidate
   SET assigned_collector_id = NULL
 WHERE assigned_collector_id IN (SELECT id FROM del_coll);

-- 3. Downstream of message.
DELETE FROM reaction                       WHERE message_id IN (SELECT id FROM del_msg);
DELETE FROM incident                       WHERE message_id IN (SELECT id FROM del_msg);
DELETE FROM incident_label                 WHERE message_id IN (SELECT id FROM del_msg);
DELETE FROM message_geo                    WHERE message_id IN (SELECT id FROM del_msg);
DELETE FROM message_observation            WHERE message_id IN (SELECT id FROM del_msg);
DELETE FROM infrastructure_artifact_mention WHERE message_id IN (SELECT id FROM del_msg);
DELETE FROM thread_summary                 WHERE op_message_id IN (SELECT id FROM del_msg);
DELETE FROM stealer_processing             WHERE attachment_id IN (SELECT id FROM del_attach);
DELETE FROM attachment                     WHERE id IN (SELECT id FROM del_attach);

-- 4. Downstream of actor.
DELETE FROM actor_alias_history WHERE actor_id IN (SELECT id FROM del_actor);
DELETE FROM actor_artifact      WHERE actor_id IN (SELECT id FROM del_actor);
DELETE FROM identity_label      WHERE actor_id IN (SELECT id FROM del_actor);
DELETE FROM manual_crew_member  WHERE actor_id IN (SELECT id FROM del_actor);
DELETE FROM reaction            WHERE actor_id IN (SELECT id FROM del_actor);
DELETE FROM engagement_authorization WHERE actor_id IN (SELECT id FROM del_actor);
DELETE FROM group_candidate_mention  WHERE mentioning_actor_id IN (SELECT id FROM del_actor);
DELETE FROM actor_relation
 WHERE from_actor_id IN (SELECT id FROM del_actor)
    OR to_actor_id   IN (SELECT id FROM del_actor);

-- 4b. Bare-UUID soft refs to actor (no FK but logical orphans).
DELETE FROM linkage
 WHERE actor_a_id IN (SELECT id FROM del_actor)
    OR actor_b_id IN (SELECT id FROM del_actor);
DELETE FROM linkage_verifier_result WHERE linkage_id NOT IN (SELECT id FROM linkage);
DELETE FROM feedback_pair          WHERE linkage_id NOT IN (SELECT id FROM linkage);
DELETE FROM persona_membership     WHERE actor_id IN (SELECT id FROM del_actor);
DELETE FROM observation            WHERE actor_id IN (SELECT id FROM del_actor);
DELETE FROM profile                WHERE actor_id IN (SELECT id FROM del_actor);
DELETE FROM corpus_cursor          WHERE actor_id IN (SELECT id FROM del_actor);

-- 5. Downstream of group_.
DELETE FROM engagement_authorization       WHERE group_id IN (SELECT id FROM del_group);
DELETE FROM group_access_artifact          WHERE group_id IN (SELECT id FROM del_group);
DELETE FROM group_snapshot                 WHERE group_id IN (SELECT id FROM del_group);
DELETE FROM membership                     WHERE group_id IN (SELECT id FROM del_group)
                                              OR actor_id IN (SELECT id FROM del_actor);
DELETE FROM collector_group_membership     WHERE collector_id IN (SELECT id FROM del_coll)
                                              OR group_id    IN (SELECT id FROM del_group);
DELETE FROM thread_summary                 WHERE group_id IN (SELECT id FROM del_group);

-- 6. Downstream of group_candidate + collector.
DELETE FROM group_candidate_mention WHERE candidate_id IN (SELECT id FROM del_cand)
                                      OR observed_by_collector_id IN (SELECT id FROM del_coll);
DELETE FROM group_access_artifact   WHERE candidate_id IN (SELECT id FROM del_cand);
DELETE FROM message_observation     WHERE collector_id IN (SELECT id FROM del_coll);

-- 7. Bare-UUID search_document (nullable source_id).
DELETE FROM search_document
 WHERE source_id IS NOT NULL
   AND source_id NOT IN (SELECT id FROM keep_src);

-- 8. Direct-source-id tables (minus infra_artifact which we only NULLed).
DELETE FROM message          WHERE id IN (SELECT id FROM del_msg);
DELETE FROM group_candidate  WHERE id IN (SELECT id FROM del_cand);
DELETE FROM group_           WHERE id IN (SELECT id FROM del_group);
DELETE FROM collector        WHERE id IN (SELECT id FROM del_coll);
DELETE FROM identity         WHERE id IN (SELECT id FROM del_ident);
DELETE FROM actor_relation   WHERE source_id NOT IN (SELECT id FROM keep_src);
DELETE FROM actor            WHERE id IN (SELECT id FROM del_actor);
DELETE FROM source_domain    WHERE source_id NOT IN (SELECT id FROM keep_src);

-- 9. Sources themselves, last.
DELETE FROM source WHERE id NOT IN (SELECT id FROM keep_src);

-- 10. Hand FK enforcement back. COMMIT will fail if any FK is violated,
-- which is exactly the safety net we want.
SET session_replication_role = origin;
COMMIT;

-- 11. Post-hoc sanity. Should all be 0.
\echo '--- sanity (all should be 0) ---'
SELECT 'actors not in keep_src'      AS what, count(*) FROM actor     a WHERE a.source_id NOT IN (SELECT id FROM source WHERE kind IN ('FORUM','OPERATOR'))
UNION ALL SELECT 'messages not in keep_src',  count(*) FROM message   m WHERE m.source_id NOT IN (SELECT id FROM source WHERE kind IN ('FORUM','OPERATOR'))
UNION ALL SELECT 'groups not in keep_src',    count(*) FROM group_    g WHERE g.source_id NOT IN (SELECT id FROM source WHERE kind IN ('FORUM','OPERATOR'))
UNION ALL SELECT 'collectors not in keep_src',count(*) FROM collector c WHERE c.source_id NOT IN (SELECT id FROM source WHERE kind IN ('FORUM','OPERATOR'))
UNION ALL SELECT 'identities not in keep_src',count(*) FROM identity  i WHERE i.source_id NOT IN (SELECT id FROM source WHERE kind IN ('FORUM','OPERATOR'))
UNION ALL SELECT 'artifact.resolved_to dangling', count(*) FROM infrastructure_artifact a WHERE a.resolved_to_source_id IS NOT NULL AND a.resolved_to_source_id NOT IN (SELECT id FROM source);

\echo '--- final shape ---'
SELECT 'source' AS t, kind::text AS k, count(*) FROM source GROUP BY kind
UNION ALL SELECT 'message', NULL, count(*) FROM message
UNION ALL SELECT 'actor',   NULL, count(*) FROM actor
UNION ALL SELECT 'group_',  NULL, count(*) FROM group_
UNION ALL SELECT 'incident',NULL, count(*) FROM incident
UNION ALL SELECT 'infrastructure_artifact', NULL, count(*) FROM infrastructure_artifact
UNION ALL SELECT 'attachment', NULL, count(*) FROM attachment
UNION ALL SELECT 'collector',  NULL, count(*) FROM collector
UNION ALL SELECT 'identity',   NULL, count(*) FROM identity
ORDER BY 1, 2;
