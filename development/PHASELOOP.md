# PHASELOOP index — API_PLAN.md driven

One line per phase. The highest-numbered `PHASE-N.md` is the live continuation token.

- [PHASE-1](PHASE-1.md) — ✅ REQUESTED→JOINED membership resolution (post-E5.5 #1 loose end). Atomic CAS-first transition + event/probe detector + self-healing compensation. 1949 passed, 88.28% cov, mypy/ruff clean, 3 adversarial rounds → solid. Checkpoint `546e710`. Next: Group B.
- [PHASE-2](PHASE-2.md) — ✅ M9.B1 file-access signing-key registry + acknowledgment nonces + Ed25519 verify primitives (Group B foundation, §5.5–5.7). User-scoped key lookup + partial-unique single-active enforcement + injection-proof canonical form + atomic nonce CAS. 1972 passed, 88.36% cov, mypy/ruff clean, 2 adversarial rounds (crypto unanimous-solid bar) → solid. Un-merged on `worktree-e55-requested-to-joined`. **Next: M9.B2 (journal table + record_access) — resolve the server-vs-client signing fork at the B2 scoping checkpoint.**
