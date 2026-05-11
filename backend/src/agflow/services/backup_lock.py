from __future__ import annotations

import asyncio

# Lock global pour sérialiser les opérations longues (dump, push).
# Acquis par local_backups_service et remote_backup_pusher.
backup_lock: asyncio.Lock = asyncio.Lock()
