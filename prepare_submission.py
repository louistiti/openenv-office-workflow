"""Build exact Arena request from verified container schema and immutable digest."""
import argparse
import json
import re
from pathlib import Path
from tasks import TASK_IDS

p = argparse.ArgumentParser()
p.add_argument('--image', required=True)
p.add_argument('--schema', default='schema-local.json')
p.add_argument('--output', default='submission-office-v1.json')
args = p.parse_args()
image = args.image.strip()
if not re.fullmatch(r'ghcr\.io/louistiti/openenv-office-workflow@sha256:[0-9a-f]{64}', image):
    raise ValueError('An immutable verified office image digest is required')
request = dict(submission_id='office-workflow-lab-v1', name='Office Workflow Lab v1',
               dataset='Louistiti/openenv-office-workflow', image=image, server_port=8000,
               schema=json.loads(Path(args.schema).read_text()),
               tasks=[dict(task_id=x, split='train', reset_wall_s=120, rollout_wall_s=600,
                           verifier_wall_s=120, tool_wall_s=120, tool_calls_total=24,
                           tool_calls_per_minute=60, completion_tokens=8192, context_tokens=24576,
                           memory_gib=2, cpu_floor_vcpus=1, workspace_gib=1) for x in TASK_IDS],
               example_actions=[dict(operation='submit')],finish_action=dict(operation='submit'),
               source='https://github.com/louistiti/openenv-office-workflow')
Path(args.output).write_text(json.dumps(request,indent=2)+'\n')
print(json.dumps({'request':args.output,'task_ids':len(TASK_IDS),'image':image,'submitted':False}))
