"""Benchmark harness (Week 7): collects raw latency measurements into JSON Lines.

Target system (stand-in for the Task 2 function -- replace `resolve_*` with your own code):
    a request resolver that looks up a *batch* of keys in a catalog.
      * baseline : linear scan over a list of (key, value) pairs     -> O(N) per request
      * proposed : hash index (dict)                                  -> O(1) per request

Design rules that keep the data "clean":
  * Measurement isolation: only the target call sits between two perf_counter_ns() stamps.
    Workload generation happens BEFORE and JSONL writing happens AFTER all runs (no I/O in the timed region).
  * Warm-up: the first `warmup_runs` repetitions of every (variant, load) are logged with phase="warmup".
  * Paired design: baseline and proposed receive the *same* batch in the same repetition.
  * Interleaving: all (variant, load) cells are interleaved inside every repetition, so slow drifts of the machine
    (thermal, background load) hit all cells equally instead of biasing one of them.
  * Errors are never dropped: they are logged with status="error" and an error_type (guardrail metric).

Run:  python -m src.benchmark --config config.yaml
"""
from __future__ import annotations

import argparse
import gc
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import yaml


# ----------------------------------------------------------------------------- target system
def build_catalog(n: int, seed: int):
    """Catalog of n records. Keys are ordered by popularity rank (item-00000 = most popular)
    but stored in a random order inside the list, so that position != popularity."""
    keys_by_rank = [f"item-{i:05d}" for i in range(n)]
    perm = np.random.default_rng(seed).permutation(n)
    entries = [(keys_by_rank[i], i) for i in perm]          # baseline structure: list of tuples
    index = dict(entries)                                    # proposed structure: hash index
    return keys_by_rank, entries, index


def _check_deadline(start_ns: int, deadline_ns: int) -> None:
    if time.perf_counter_ns() - start_ns > deadline_ns:
        raise TimeoutError("batch deadline exceeded")


def resolve_baseline(batch, entries, deadline_ns: int) -> int:
    start = time.perf_counter_ns()
    total = 0
    for i, key in enumerate(batch):
        if not key:
            raise ValueError("empty key")
        for k, v in entries:                                  # O(N) linear scan
            if k == key:
                total += v
                break
        if i & 15 == 15:
            _check_deadline(start, deadline_ns)
    return total


def resolve_proposed(batch, index, deadline_ns: int) -> int:
    start = time.perf_counter_ns()
    total = 0
    get = index.get
    for i, key in enumerate(batch):
        if not key:
            raise ValueError("empty key")
        total += get(key, 0)                                  # O(1) hash lookup
        if i & 15 == 15:
            _check_deadline(start, deadline_ns)
    return total


# ----------------------------------------------------------------------------- synthetic workload
def make_batch(rng: np.random.Generator, size: int, cfg: dict, keys_by_rank: list[str]) -> list[str]:
    """Zipf-distributed key popularity + edge cases (NOT uniform random.randint -- see Week 7, Block 2)."""
    n = len(keys_by_rank)
    ranks = np.empty(0, dtype=np.int64)
    while ranks.size < size:                                  # rejection: keep ranks inside the catalog
        draw = rng.zipf(cfg["zipf_a"], size=size * 2)
        ranks = np.concatenate([ranks, draw[draw <= n]])
    batch = [keys_by_rank[r - 1] for r in ranks[:size]]

    for i in np.flatnonzero(rng.random(size) < cfg["p_edge_request"]):   # valid but nasty requests
        kind = int(rng.integers(3))
        if kind == 0:
            batch[i] = f"missing-{i}"                         # cache miss: baseline scans the whole list
        elif kind == 1:
            batch[i] = "A" * int(cfg["huge_key_len"]) + str(i)  # gigantic string
        else:
            batch[i] = f"ключ-🔑-{i}"                          # non-ASCII characters
    if rng.random() < cfg["p_malformed_run"]:                 # one malformed request -> exception
        batch[int(rng.integers(size))] = ""
    return batch


# ----------------------------------------------------------------------------- measurement
def timed_call(fn, *args):
    """Return (latency_ms, status, error_type). The ONLY thing inside the stopwatch is fn(*args)."""
    gc.collect()
    gc.disable()
    status, etype = "ok", None
    t0 = time.perf_counter_ns()
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 - every failure must be logged, never swallowed silently
        status, etype = "error", type(exc).__name__
    t1 = time.perf_counter_ns()
    gc.enable()
    return (t1 - t0) / 1e6, status, etype


def collect_metadata(cfg: dict) -> dict:
    def cpu_model() -> str:
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
        return platform.processor() or "unknown"

    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / 2**30, 2)
        cores = psutil.cpu_count(logical=False), psutil.cpu_count(logical=True)
    except ImportError:
        ram_gb, cores = None, (None, None)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        commit = None
    return {
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "os": platform.platform(),
        "cpu_model": cpu_model(),
        "cpu_cores_physical_logical": cores,
        "ram_gb": ram_gb,
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "git_commit": commit,
        "config": cfg,
    }


def run(cfg: dict) -> list[dict]:
    keys_by_rank, entries, index = build_catalog(cfg["catalog_size"], cfg["seed"])
    deadline_ns = int(cfg["deadline_ms"] * 1e6)
    variants = {
        "baseline": (resolve_baseline, entries),
        "proposed": (resolve_proposed, index),
    }
    loads = list(cfg["loads"])
    total_reps = cfg["warmup_runs"] + cfg["benchmark_runs"]
    order_rng = np.random.default_rng(cfg["seed"] + 1)
    records: list[dict] = []                                  # kept in memory: no I/O during measurement

    for rep in range(total_reps):
        phase = "warmup" if rep < cfg["warmup_runs"] else "benchmark"
        for load in order_rng.permutation(loads):
            load = int(load)
            # same batch for both variants in this (load, rep): paired design
            batch = make_batch(np.random.default_rng([cfg["seed"], load, rep]), load, cfg, keys_by_rank)
            for name in order_rng.permutation(list(variants)):
                fn, structure = variants[str(name)]
                latency_ms, status, etype = timed_call(fn, batch, structure, deadline_ns)
                records.append({
                    "ts_us": time.time_ns() // 1000,
                    "phase": phase,
                    "variant": str(name),
                    "load": load,                              # requests per batch
                    "rep": rep,
                    "latency_ms": round(latency_ms, 6),
                    "status": status,
                    "error_type": etype,
                })
    return records


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())

    meta = collect_metadata(cfg)
    records = run(cfg)

    out = Path(cfg["output_raw"])                             # I/O happens only now, after all timing is done
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    Path(cfg["output_meta"]).write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"wrote {len(records)} records -> {out}")


if __name__ == "__main__":
    main()
