"""Publishable, schema-uniform seed previews. Runtime never reads this dataset."""
import json
from pathlib import Path
from tasks import TASK_IDS, make_task, csv_text

out = Path('dataset')
out.mkdir(exist_ok=True)
rows = []
for seed in [4101,4102,4103]:
    for task_id in TASK_IDS:
        task = make_task(task_id,seed)
        family, difficulty = task_id.split('-')
        rows.append(dict(task_id=task_id,family=family,difficulty=difficulty,seed=seed,
                         brief=task.instructions,files_json=json.dumps(task.files,ensure_ascii=False),
                         expected_report_csv=csv_text(task.rows,task.columns),expected_summary_json=json.dumps(task.summary)))
(out/'preview.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
(out/'README.md').write_text('''---
license: mit
language:
- en
task_categories:
- reinforcement-learning
pretty_name: Office Workflow Lab v1 Seed Previews
configs:
- config_name: default
  data_files:
  - split: train
    path: preview.jsonl
---
# Office Workflow Lab v1

Built by Leon AI (https://github.com/leon-ai/leon) with Louistiti.

Source: https://github.com/louistiti/openenv-office-workflow
Verification: https://github.com/louistiti/openenv-office-workflow/releases/tag/office-v1

36 synthetic seed previews: 12 task identities across six office/data workflow families, each shown at three reproducible seeds. The runtime image generates fresh input tables on reset. These are inspectable previews, not 36 independent programs or an empirical learning result.

Fields `files_json` and `expected_summary_json` are JSON encoded strings to keep the viewer schema uniform. `expected_report_csv` is the reference output for that seed. No real-world personal or business records are included. Public targets are not exposed in the runtime tool workspace. Arena runs only the immutable image, not this dataset.

Local validation: 507 tests including 480 independent SQL/Python comparisons, 24 real-network reference episodes, all six pinned SDK runtime checks. A deliberately capped local quantized-Qwen proxy smoke test completed two attempts with rewards 1.0 and 0.55625. This does not demonstrate training benefit or predict an Arena score. Linux container and anonymous image verification reports are in the source release when complete. No new Arena submission without approval of the exact request.
''')
print(json.dumps({'preview_rows':len(rows),'identities':len(TASK_IDS),'seeds':3,'synthetic':True}))
