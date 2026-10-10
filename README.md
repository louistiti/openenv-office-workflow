# Office Workflow Lab v1

An OpenEnv training experiment built by Leon AI ([github.com/leon-ai/leon](https://github.com/leon-ai/leon)) with Louistiti.

## What this trains

Twelve task identities across six office/data workflow families: CRM cleanup, overdue invoice reconciliation, net sales with FX and refunds, inventory replenishment, weekly payroll and expense-policy compliance. Each reset generates fresh synthetic tables, corrections and edge cases. A supplied seed makes replay deterministic; no seed uses fresh randomness. There is no real customer, financial or personal data.

Agents inspect CSV sources, issue bounded read-only SQLite SELECT/CTE queries, write `report.csv` and `summary.json`, and submit. Reports require row-level results, correct units, duplicate/revision handling and policy precedence. The episode allows 24 actions; reference workflows require five. No Python execution, filesystem, network, database writes or external tools are exposed.

Rewards are terminal only: 60% verified report cells and 40% exact summary metrics. Extra/missing rows and duplicate keys reduce report credit; duplicate JSON keys, wrong headers and invalid summary keys are rejected. Full reward requires both artifacts. Summary-only submissions cannot exceed 0.4. SQL errors reveal no target values. This is a bounded outcome verifier, not a claim of a perfectly exploit-proof benchmark.

## Verification

- 507 tests passed locally, including 480 independently implemented SQL/Python comparisons across all 12 identities and 40 seeds, plus isolation, malformed-output and lifecycle tests.
- 24 real network WebSocket reference episodes passed, two fresh seeds per identity.
- All six runtime checks passed using OpenEnv revision `86a180ede21e044f7929b9a7783ad83aa67d83a3`.
- Model smoke-test status and limitations are in `SMOKE.md`. It is deliberately capped, not extended difficulty tuning.
- Publication CI reruns tests inside Linux, builds a non-root linux/amd64 image, checks the real container and publishes immutable-digest reports. Anonymous pull validation is a separate workflow so package visibility can be verified first.

Correctness and tool compatibility do not establish learning benefit or an Arena score. Prior Python Repair Lab v3 scored 5/40 against the 4/40 reference. This office environment is a focused follow-up, not a promised ranking improvement. Twelve identities are not twelve fixed examples, but six workflow families still limit diversity. No new Arena submission without human approval of the exact request.

## Reproduce

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest -q test_environment.py
.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8767
# In another terminal:
.venv/bin/python live_replay.py
.venv/bin/openenv validate --url http://127.0.0.1:8767 --level runtime --json
```

The runtime Docker image copies only `server.py`, `tasks.py` and `openenv.yaml`; independent SQL reference solutions, smoke runner and validation files remain outside the image. The public dataset contains seeded previews for inspection; the Arena runs only the image. `prepare_submission.py` requires the actual immutable digest and the schema returned by that container.

License: MIT. OpenEnv is separately licensed by its upstream authors.
