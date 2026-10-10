"""Local-only MCP fault fixture. Never connects to an external service."""
import asyncio
import json
import sys
from mcp.server.fastmcp import FastMCP

server = FastMCP('recovery-faults', host='127.0.0.1', port=int(sys.argv[1]), log_level='ERROR')
writes = {}
calls = {}


@server.tool()
async def write_once(request_id: str) -> str:
    calls[request_id] = calls.get(request_id, 0) + 1
    if request_id not in writes:
        writes[request_id] = len(writes) + 1
        await asyncio.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 3)  # Commit precedes the lost/timed-out response.
    return json.dumps({'receipt': writes[request_id]})


@server.tool()
async def stats() -> str:
    return json.dumps({'writes': len(writes), 'calls': sum(calls.values()), 'keys': list(writes)})


if __name__ == '__main__':
    server.run(transport='streamable-http')
