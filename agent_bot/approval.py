import asyncio
from dataclasses import dataclass, field
import uuid

@dataclass
class ApprovalRequest:
    action: str
    reason: str
    approval_type: str  # "confirm" | "secret_input"
    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: str | None = None  # "approved" | "rejected" | secret value

# Global approval queue
# key: unique request_id (uuid4 short)
# value: ApprovalRequest
pending: dict[str, ApprovalRequest] = {}

async def wait_for_approval(request_id: str, timeout: int = 300) -> str | None:
    if request_id not in pending:
        return None
    req = pending[request_id]
    try:
        await asyncio.wait_for(req.event.wait(), timeout=timeout)
        return req.result
    except asyncio.TimeoutError:
        return None
    finally:
        pending.pop(request_id, None)
