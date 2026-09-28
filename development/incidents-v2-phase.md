# Incidents v2 build — phase tracker (worktree: incidents-v2-attachment)

Goal: 16-leaf hierarchical taxonomy + attachment-aware model input. Built/trained/tested
in this worktree, NOT merged to main and NOT deployed — awaits operator blessing of the
trained model + the AI-labeled gold rows.

Leaf set (16): defacement, ddos_attack, intrusion, breach_dump, credentials, stealer_logs,
iab_corporate, crimeware_tooling, crime_aas, telecom_abuse, phishing_delivery, fraud_ops,
recruiting, alliance, crew_ops, infra_resale. See development/incident-taxonomy-hierarchy.md.

## Phases
- [x] P1 enrich_text(body, att_files) + attachment_files_by_message_ids (commit bbf49c0)
- [ ] P2 label surface → 16 leaves: classifier.SIG2LABEL, rules.TAXONOMY_LABELS,
      dataset/train_mmbert_ml.LABELS (+tune_thresholds/calibrate reuse it), FE data.js
      INCIDENT_LABELS + tones. (classifier reads labels.json at runtime; no hardcoded 6.)
- [ ] P3 enrich gold + regen silver: attachment-join gold_v2 text via enrich_text;
      re-run bootstrap_silver under v2 SIG2LABEL.
- [ ] P4 train + calibrate candidate model -> dataset/mmbert-incident-ml-v2/ (separate dir);
      capture honest gold-test per-leaf. GPU; if OOM/長, leave command ready.
- [ ] P5 inference enrichment: service._flush + backfill fetch attachment_files and
      enrich_text before classify_batch (train/serve parity).
- [ ] Full battery green; write handoff; leave for operator to bless + merge + deploy.

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
