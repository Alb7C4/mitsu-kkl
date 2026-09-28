"""JSONL logging: one event file per run plus a shared attempts.jsonl summary."""

import datetime
import json
import time
from pathlib import Path

ATTEMPTS = "attempts.jsonl"


def _wall():
    return datetime.datetime.now().isoformat(timespec="seconds")


class RunLog:
    def __init__(self, logdir, cmd, argv, note=""):
        self.dir = Path(logdir)
        self.dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = self.dir / f"{stamp}_{cmd}.jsonl"
        self.f = open(self.path, "w", encoding="utf-8")
        self.t0 = time.perf_counter()
        self.note = note
        self.attempt = None
        self.ev("run_start", argv=argv, note=note, wall=_wall())

    def ev(self, _ev, t=None, **kw):
        t = time.perf_counter() if t is None else t
        rec = {"ms": round((t - self.t0) * 1000, 2), "ev": _ev}
        if self.attempt is not None:
            rec["a"] = self.attempt
        rec.update(kw)
        self.f.write(json.dumps(rec, default=str) + "\n")

    def begin(self, n, kind, params):
        self.attempt = n
        self.ev("attempt_begin", kind=kind, params=params)

    def end(self, kind, params, result):
        self.ev("attempt_end", kind=kind, result=result)
        rec = {"wall": _wall(), "run": self.path.name, "n": self.attempt, "note": self.note,
               "kind": kind, "params": params, **result}
        with open(self.dir / ATTEMPTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        self.attempt = None
        self.f.flush()

    def close(self):
        self.ev("run_end", wall=_wall())
        self.f.close()
