from datetime import datetime, timezone
from typing import Optional

def iso_from_timestamp(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return (
            datetime.fromtimestamp(ts, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except Exception:
        return None
