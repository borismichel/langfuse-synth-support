# Support setup #329 evidence

Source-ready candidate 0.3.3; reviewed release, signature verification and registry update are pending.
This is an existing registered-kit update; #324 does not require new-kit admission
or a fresh live production run. Live checks were not run for this delta.
Recorded 2026-10-14 against kit base ddaaa51f176a63822594e15b103ed9b7ac7c3425.
Core v4.3.0 is installed from the immutable release, peeled commit
ba4a4a276079ed49865becffc7955acde148147a. Both dependency pins and the publish
workflow use v4.3.0; Langfuse SDK remains >=4.14,<5.

## Scope and accepted story

The existing retrieval regression, resolution comparison, session deflection and
cost attribution story is retained. Presentation remains 1,000 turns with seed 42.
Quick rehearsal uses 200 turns, chosen by generating and verifying the complete
story, not by choosing the schema minimum. Custom retains the existing bounds;
a tiny custom volume can lack the statistical evidence the verifier requires.
The explicit #329 contract preserves seed → verify and overrides the generic
authoring skill's probe/plan requirement. No plan or approval stage is fabricated.

The old sampler excluded the selected day. Generation now covers 28 inclusive UTC
calendar days: Friday 2026-10-16 means 2026-09-19 through 2026-10-16. Sparse inputs
retain exactly their requested count while including the selected day. Turn starts
reserve 16 minutes before the upper boundary for children and delayed feedback.
The reindex boundary and every child duration/score offset remain unchanged.

## Offline evidence

[Generated evidence](generated-evidence.json) comes from finalized runtime Spools,
projected through the external v4 read transport into the real kit verifier. No
Langfuse request was made. Both seed 42 volumes passed all nine checks, including
actual selected-day support activity. This is generation/readback evidence, not
proof of ingestion into Langfuse.

| Measurement | Rehearsal 200 | Presentation 1,000 |
| --- | --- | --- |
| Observation count | 1,136 | 5,745 |
| Earliest observation UTC | Sep 19 05:20:31.825600 | Sep 19 05:26:33.064690 |
| Latest observation end UTC | Oct 16 17:28:45.031483 | Oct 16 19:24:49.748298 |
| Session deflection scores | 126 | 624 |
| Self-served / escalated | 166 / 34 | 791 / 209 |
| Retrieval pre / post mean | .820 / .575 | .812 / .548 |
| Cost-attributed generations | 400 / 400 | 2,000 / 2,000 |

The normal seed path produces SCHEDULE.json with the requested calendar and bounds
measured from finalized observations, alongside DEMO_SCRIPT.md. Tests check those
files against the actual Spool. Tests also cover seed196's formerly overflowing
feedback, year and leap-day boundaries, DST calendar dates, and absent selected-day
observations despite remaining scores. Dry-run remains artifact-free.

The authoring command [offline result](offline-check.json) reports local_ready=true:
manifest validation, conformance and all 49 tests passed. Stateless anchor checks are
inapplicable under the existing core contract; all applicable conformance checks ran.

## Golden review

The 24-turn golden was regenerated with `synth-authoring freeze` only after comparing
candidate and committed Spools. Both contain 257 records with the same event counts.
After removing timestamp, startTimeUnixNano, endTimeUnixNano and completion_start_time,
there are zero differences: IDs, inputs, outputs, costs, scores and score subjects are
unchanged. The golden change is chronology only. At200/1000, weekday-weighted date
sampling slightly changes boundary cohort membership; the measured regression,
resolution, deflection and cost checks above still pass.

## Product references

The linked Langfuse skill entrypoint SHA256 was
`e8908ea1c924374ba7bc5e82b220709d107db6a3450a0c4d72228a91a2a7534a`.
Current official sources inspected during implementation:
[documentation index](https://langfuse.com/llms.txt),
[data model](https://langfuse.com/docs/observability/data-model), and
[SDK scores](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk).
Observation vocabulary and score subjects were preserved; no new product semantics
or SDK major version were introduced.

## Readiness checklist

| Check | Status and evidence |
| --- | --- |
| Accepted story | Passed offline at 200/1000; unchanged runbook beats, verifier results above. |
| Deployment pipeline | Passed: existing seed→verify declaration retained and manifest test asserts it. |
| Cost estimate and confirmation | Not applicable: explicit #329 pipeline contract has neither stage. Historical generation costs remain verified. |
| Progress | Passed in authenticated Depot fixture: seed in progress, verify waiting; live progress not re-exercised for this delta. |
| Offline checks | Passed: validation, conformance,49 tests. |
| Seed and scale | Passed offline at rehearsal 200 and presentation 1000; existing advertised 100000 maximum is unchanged and was not revalidated under deployed resource limits; that inherited limit is outside this narrow delta. |
| Runtime assets | Existing prompts, score subjects and deterministic assets retained; live checks not run for this delta. |
| Live verification | Not run: no remote target used or seeded; a fresh live production run is not required for this existing-kit update. |
| Companion | Offline conformance health/index passed; delivered interactions not re-exercised for this delta. |
| Presenter delivery | Artifact publication tested; Depot setup/save/resume screenshots recorded in matching portal evidence. Native Langfuse story was not re-exercised for this delta. |
| Release and registry | Pending: root coordinates reviewed 0.3.3 release, exact image signature verification and existing registry bump. New-kit admission is not applicable. |
| Publication | Pending: no tag, push, main merge or registry write performed by this task. |

## Copy correction candidate 0.3.4

The final Depot copy audit found implementation terminology in the target-trace
field description and an incomplete reproducibility claim in the seed description.
Version 0.3.4 labels trace volume directly and explains that reproducibility also
requires the same configuration and Data as of date, retaining the duplicate-data
warning. All runtime code, defaults, limits, schedule behavior and core pins remain
unchanged from 0.3.3. Manifest validation passes. This copy correction requires no
new seed or live verification; its review, CI and signed image publication remain
release-coordinator steps. The existing 0.3.3 release remains immutable.
