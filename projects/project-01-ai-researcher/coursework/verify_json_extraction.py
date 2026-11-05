"""Reproduce the baseline, regression and boundary checks with no API calls."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_report(name):
    return json.loads((PROJECT_ROOT / "coursework/results" / name).read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_replay(output, extra_args, expected_exit):
    command = [
        sys.executable, "coursework/reproduce_json_extraction.py",
        "--output", f"coursework/results/{output}", "--require-all", *extra_args,
    ]
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    require(result.returncode == expected_exit, f"{output}: unexpected exit {result.returncode}")
    print(f"Verified {output}: exit {expected_exit} (expected).", flush=True)
    return read_report(output)


def main():
    baseline = run_replay("baseline-replay.json", ["--source-revision", "5905034"], 1)
    current = run_replay("after-replay.json", [], 0)
    boundaries = run_replay(
        "boundaries.json", ["--fixture", "coursework/fixtures/json_extraction_boundaries.json"], 0,
    )
    original = read_report("baseline.json")
    fixed = read_report("after.json")
    reports = (original, fixed, baseline, current)
    require(len({report["fixture_sha256"] for report in reports}) == 1, "Regression fixture changed")
    require(len({report["evidence_sha256"] for report in (*reports, boundaries)}) == 1, "Evidence changed")
    require(
        baseline["prepare_validator"]["function_ast_sha256"]
        == current["prepare_validator"]["function_ast_sha256"],
        "Field validation rules changed",
    )
    runner_hash = hashlib.sha256((PROJECT_ROOT / "coursework/reproduce_json_extraction.py").read_bytes()).hexdigest()
    for report in (baseline, current, boundaries):
        require(report["runner_sha256"] == runner_hash, "Replay runner changed during verification")
    for report in (current, boundaries):
        validator = report["prepare_validator"]
        actual_hash = hashlib.sha256((PROJECT_ROOT / validator["path"]).read_bytes()).hexdigest()
        require(actual_hash == validator["source_sha256"], "Validator source changed during verification")
    for index, entry in enumerate(current["results"]):
        old = baseline["results"][index]
        edge = boundaries["results"][index]
        require(old["summary"] == {"total": 10, "passed": 5, "failed": 5}, "Baseline behavior changed")
        require(entry["summary"] == {"total": 10, "passed": 10, "failed": 0}, "Regression failure")
        require(edge["summary"] == {"total": 20, "passed": 20, "failed": 0}, "Boundary failure")
        for replay, snapshot in ((old, original["results"][index]), (entry, fixed["results"][index])):
            require(replay["source"]["path"] == snapshot["source"]["path"], "Entry mismatch")
            require(replay["source"]["function_ast_sha256"] == snapshot["source"]["function_ast_sha256"], "Implementation changed")
            require(
                [(case["id"], case["actual"], case["exception"]) for case in replay["cases"]]
                == [(case["id"], case["actual"], case["exception"]) for case in snapshot["cases"]],
                "Replay differs from the recorded snapshot",
            )
        for result in (entry, edge):
            for source in (result["source"], result["source"]["implementation"]):
                actual_hash = hashlib.sha256((PROJECT_ROOT / source["path"]).read_bytes()).hexdigest()
                require(actual_hash == source["source_sha256"], "Source changed during verification")
        cases = {case["id"]: case for case in edge["cases"]}
        unsupported = cases["title_outside_local_evidence"]
        require(unsupported["prepare_validation"]["accepted"], "Expected shape-only validation")
        require(unsupported["reference_titles_match_local_evidence"] is False, "Expected evidence mismatch")
        require(not cases["missing_required_lists"]["prepare_validation"]["accepted"], "Missing fields should be rejected")
    print("Verified: both entries reproduce 5/10 -> 10/10; 20 boundary expectations each; evidence and implementation checks match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
