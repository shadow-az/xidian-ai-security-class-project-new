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


def read_source(relative_path, source_revision=None):
    if source_revision is None:
        return (PROJECT_ROOT / relative_path).read_bytes()
    prefix = subprocess.run(
        ["git", "rev-parse", "--show-prefix"], cwd=PROJECT_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return subprocess.run(
        ["git", "show", f"{source_revision}:{prefix}{relative_path}"],
        cwd=PROJECT_ROOT, capture_output=True, check=True,
    ).stdout


def load_extractor(relative_path, source_revision=None):
    """Load the current binding or a selected Git revision, without checkout."""
    source_bytes = read_source(relative_path, source_revision)
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
    namespace = {"json": json}
    record = {
        "path": relative_path,
        "line": binding.lineno,
        "source_sha256": sha256(source_bytes),
    }
    function = binding
    if isinstance(binding, ast.ImportFrom):
        shared_path = "research_agent/json_utils.py"
        shared_bytes = read_source(shared_path, source_revision)
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
    # Current sources execute the actual import. Historical sources execute the
    # function from that same revision, so later edits cannot affect the replay.
    loaded_node = function if source_revision else binding
    module = ast.Module(body=[loaded_node], type_ignores=[])
    exec(compile(module, relative_path, "exec"), namespace)
    record["function_ast_sha256"] = sha256(ast.dump(function).encode("utf-8"))
    return namespace["extract_json_from_output"], record


def load_prepare_validator(source_revision=None):
    relative_path = "research_agent/inno/workflow/flowcache.py"
    source_bytes = read_source(relative_path, source_revision)
    tree = ast.parse(source_bytes.decode("utf-8-sig"), filename=relative_path)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "validate_prepare_result"
    )
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), relative_path, "exec"), namespace)
    return namespace[function.name], {
        "path": relative_path,
        "line": function.lineno,
        "source_sha256": sha256(source_bytes),
        "function_ast_sha256": sha256(ast.dump(function).encode("utf-8")),
    }


def run_case(extractor, case, prepare_validator, evidence_titles):
    captured = io.StringIO()
    actual = None
    error = None
    with contextlib.redirect_stdout(captured):
        try:
            actual = extractor(case["output_text"])
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
    expected_error = case.get("expected_exception")
    if expected_error:
        passed = error is not None and error["type"] == expected_error
    else:
        passed = error is None and actual == case["expected"]
    validation_error = None
    try:
        prepare_validator(actual)
        prepare_accepted = True
    except ValueError as exc:
        prepare_accepted = False
        validation_error = str(exc)
    papers = actual.get("reference_papers") if isinstance(actual, dict) else None
    titles_match = None
    if isinstance(papers, list) and papers and all(isinstance(paper, str) for paper in papers):
        titles_match = all(paper in evidence_titles for paper in papers)
    if "expected_prepare_accepted" in case:
        passed = passed and prepare_accepted == case["expected_prepare_accepted"]
    if "expected_titles_match" in case:
        passed = passed and titles_match == case["expected_titles_match"]
    return {
        "id": case["id"],
        "description": case["description"],
        "category": case.get("category", "regression"),
        "passed": passed,
        "expected": case.get("expected"),
        "expected_exception": expected_error,
        "actual": actual,
        "exception": error,
        "stdout": captured.getvalue(),
        "prepare_validation": {"accepted": prepare_accepted, "error": validation_error},
        "reference_titles_match_local_evidence": titles_match,
        "expected_prepare_accepted": case.get("expected_prepare_accepted"),
        "expected_titles_match": case.get("expected_titles_match"),
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
    parser.add_argument(
        "--fixture", type=Path,
        default=Path("coursework/fixtures/json_extraction_cases.json"),
        help="Fixture path relative to the project root, or an absolute path.",
    )
    parser.add_argument(
        "--source-revision",
        help="Read parser and validator sources from a local Git commit, without checkout.",
    )
    args = parser.parse_args()
    source_revision = None
    if args.source_revision:
        source_revision = subprocess.run(
            ["git", "rev-parse", "--verify", "--end-of-options", f"{args.source_revision}^{{commit}}"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    fixture_path = PROJECT_ROOT / args.fixture
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    evidence_path = PROJECT_ROOT / fixture["provenance"]["evidence_file"]
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    if evidence["source_papers"][0]["reference"] != fixture["provenance"]["evidence_title"]:
        raise ValueError("Local evidence title changed; review the fixture provenance.")
    evidence_titles = {paper["reference"] for paper in evidence["source_papers"]}
    prepare_validator, validator_record = load_prepare_validator(source_revision)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    results = []
    for source_path in SOURCES:
        extractor, source_record = load_extractor(source_path, source_revision)
        cases = [run_case(extractor, case, prepare_validator, evidence_titles) for case in fixture["cases"]]
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
        "source_revision": source_revision or "working_tree",
        "fixture": args.fixture.as_posix(),
        "prepare_validator": validator_record,
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
