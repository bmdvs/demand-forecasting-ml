"""Summarize a pipeline update from its event log: duration, datasets and expectation results.

Reads the update's events with the Databricks CLI and prints, per dataset, the rows written and
each expectation's passed and failed record counts, then the update's start, end and state.

Usage:
  python src/tests/parity/pipeline_update.py --profile PROFILE PIPELINE_ID UPDATE_ID [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def events(profile: str, pipeline: str, update: str) -> list[dict]:
    """Every event of one update, from the REST endpoint (the CLI listing omits the details)."""
    out, token = [], None
    while True:
        q = "max_results=250" + (f"&page_token={token}" if token else "")
        r = subprocess.run(["databricks", "--profile", profile, "api", "get",
                            f"/api/2.0/pipelines/{pipeline}/events?{q}"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip())
        d = json.loads(r.stdout)
        page = d.get("events", [])
        out += [e for e in page if e.get("origin", {}).get("update_id") == update]
        token = d.get("next_page_token")
        # events come newest first; stop once the page is older than the update's creation
        if not token or any(e.get("event_type") == "create_update"
                            and e.get("origin", {}).get("update_id") == update for e in page):
            return out


def summarize(ev: list[dict]) -> dict:
    flows: dict[str, dict] = {}
    states = []
    for e in ev:
        d = e.get("details", {})
        fp = d.get("flow_progress")
        name = e.get("origin", {}).get("flow_name") or e.get("origin", {}).get("dataset_name")
        if fp and name:
            f = flows.setdefault(name, {"status": None, "rows": None, "expectations": {}})
            if fp.get("status"):
                f["status"] = fp["status"] if f["status"] in (None, "QUEUED", "PLANNING", "STARTING", "RUNNING") else f["status"]
            m = fp.get("metrics", {})
            if m.get("num_output_rows") is not None:
                f["rows"] = m["num_output_rows"]
            for x in fp.get("data_quality", {}).get("expectations", []) or []:
                f["expectations"][x["name"]] = {"passed": x.get("passed_records"), "failed": x.get("failed_records")}
        up = d.get("update_progress")
        if up:
            states.append((e["timestamp"], up["state"]))
    states.sort()
    return {"flows": flows, "states": states}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT"))
    p.add_argument("pipeline")
    p.add_argument("update")
    p.add_argument("--json", type=Path)
    a = p.parse_args()
    s = summarize(events(a.profile, a.pipeline, a.update))
    if a.json:
        a.json.write_text(json.dumps(s, indent=1))
    for name, f in sorted(s["flows"].items()):
        exp = "; ".join(f"{k} passed {v['passed']} failed {v['failed']}" for k, v in f["expectations"].items())
        print(f"{name:60s} {f['status'] or '':10s} {f['rows'] if f['rows'] is not None else '':>9} {exp}")
    for t, st in s["states"]:
        print(t, st)


if __name__ == "__main__":
    main()
