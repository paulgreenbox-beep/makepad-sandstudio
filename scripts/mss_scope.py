"""Derive independent MSS/CWG plan views; never execute source or qualify runtime.

Python 3.11+, standard library only. Input files are hash-pinned planning data.
Historical tests, evidence and the source archive are not edited.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import tomllib
from pathlib import Path, PurePosixPath
import subprocess
import sys

PRODUCT_IDS = {f"A{i:02d}" for i in range(14)}
EXTERNAL_IDS = {f"B{i:02d}" for i in range(8)}
GATE = "MSS-V00"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_GRAPH_ROWS = 256
EQUIVALENT_CHECKS = {
    "T-019", "T-033", "T-036", "T-037", "T-038", "T-039", "T-X10", "T-X13", "T-X14",
}
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
    require(isinstance(raw, bytes) and len(raw) <= MAX_INPUT_BYTES, "planning input too large")
    def invalid_constant(value: str) -> None:
        raise ValueError(f"non-JSON numeric constant: {value}")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=invalid_constant)
        # Also reject overflow-to-infinity and escaped lone surrogate strings.
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except RecursionError as error:
        raise ValueError("planning input too deeply nested") from error
    require(isinstance(value, dict), "planning input must be an object")
    return value


def _source_signature(info: os.stat_result, *, windows_cross_view: bool = False) -> tuple:
    # Windows path stat preserves legacy creation-time ctime, while descriptor
    # fstat may report metadata ChangeTime. Compare their shared birthtime only
    # across views; pre-3.12 Windows retains its original creation-time fallback.
    # Within either view, callers keep the complete ctime stability check.
    timestamp = info.st_ctime_ns
    if windows_cross_view:
        timestamp = getattr(info, "st_birthtime_ns", timestamp)
    identity = (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_size, info.st_mtime_ns, timestamp)
    if windows_cross_view:
        return identity
    # A field used for cross-view identity must also remain stable within each
    # observation view; retain birthtime in addition to the full ctime check.
    return (*identity, getattr(info, "st_birthtime_ns", None))


def read_regular(path: Path) -> bytes:
    """Bounded source read for an operator-owned tree, NOT an OS sandbox.

    Refuses observed links/special files and detects file identity drift. This
    does not promise race-free ancestor traversal against a hostile same-user
    process; run only on a quiescent, owner-controlled checkout/extraction.
    """
    path = path.absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode)
                and not (getattr(info, "st_file_attributes", 0) & 0x400),
                "source link/reparse refused")
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "regular unlinked source required")
    require(before.st_size <= MAX_INPUT_BYTES, "planning input too large")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        cross_view = os.name == "nt"
        require(_source_signature(opened, windows_cross_view=cross_view)
                == _source_signature(before, windows_cross_view=cross_view),
                "source changed before read")
        raw = stream.read(MAX_INPUT_BYTES + 1)
        require(len(raw) <= MAX_INPUT_BYTES, "planning input too large")
        require(_source_signature(os.fstat(stream.fileno())) == _source_signature(opened)
                and _source_signature(path.lstat()) == _source_signature(before),
                "source changed during read")
    return raw


def load_inputs(root: Path, pins: dict) -> dict:
    required = {
        "pr-backlog.json", "invariants.json", "proposed-tests.json",
        "toolkit/operations.raw.json", "toolkit/schema.raw.json",
        "toolkit/scenario-registry.json",
    }
    require(isinstance(pins, dict) and set(pins) == required, "incomplete baseline pins")
    result = {}
    for name, digest in pins.items():
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts, "invalid input path")
        require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                "invalid baseline SHA-256")
        raw = read_regular(root.joinpath(*path.parts))
        require(hashlib.sha256(raw).hexdigest() == digest, f"baseline drift: {name}")
        result[name] = decode(raw)
    return result


def check_graph(rows: list[dict]) -> None:
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_GRAPH_ROWS, "invalid graph size")
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("id"), str)
                and bool(row["id"]) and len(row["id"]) <= 128, "invalid package identity")
        edges = row.get("depends_on")
        require(isinstance(edges, list) and len(edges) <= MAX_GRAPH_ROWS
                and all(isinstance(edge, str) and bool(edge) and len(edge) <= 128 for edge in edges),
                "dependencies must be a bounded list of package IDs")
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
    require(isinstance(paths, list) and len(paths) <= 20_000, "invalid tracked path inventory")
    seen = set()
    for path in paths:
        require(isinstance(path, str) and 0 < len(path) <= 4096, "invalid tracked path")
        require("\\" not in path and ":" not in path and not path.startswith("/"),
                "tracked path must be relative POSIX form")
        parts = path.split("/")
        require(all(part not in ("", ".", "..") and part.rstrip(" .") == part
                    and not any(ord(char) < 32 or ord(char) == 127 for char in part)
                    for part in parts), "noncanonical tracked path")
        lower = [part.casefold() for part in parts]
        require(".git" not in lower, "Git metadata is not product source")
        folded = path.casefold()
        require(folded not in seen, "case-insensitive tracked path collision")
        seen.add(folded)
        forbidden = any(folded.startswith(prefix.casefold()) for prefix in FORBIDDEN)
        forbidden |= "native-check-broker" in lower
        forbidden |= any(part.startswith(("cwg_", "cwg-")) for part in lower[:-1])
        forbidden |= any(lower[i:i + 2] == ["scripts", "codex-issue"]
                         for i in range(len(lower) - 1))
        forbidden |= any(lower[i:i + 2] == ["workflows", "codex-issue.yaml"]
                         for i in range(len(lower) - 1))
        require(not forbidden, f"CWG executable infrastructure must not enter MSS: {path}")


def check_cargo(raw: bytes) -> None:
    """Reject declared CWG package/alias/path/Git dependencies; do not run Cargo."""
    require(len(raw) <= MAX_INPUT_BYTES, "Cargo input too large")
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid Cargo TOML") from error

    def external(value: str) -> bool:
        normalized = value.casefold().replace("_", "-").replace("\\", "/")
        return (normalized == "cwg" or normalized.startswith("cwg-")
                or "chat-worker-github" in normalized or "native-check-broker" in normalized
                or any(part.startswith("cwg-") for part in normalized.split("/")))

    def dependency_table(table: dict) -> None:
        require(isinstance(table, dict), "invalid dependency table")
        for name, value in table.items():
            require(not external(name), "CWG dependency name refused")
            if isinstance(value, dict):
                for field in ("package", "path", "git"):
                    reference = value.get(field)
                    if isinstance(reference, str):
                        require(not external(reference), "CWG dependency alias/source refused")

    def walk(obj: object, depth: int = 0) -> None:
        require(depth <= 64, "Cargo table nesting limit")
        if not isinstance(obj, dict):
            return
        for key, value in obj.items():
            if key in ("dependencies", "dev-dependencies", "build-dependencies", "replace"):
                dependency_table(value)
            elif key == "patch":
                require(isinstance(value, dict), "invalid Cargo patches")
                for table in value.values():
                    dependency_table(table)
            elif key == "workspace" and isinstance(value, dict):
                for field in ("members", "default-members"):
                    members = value.get(field, [])
                    require(isinstance(members, list), "workspace members must be a list")
                    for member in members:
                        require(isinstance(member, str) and not external(member),
                                "CWG workspace member refused")
                walk(value, depth + 1)
            else:
                walk(value, depth + 1)

    walk(data)
    packages = data.get("package", [])
    if isinstance(packages, dict):
        packages = [packages]
    require(isinstance(packages, list), "invalid Cargo package list")
    for package in packages:
        require(isinstance(package, dict) and not external(str(package.get("name", ""))),
                "CWG package refused")
        source = package.get("source", "")
        require(not isinstance(source, str) or not external(source), "CWG lock source refused")


def check_repo(repo: Path) -> None:
    output = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"],
                            check=True, capture_output=True, timeout=15).stdout
    require(len(output) <= 4 * MAX_INPUT_BYTES, "tracked inventory too large")
    paths = [path for path in output.decode("utf-8").split("\0") if path]
    require(bool(paths), "empty tracked source inventory")
    check_paths(paths)
    for path in paths:
        if PurePosixPath(path).name in ("Cargo.toml", "Cargo.lock"):
            check_cargo(read_regular(repo / path))


def derive(inputs: dict, policy: dict) -> dict:
    require(policy.get("schema") == "mss-cwg-separation-v1", "wrong scope schema")
    require(type(policy.get("toolkit_operation_count")) is int
            and policy["toolkit_operation_count"] == 112, "Toolkit scope cannot shrink")
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
    require(isinstance(gate["invariants"], list) and len(gate["invariants"]) == len(MANDATORY)
            and set(gate["invariants"]) == MANDATORY, "native/evidence obligations changed")
    require(gate["implementation_status"] == "PLANNED_NOT_STARTED", "gate not qualified")
    ids = {t["id"] for t in tests}
    checks = gate["equivalent_checks_from"]
    require(isinstance(checks, list) and len(checks) == len(EQUIVALENT_CHECKS)
            and set(checks) == EQUIVALENT_CHECKS and set(checks) <= ids,
            "equivalent native checks cannot shrink or duplicate")
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
        row["depends_on"] = [d for d in row["historical_depends_on"] if d in EXTERNAL_IDS]
        row["external_contract_inputs"] = [d for d in row["historical_depends_on"] if d not in EXTERNAL_IDS]
        row["migration_status"] = "SOURCE_HANDOFF_NOT_RUNTIME_QUALIFICATION"
    check_graph(product)
    check_graph(external)
    require(all(d in PRODUCT_IDS | {GATE} for r in product for d in r["depends_on"]),
            "CWG still blocks MSS")
    return {
        "schema": "mss-independent-plan-view-v1",
        "runtime_acceptance": "NOT_VERIFIED",
        "source_inputs_sha256": copy.deepcopy(policy["source_inputs_sha256"]),
        "toolkit_operation_count": 112,
        "mss_packages": product,
        "cwg_external_handoff": external,
        "preserved_invariants": copy.deepcopy(invariants),
        "preserved_proposed_checks": copy.deepcopy(tests),
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
        policy = decode(read_regular(args.policy))
        result = derive(load_inputs(args.source, policy["source_inputs_sha256"]), policy)
        if args.repo:
            check_repo(args.repo)
        if args.output:
            # Never overwrite a previous report or historical archive.
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        print("PASS: plan projection only; 14 MSS packages + MSS-V00; 8 external CWG packages; 54/68 inventories preserved")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, RecursionError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
