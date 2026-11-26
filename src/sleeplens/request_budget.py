"""Persistent, single-host request quota and in-flight admission control."""

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4


class BudgetError(RuntimeError):
    pass


class RequestBudget:
    def __init__(self, path, *, request_limit=200, max_concurrent=2):
        self.path = Path(path)
        self.request_limit = request_limit
        self.max_concurrent = max_concurrent
        if type(request_limit) is not int or request_limit < 0 or type(max_concurrent) is not int or max_concurrent < 1:
            raise ValueError("Request limit must be a nonnegative integer (0 means unlimited); concurrency must be positive.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, started REAL NOT NULL, finished REAL, active INTEGER NOT NULL, status TEXT NOT NULL)")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=1.0, isolation_level=None)

    def reserve(self):
        try:
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                used, active = db.execute("SELECT COUNT(*), COALESCE(SUM(active),0) FROM requests").fetchone()
                if self.request_limit and used >= self.request_limit:
                    raise BudgetError("服务累计调用额度已用尽，请联系管理员。 Shared request limit reached.")
                if active >= self.max_concurrent:
                    raise BudgetError("当前请求较多，请稍后再试。 Shared concurrency limit reached.")
                reservation = uuid4().hex
                db.execute("INSERT INTO requests VALUES (?, ?, NULL, 1, 'reserved')", (reservation, time.time()))
                db.execute("COMMIT")
                return reservation
        except sqlite3.Error:
            raise BudgetError("服务调用账本暂不可用，未发送模型请求。") from None

    def finish(self, reservation, status):
        # An attempt consumes quota even on timeout/error; no automatic refunds.
        try:
            with closing(self._connect()) as db:
                db.execute("UPDATE requests SET active=0, finished=?, status=? WHERE id=?", (time.time(), status, reservation))
        except sqlite3.Error:
            # Fail closed: retain an in-flight slot if release could not persist.
            return False
        return True

    def status(self):
        with closing(self._connect()) as db:
            used, active = db.execute("SELECT COUNT(*), COALESCE(SUM(active),0) FROM requests").fetchone()
        return {"reserved_requests": used, "active_requests": active,
                "request_limit": self.request_limit,
                "remaining_requests": max(0, self.request_limit-used) if self.request_limit else None,
                "max_concurrent": self.max_concurrent}

    def clear_inflight_after_server_stopped(self):
        with closing(self._connect()) as db:
            db.execute("UPDATE requests SET active=0, status='operator_released_after_stop', finished=? WHERE active=1", (time.time(),))


def main():
    import argparse
    import json
    from sleeplens.config import load_settings
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear-inflight", action="store_true")
    parser.add_argument("--server-stopped", action="store_true")
    args = parser.parse_args()
    cfg = load_settings()
    budget = RequestBudget(cfg.budget_db, request_limit=cfg.request_limit, max_concurrent=cfg.max_concurrent)
    if args.clear_inflight:
        if not args.server_stopped:
            parser.error("Stop the server first, then explicitly pass --server-stopped. Total quota is never reset.")
        budget.clear_inflight_after_server_stopped()
    print(json.dumps(budget.status()))


if __name__ == "__main__":
    main()
