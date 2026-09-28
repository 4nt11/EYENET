# Incidents v2 build — phase tracker (worktree: incidents-v2-attachment)

Goal: 16-leaf hierarchical taxonomy + attachment-aware model input. Built/trained/tested
in this worktree, NOT merged to main and NOT deployed — awaits operator blessing of the
trained model + the AI-labeled gold rows.

Leaf set (16): defacement, ddos_attack, intrusion, breach_dump, credentials, stealer_logs,
iab_corporate, crimeware_tooling, crime_aas, telecom_abuse, phishing_delivery, fraud_ops,
recruiting, alliance, crew_ops, infra_resale. See development/incident-taxonomy-hierarchy.md.

## Phases
- [x] P1 enrich_text + attachment_files_by_message_ids (commit bbf49c0)
- [x] P2 label surface → 16 leaves: SIG2LABEL, rules.TAXONOMY_LABELS, FE data.js
      INCIDENT_LABELS+tones, dataset LABELS. (commit 3f8a00f, 6581815)
- [x] P3 v2 silver via bootstrap_silver (23k labeled); train_mmbert_ml reads gold_v2 +
      enrich_text join. (commit 6581815)
- [x] P5 inference enrichment: service._flush + backfill enrich_text before classify_batch;
      prefilter/rules stay on raw body. (commit 3f8a00f)
- [x] P4 trained + calibrated -> dataset/mmbert-incident-ml-v2/ (in THIS worktree's dataset,
      gitignored ~1.2GB). adafactor+bs2, 18 min. calibration.json written.
- [ ] Operator: bless model + AI-labeled gold, then merge worktree to main + deploy.

## v2 model eval (held-out human gold, post-calibration F1 @ operating point)
14/16 leaves usable. telecom_abuse .95, stealer_logs .90, alliance .86, phishing .78,
iab_corporate .77, crime_aas .74, defacement/ddos/fraud_ops .67, intrusion .65,
breach_dump .58, credentials .55, crimeware_tooling .47, infra_resale .45.
THIN (need more labels / keep prefilter-assisted): recruiting .27 (sup 5), crew_ops .25 (sup 15).
AUROC (threshold-free) is strong even where F1 lags: infra_resale .89, credentials .84.

## To bless + deploy (operator, on main after review)
1. Review the AI-labeled gold: cand_labels_all + logs_labels_all (+ the 98 rescued) in
   labeler.html; correct anything wrong; re-assemble gold_v2; optionally re-run P3/P4.
2. Merge this worktree branch to main (--no-ff). The 16-leaf surface + attachment scoring
   land together (do NOT merge surface without the model — 6-head prod model would break).
3. Deploy: put mmbert-incident-ml-v2 where EYENET_INCIDENT_MODEL_DIR points (or into
   deploy/docker/incident-model/), rebuild eyenet:incidents, recreate incident-classifier.
   The DB needs no change (labels are strings; incident/incident_label tables unchanged).
4. Backfill re-classify under v2 if desired: `eyenet incidents-backfill` (now attachment-aware).

## Test state (worktree)
- All incidents/storage/api/classifier tests GREEN. FE builds.
- Pre-existing failures on this HEAD (NOT from this work, fail in isolation, unrelated
  subsystems): test_user_scopes::test_scopes_revoke_removes_grant,
  test_actors_list::test_list_newest_activity_first, test_sysstats::test_snapshot_shape.

## Run notes (worktree import trap)
- eyenet resolves to worktree only when cwd (worktree root) is on sys.path. Run scripts via:
  `python -c "import sys; sys.path[:0]=['','dataset']; import runpy; runpy.run_path('dataset/X.py', run_name='__main__')"` from the worktree root. PYTHONPATH is blocked by the sandbox guard here.
- Data files (eyenet_messages.jsonl, gold_v2.mllabels.jsonl, silver_multilabel.jsonl) copied
  into worktree/dataset from main; gitignored, not committed.

## v2 SIG2LABEL mapping (prefilter signal -> leaf) applied in P2
deface_banner->defacement; ddos_command,check_host,multi_target->ddos_attack;
compromise_confirmed->intrusion; leak_host,leak_label,target_dump_file,pii_schema,
onion_url->breach_dump; hash_list,cred_combo,cred_label->credentials;
stealer_logs,cloud_pass->stealer_logs; access_material->iab_corporate;
tool_sale->crimeware_tooling; telecom_abuse->telecom_abuse.
(No prefilter signal for crime_aas/phishing_delivery/fraud_ops/infra_resale/recruiting/
alliance/crew_ops — those rely on the model + operator rules.)

## Do NOT
- merge to main / deploy: 6-head prod model would break under 16-leaf surface.
- treat AI-labeled gold (cand_*, logs_* passes) as verified — operator must review.
