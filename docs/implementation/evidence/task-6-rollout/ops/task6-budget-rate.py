"""Revise future conservative reservation rates; never reset previous reservations."""
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
path=Path('/tmp/task6-live-smoke-01/budget.json')
with path.open('r+') as handle:
    fcntl.flock(handle,fcntl.LOCK_EX)
    data=json.load(handle)
    assert data['limit_cny']=='100' and set(data['models'])=={'qwen3.7-plus','deepseek-v4-flash'}
    before={'at':datetime.now(timezone.utc).isoformat(),'requests':data['requests'],
            'reserved_cny':data['reserved_cny'],'previous_models':data['models'],
            'reason':'Future reserve rates 3/12 CNY per million, above verified 2/8 peak list rates; input bound below 65536 bytes plus framing, below Qwen 256k tier. Past reserves retained.'}
    data['rate_revisions']=[*data.get('rate_revisions',[]),before]
    data['models']={k:{**v,'input_per_million':'3','output_per_million':'12'} for k,v in data['models'].items()}
    handle.seek(0);json.dump(data,handle);handle.truncate();handle.flush();os.fsync(handle.fileno())
print(json.dumps({'limit_cny':data['limit_cny'],'reserved_cny':data['reserved_cny'],'requests':data['requests'],'future_rates':'3/12 CNY per million'}))
