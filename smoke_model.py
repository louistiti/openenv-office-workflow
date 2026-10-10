"""Capped local tool-use smoke test, not Arena training or a score prediction."""
import json
import time
import urllib.request
from pathlib import Path
from server import OfficeEnvironment, OfficeAction

BASE = 'http://127.0.0.1:11434'
MODEL = 'qwen3.8:27b'
TOTAL_SECONDS = 240

def main():
    started = time.monotonic()
    rows = []
    schema = OfficeAction.model_json_schema()
    tool = {'type':'function','function':{'name':'office_step','description':'Operate the office workspace, then submit the completed artifacts.','parameters':schema}}
    for task_id in ['invoices-standard','expenses-advanced']:
        env = OfficeEnvironment()
        initial = env.reset(task_id=task_id,seed=8671)
        messages = [{'role':'system','content':'Complete the office workflow using office_step tools. Read source data or query the source tables, compute all required results, write both report.csv and summary.json, then submit. Preserve units and policy precedence. Tool errors can be corrected. Do not just describe a solution.'},
                    {'role':'user','content':json.dumps(initial.model_dump())}]
        transcript = []
        result = {'task_id':task_id,'seed':8671,'reward':None,'completed':False,'tokens':0,'actions':0,'error':None}
        episode_start = time.monotonic()
        try:
            while not env.ended and env.state.step_count < 24:
                remaining = min(120-(time.monotonic()-episode_start), TOTAL_SECONDS-(time.monotonic()-started))
                if remaining <= 0: raise TimeoutError('Capped smoke-test wall-time reached; no tuning/retry')
                payload = dict(model=MODEL,messages=messages,tools=[tool],stream=False,think=False,
                               options=dict(num_ctx=12288,num_predict=1536,temperature=0.7,seed=901+env.state.step_count),keep_alive='5m')
                request = urllib.request.Request(BASE+'/api/chat',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=min(60,remaining)) as response: answer=json.load(response)
                result['tokens'] += answer.get('eval_count',0)
                message = answer['message']
                messages.append(message)
                transcript.append({'assistant':message,'done_reason':answer.get('done_reason')})
                calls = message.get('tool_calls',[])
                if not calls: raise ValueError('No executable tool call from local chat parser')
                for call in calls:
                    if env.ended: break
                    function = call['function']
                    if function['name'] != 'office_step': raise ValueError('Unknown tool')
                    args = function['arguments']
                    if isinstance(args,str): args=json.loads(args)
                    observation=env.step(OfficeAction(**args))
                    text=json.dumps(observation.model_dump())
                    messages.append({'role':'tool','tool_name':'office_step','content':text})
                    transcript.append({'action':args,'observation':observation.model_dump()})
                    result['actions']=env.state.step_count
                    print(json.dumps({'task':task_id,'action':env.state.step_count,'operation':args['operation'],'done':observation.done,'reward':observation.reward}),flush=True)
                if result['tokens'] > 6000: raise TimeoutError('Capped generated-token budget reached')
            result.update(reward=env.last_reward,completed=env.ended)
        except Exception as exc:
            result['error']=type(exc).__name__+': '+str(exc)[:200]
            # Do not force-submit an incomplete attempt or label it a solved rollout.
        finally:
            result['elapsed_seconds']=round(time.monotonic()-episode_start,2)
            result['transcript']=transcript
            env.close()
        rows.append(result)
        Path('model-smoke.json').write_text(json.dumps({'model':MODEL,'quantization':'nvfp4 MLX (local proxy, not Arena weights/runner)','cap_seconds':TOTAL_SECONDS,'episodes':rows,'learning_evidence':False},indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='transcript'}),flush=True)
    print('Smoke test complete; no extended calibration.',flush=True)

if __name__=='__main__': main()
