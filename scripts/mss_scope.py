"""Derive independent MSS/CWG plan views; never execute source or qualify runtime.

Python 3.11+, standard library only. Input files are hash-pinned planning data.
Historical tests, evidence and the source archive are not edited.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

PRODUCT_IDS = {f"A{i:02d}" for i in range(14)}
EXTERNAL_IDS = {f"B{i:02d}" for i in range(8)}
GATE = "MSS-V00"
MANDATORY = {
    "INV-EVIDENCE-01", "INV-EVIDENCE-02", "INV-EVIDENCE-03", "INV-TEST-01",
    "INV-FS-01", "INV-NET-01", "INV-EXEC-01", "INV-SOURCE-01", "INV-CI-01",
    "INV-RELEASE-01",
}
FORBIDDEN = (
    "native-check-broker/", "scripts/codex-issue/", "CWG_",
    ".github/workflows/codex-issue.yml", ".github/codex-issue-policy.json",
    ".github/prompts/codex-issue.md",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decode(raw: bytes) -> dict:
    require(len(raw) <= 2 * 1024 * 1024, "planning input too large")
    value = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(value, dict), "planning input must be an object")
    return value


def load_inputs(root: Path, pins: dict) -> dict:
    required = {
        "pr-backlog.json", "invariants.json", "proposed-tests.json",
        "toolkit/operations.raw.json", "toolkit/schema.raw.json",
        "toolkit/scenario-registry.json",
    }
    require(set(pins) == required, "incomplete baseline pins")
    result = {}
    for name, digest in pins.items():
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts, "invalid input path")
        raw = root.joinpath(*path.parts).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == digest, f"baseline drift: {name}")
        result[name] = decode(raw)
    return result


def check_graph(rows: list[dict]) -> None:
    ids = [row["id"] for row in rows]
    require(len(ids) == len(set(ids)), "duplicate package")
    graph = {row["id"]: row["depends_on"] for row in rows}
    visiting, visited = set(), set()

    def visit(key: str) -> None:
        require(key in graph, f"foreign or unknown dependency: {key}")
        require(key not in visiting, f"dependency cycle: {key}")
        if key in visited:
            return
        visiting.add(key)
        require(len(graph[key]) == len(set(graph[key])), "duplicate dependency")
        for parent in graph[key]:
            visit(parent)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)


def check_paths(paths: list[str]) -> None:
    for path in paths:
        require(not any(path.casefold().startswith(p.casefold()) for p in FORBIDDEN),
                f"CWG executable infrastructure must not enter MSS: {path}")


def derive(inputs: dict, policy: dict) -> dict:
    require(policy.get("schema") == "mss-cwg-separation-v1", "wrong scope schema")
    require(policy.get("toolkit_operation_count") == 112, "Toolkit scope cannot shrink")
    require(policy.get("runtime_acceptance") == "NOT_VERIFIED", "plan is not acceptance")
    rows = inputs["pr-backlog.json"]["backlog"]
    check_graph(rows)
    require({r["id"] for r in rows} == PRODUCT_IDS | EXTERNAL_IDS, "baseline package drift")
    invariants = inputs["invariants.json"]["invariants"]
    tests = inputs["proposed-tests.json"]["tests"]
    require(len(invariants) == 54 and len(tests) == 68, "baseline inventory drift")
    require(len({x["id"] for x in invariants}) == 54, "duplicate invariant")
    require(len({x["id"] for x in tests}) == 68, "duplicate check")
    require(len(inputs["toolkit/operations.raw.json"]["operations"]) == 112,
            "Toolkit operation inventory drift")
    require(MANDATORY <= {x["id"] for x in invariants}, "missing native obligation")
    gate = copy.deepcopy(policy["independent_verification_gate"])
    require(gate["id"] == GATE and gate["depends_on"] == ["A02"], "invalid native gate")
    require(set(gate["invariants"]) == MANDATORY, "native/evidence obligations changed")
    require(gate["implementation_status"] == "PLANNED_NOT_STARTED", "gate not qualified")
    ids = {t["id"] for t in tests}
    require(set(gate["equivalent_checks_from"]) <= ids, "missing equivalent-check source")
    product = [copy.deepcopy(r) for r in rows if r["id"] in PRODUCT_IDS]
    external = [copy.deepcopy(r) for r in rows if r["id"] in EXTERNAL_IDS]
    for row in product:
        if row["id"] == "A02":
            row["files"] = [p.replace("disabled до B06", "disabled до MSS-V00") for p in row["files"]]
            row["merge_gate"] = "Document/validator review; automated untrusted-code execution requires MSS-V00, not CWG."
        if row["id"] == "A13":
            require(row["depends_on"] == ["A09", "A12", "B06"], "unexpected final-gate inputs")
            row["depends_on"] = ["A09", "A12", GATE]
        # Preserve original test lists and all semantic acceptance assertions.
    product.append(gate)
    for row in external:
        row["owner_repository"] = policy["cwg_repository"]
        row["historical_depends_on"] = row["depends_on"][:]
        row["depends_on"] = [d for d in row["depends_on"] if d in EXTERNAL_IDS]
        row["external_contract_inputs"] = [d for d in row["historical_depends_on"] if d not in EXTERNAL_IDS]
        row["migration_status"] = "SOURCE_HANDOFF_NOT_RUNTIME_QUALIFICATION"
    check_graph(product)
    check_graph(external)
    require(all(d in PRODUCT_IDS | {GATE} for r in product for d in r["depends_on"]),
            "CWG still blocks MSS")
    return {
        "schema": "mss-independent-plan-view-v1",
        "runtime_acceptance": "NOT_VERIFIED",
        "source_inputs_sha256": policy["source_inputs_sha256"],
        "toolkit_operation_count": 112,
        "mss_packages": product,
        "cwg_external_handoff": external,
        "preserved_invariants": invariants,
        "preserved_proposed_checks": tests,
        "note": "Historical target_pr fields remain provenance, not new MSS dependencies. No PASS transferred.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--policy", type=Path,
                        default=Path(__file__).resolve().parents[1] / "doc/plans/mss-scope-v2.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repo", type=Path, help="also check tracked paths of this checkout")
    args = parser.parse_args()
    try:
        policy = decode(args.policy.read_bytes())
        result = derive(load_inputs(args.source, policy["source_inputs_sha256"]), policy)
        if args.repo:
            paths = subprocess.run(["git", "-C", str(args.repo), "ls-files", "-z"],
                                   check=True, capture_output=True).stdout.decode().split("\0")
            check_paths([p for p in paths if p])
        if args.output:
            # Never overwrite a previous report or historical archive.
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        print("PASS: plan projection only; 14 MSS packages + MSS-V00; 8 external CWG packages; 54/68 inventories preserved")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
