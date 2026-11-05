"""Replay controlled outputs against the real source functions.

Only the selected function or its shared import is loaded, avoiding unrelated
LLM / Docker imports. This measures extraction, not the complete workflow.
"""

import argparse
import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
SOURCES = (
    "research_agent/run_infer_idea.py",
    "research_agent/run_infer_plan.py",
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_extractor(relative_path):
    """Load an entry point's local function or its actual shared import."""
    source_bytes = (PROJECT_ROOT / relative_path).read_bytes()
    source = source_bytes.decode("utf-8-sig")
    tree = ast.parse(source, filename=relative_path)
    binding = next(
        node for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "extract_json_from_output"
        ) or (
            isinstance(node, ast.ImportFrom)
            and node.module == "research_agent.json_utils"
            and any(alias.name == "extract_json_from_output" for alias in node.names)
        )
    )
    module = ast.Module(body=[binding], type_ignores=[])
    namespace = {"json": json}
    exec(compile(module, relative_path, "exec"), namespace)
    record = {
        "path": relative_path,
        "line": binding.lineno,
        "source_sha256": sha256(source_bytes),
    }
    function = binding
    if isinstance(binding, ast.ImportFrom):
        shared_path = "research_agent/json_utils.py"
        shared_bytes = (PROJECT_ROOT / shared_path).read_bytes()
        shared_tree = ast.parse(shared_bytes.decode("utf-8-sig"), filename=shared_path)
        function = next(
            node for node in shared_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "extract_json_from_output"
        )
        record["implementation"] = {
            "path": shared_path,
            "line": function.lineno,
            "source_sha256": sha256(shared_bytes),
        }
    record["function_ast_sha256"] = sha256(ast.dump(function).encode("utf-8"))
    return namespace["extract_json_from_output"], record


def run_case(extractor, case):
    captured = io.StringIO()
    actual = None
    error = None
    with contextlib.redirect_stdout(captured):
        try:
            actual = extractor(case["output_text"])
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
    return {
        "id": case["id"],
        "description": case["description"],
        "passed": error is None and actual == case["expected"],
        "expected": case["expected"],
        "actual": actual,
        "exception": error,
        "stdout": captured.getvalue(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True,
        help="Explicit result path; use a new filename to retain the baseline.",
    )
    parser.add_argument(
        "--require-all", action="store_true",
        help="Exit 1 if any controlled example fails (baseline intentionally fails).",
    )
    args = parser.parse_args()
    fixture_path = PROJECT_ROOT / "coursework/fixtures/json_extraction_cases.json"
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    evidence_path = PROJECT_ROOT / fixture["provenance"]["evidence_file"]
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    if evidence["source_papers"][0]["reference"] != fixture["provenance"]["evidence_title"]:
        raise ValueError("Local evidence title changed; review the fixture provenance.")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    results = []
    for source_path in SOURCES:
        extractor, source_record = load_extractor(source_path)
        cases = [run_case(extractor, case) for case in fixture["cases"]]
        passed = sum(case["passed"] for case in cases)
        results.append({
            "source": source_record,
            "summary": {"total": len(cases), "passed": passed, "failed": len(cases) - passed},
            "cases": cases,
        })
        print(f"{source_path}: {passed}/{len(cases)} matched expected behavior")
        for case in cases:
            if not case["passed"]:
                reason = case["exception"]["type"] if case["exception"] else "different result"
                print(f"  FAIL {case['id']}: {reason}")
    report = {
        "experiment": "controlled_json_extraction_replay",
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "third_party_dependencies": [],
        },
        "repository_head": revision,
        "runner_sha256": sha256(Path(__file__).read_bytes()),
        "provenance": fixture["provenance"],
        "fixture_sha256": sha256(fixture_bytes),
        "evidence_sha256": sha256(evidence_bytes),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"Saved {args.output.as_posix()}")
    if args.require_all and any(result["summary"]["failed"] for result in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
