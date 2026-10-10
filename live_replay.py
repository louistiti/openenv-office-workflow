"""All-task network verification using independently calculated SQL actions."""
import argparse
import asyncio
import json
from pathlib import Path
from websockets.asyncio.client import connect
from tasks import TASK_IDS, make_task, csv_text
from oracle import QUERIES, summary_sql

async def send(sock, kind, data):
    await sock.send(json.dumps({'type':kind,'data':data}))
    response = json.loads(await asyncio.wait_for(sock.recv(),timeout=20))
    assert response['type'] == 'observation', response
    return response['data']

async def main(url, output):
    records = []
    for seed in [713, 2718]:
        for ident in TASK_IDS:
            async with connect(url.replace('http','ws',1)+'/ws') as sock:
                task = make_task(ident,seed)
                initial = await send(sock,'reset',dict(task_id=ident,seed=seed))
                assert initial['observation']['message'] == task.instructions
                floor = await send(sock,'step',dict(operation='submit'))
                assert floor['done'] and floor['reward']==0
                await send(sock,'reset',dict(task_id=ident,seed=seed))
                family = ident.split('-')[0]
                result = await send(sock,'step',dict(operation='query',sql=QUERIES[family]))
                rows = json.loads(result['observation']['message'])['rows']
                assert rows == task.rows
                result = await send(sock,'step',dict(operation='query',sql=summary_sql(family)))
                summary = json.loads(result['observation']['message'])['rows'][0]
                assert summary == task.summary
                for path,content in [('report.csv',csv_text(rows,task.columns)),('summary.json',json.dumps(summary))]:
                    result = await send(sock,'step',dict(operation='write',path=path,content=content))
                    assert not result['done'] and result['reward']==0
                terminal = await send(sock,'step',dict(operation='submit'))
                assert terminal['done'] and terminal['reward']==1,terminal
                records.append(dict(task_id=ident,seed=seed,reward=terminal['reward'],steps=5))
    Path(output).write_text(json.dumps(dict(transport='network_websocket',episodes=len(records),all_passed=True,model_rollouts=0,rows=records),indent=2)+'\n')
    print(json.dumps(dict(episodes=len(records),all_passed=True)))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8767')
    parser.add_argument('--output',default='live-replay.json')
    args=parser.parse_args()
    asyncio.run(main(args.url,args.output))
