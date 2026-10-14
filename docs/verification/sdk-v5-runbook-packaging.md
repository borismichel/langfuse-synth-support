# Installed runbook publication — v0.3.6 candidate

Fresh v0.3.5 admission passed seeding, scenario verification and Companion smoke, and the live SDK v5 journey passed. However, normal Depot Artifacts showed only SCHEDULE.json. The seed log reported DEMO_SCRIPT.md missing at /usr/local/lib/python3.12/DEMO_SCRIPT.md. Source-checkout tests had hidden the delivery defect: the publisher inferred a repository root from its installed module path, while the wheel omitted the root runbook.

The publisher and Dockerfile are unchanged between v0.3.4 and v0.3.5, and package discovery is unchanged. This is an existing packaging defect found during the required released-image rehearsal, not an SDK v5 telemetry regression. No existing deployment was repaired in place.

The root DEMO_SCRIPT.md remains the only maintained runbook. Source distributions include it; wheel builds copy it into the synth package. Runtime publication uses importlib.resources, with the existing source-checkout fallback for local development. The content, declared output name, seed invocation and best-effort destination error handling are unchanged. Candidate version is 0.3.6; SDK remains exactly 5.0.1, both runtime and authoring core pins remain v5.0.0, and the reusable publish workflow remains v5.0.0.

The pre-agreed test seam is installed-distribution publication of the unchanged runbook without source-checkout access. The regression builds an sdist, builds its wheel offline, installs that wheel into an isolated directory, removes both build source trees, and calls the public publisher under isolated Python import resolution from an unrelated working directory. Before the fix it failed with missing output; after the fix the published bytes equal the committed source. Existing seed integration proves seed invokes publication; this packaging test does not import or reseed live data.

Validation on Python 3.12:

- 51 tests passed, no skips, including the installed-wheel regression and unchanged full deterministic Spool golden.
- Manifest validation and enforcing Contract conformance passed (stateless anchor check legitimately inapplicable).
- A new disposable container used the verified v0.3.5 runtime base plus the locally built v0.3.6 wheel. It ran network-disabled with a read-only root and no capabilities. A tmpfs hid /app, so the source checkout was inaccessible at its usual location; isolated Python imported only the candidate install. It published /app/out/DEMO_SCRIPT.md, 8873 bytes, SHA256 0f60c7756cd1098b5f29e542aa0c9e98254464d6abed7338ef1eb08e48b4ce27, matching the unchanged source.
- Golden SHA256 unchanged: ea081d24f60c258aa6c18064b6b8d2e07f857cc746c8acba0c3dd5f6e4b2f903.

The container check proves candidate packaging in the runtime environment; it is not a signed v0.3.6 release receipt. Independent review, immutable publication and a fresh normal admission confirming Depot collects and renders the runbook remain release obligations.
