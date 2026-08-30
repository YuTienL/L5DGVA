> **Superseded.** See START_HERE.md for the current canonical entry point and accurate current numbers/claims.

# Real Project Onboarding

1. Declare execution mode.
2. Provide DUT RTL path.
3. Provide Spec / PHY / Programming / Register docs.
4. Provide VIP installation path if available.
5. Run DUT Interface Extractor.
6. Run VIP API Learner.
7. Build semantic model.
8. Review role/topology/boundary.
9. Generate UVM environment.
10. Compile.
11. Repair until compile PASS or explicit blocker.
12. Run protocol-specific smoke.
13. If failure: first-failure stop, VIP trace, targeted waveform if needed.
14. Repair/rerun.
15. Run qualification suite.
16. Promote capability only with evidence.
