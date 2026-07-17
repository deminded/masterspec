from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "graph-adapter.py"
GRAPH_BUILD_SCRIPT = Path(__file__).parents[1] / "graph-build.sh"

# Small synthetic graph exercising every relation class the adapter's edge policy cares about:
# contains/method (structural, request-only), the 5 EXTRACTED_CORE relations (traversed by
# default), and two INFERRED classes (denied by default, allowed + marked with --include-inferred).
# Every link carries `confidence`, matching live graphify 0.9.17's actual shape, but the VALUE on
# each link matches exactly what its relation name used to mean pre-B1 — this fixture is a
# regression net for the OLD (name-only) tests, not the B1 confidence-first tests themselves,
# which get their own fixture below (build_confidence_fixture) so a fixture change here can never
# quietly widen or narrow what those older assertions are checking.
NODES = [
    {"id": "a", "label": "", "source_file": "a.py", "file_type": "code"},
    {"id": "a_foo", "label": "Foo", "source_file": "a.py", "file_type": "code"},
    {"id": "a_foo_bar", "label": "Foo.bar", "source_file": "a.py", "file_type": "code"},
    {"id": "b", "label": "", "source_file": "b.py", "file_type": "code"},
    {"id": "b_child", "label": "Child", "source_file": "b.py", "file_type": "code"},
    {"id": "c_util", "label": "Util", "source_file": "c.py", "file_type": "code"},
    {"id": "sim_thing", "label": "SimThing", "source_file": "d.py", "file_type": "code"},
]
LINKS = [
    {"source": "a", "target": "a_foo", "relation": "contains", "weight": 1.0, "confidence": "EXTRACTED"},
    {"source": "a_foo", "target": "a_foo_bar", "relation": "method", "weight": 1.0, "confidence": "EXTRACTED"},
    {"source": "b", "target": "a", "relation": "imports", "weight": 1.0, "confidence": "EXTRACTED"},
    {"source": "a_foo", "target": "b_child", "relation": "calls", "weight": 1.0, "confidence": "EXTRACTED"},
    {"source": "a_foo", "target": "c_util", "relation": "references", "weight": 1.0, "confidence": "EXTRACTED"},
    {"source": "b_child", "target": "a_foo", "relation": "inherits", "weight": 1.0, "confidence": "EXTRACTED"},
    {"source": "c_util", "target": "a_foo", "relation": "implements", "weight": 1.0, "confidence": "EXTRACTED"},
    {"source": "a_foo", "target": "sim_thing", "relation": "semantically_similar_to", "weight": 0.42, "confidence": "INFERRED"},
    {"source": "c_util", "target": "sim_thing", "relation": "part_of", "weight": 0.3, "confidence": "INFERRED"},
]


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def init_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    git("init", "-q", cwd=root)
    git("config", "user.email", "test@example.com", cwd=root)
    git("config", "user.name", "Test", cwd=root)
    # graphify-out/ is gitignored per the design (ROADMAP: "Граф не коммитится") — without this,
    # every fixture that later drops graph.json/graph.meta.json in there would show up as an
    # untracked path under `git status --porcelain`, permanently tripping the live-dirty check
    # (B2) regardless of whether the tracked source was actually touched.
    (root / ".gitignore").write_text("graphify-out/\n", encoding="utf-8")
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    git("commit", "-q", "-m", "init", cwd=root)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_again(root: Path) -> None:
    """Advances HEAD past whatever a manifest recorded — the standard way to manufacture staleness."""
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    git("commit", "-q", "-m", "second", cwd=root)


def build_fixture(
    tmp_path: Path,
    *,
    with_graph: bool = True,
    with_manifest: bool = True,
    dirty: bool = False,
    schema_version: int = 1,
    digest: str | None = None,
    partial: bool = False,
) -> tuple[Path, Path, str]:
    """A repo + graph.json + graph.meta.json that check() accepts as-is; every kwarg pokes one
    hole that the norm classifies as a deviation, so negative tests just set one and assert."""
    root = tmp_path / "repo"
    commit = init_repo(root)
    graph_path = root / "graphify-out" / "graph.json"
    raw = b""
    if with_graph:
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps({"nodes": NODES, "links": LINKS}).encode()
        graph_path.write_bytes(raw)
    if with_manifest:
        manifest = {
            "graphify_version": "0.9.17",
            "schema_version": schema_version,
            "revisions": [{"root": str(root), "commit": commit, "dirty": dirty}],
            "roots": [str(root)],
            "excludes": [],
            "digest": digest if digest is not None else hashlib.sha256(raw).hexdigest(),
            "files_seen": {".py": 4},
            "files_parsed": {".py": 4},
            "partial": partial,
        }
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        (graph_path.parent / "graph.meta.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root, graph_path, commit


def write_pair(root: Path, commit: str, nodes: list[dict], links: list[dict], **manifest_overrides) -> Path:
    """Lower-level fixture builder for tests that need a specific node/link/manifest shape the
    generic build_fixture() kwargs don't cover (multi-repo, external nodes, malformed manifests)."""
    graph_path = root / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({"nodes": nodes, "links": links}).encode()
    graph_path.write_bytes(raw)
    manifest = {
        "graphify_version": "0.9.17",
        "schema_version": 1,
        "revisions": [{"root": str(root), "commit": commit, "dirty": False}],
        "roots": [str(root)],
        "excludes": [],
        "digest": hashlib.sha256(raw).hexdigest(),
        "files_seen": {".py": len(nodes)},
        "files_parsed": {".py": len(nodes)},
        "partial": False,
    }
    manifest.update(manifest_overrides)
    (graph_path.parent / "graph.meta.json").write_text(json.dumps(manifest), encoding="utf-8")
    return graph_path


def build_confidence_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """A second, independent (graph, manifest) pair whose links exercise confidence-first gating
    (B1/M11) beyond what the base fixture's name-derived confidence values cover: a relation
    OUTSIDE every known dictionary but confidence=EXTRACTED (imports_from — live graphify 0.9.17,
    must pass through unmarked), the same shape but confidence=INFERRED (uses — must need
    --include-inferred and come back tagged), a known EXTRACTED_CORE name overridden by
    confidence=INFERRED (proving confidence wins over the name fallback, not just supplements it),
    and a relation with no confidence field and no dictionary match at all (conservative fallback:
    treated as inferred per B1's third clause)."""
    root = tmp_path / "confrepo"
    commit = init_repo(root)
    nodes = [
        {"id": "p", "label": "", "source_file": "p.py", "file_type": "code"},
        {"id": "q", "label": "", "source_file": "q.py", "file_type": "code"},
        {"id": "r", "label": "", "source_file": "r.py", "file_type": "code"},
        {"id": "s", "label": "", "source_file": "s.py", "file_type": "code"},
        {"id": "t", "label": "", "source_file": "t.py", "file_type": "code"},
    ]
    links = [
        # unfamiliar name, confidence=EXTRACTED -> code fact, passes unmarked (B1)
        {"source": "p", "target": "q", "relation": "imports_from", "confidence": "EXTRACTED", "weight": 1.0},
        # same unfamiliar name, confidence=INFERRED -> gated, marked (B1)
        {"source": "p", "target": "r", "relation": "uses", "confidence": "INFERRED", "weight": 0.8},
        # EXTRACTED_CORE name but confidence=INFERRED -> confidence wins over the name dictionary
        {"source": "p", "target": "s", "relation": "calls", "confidence": "INFERRED", "weight": 0.5},
        # unfamiliar name, NO confidence field at all -> conservative default: inferred
        {"source": "p", "target": "t", "relation": "vibes_related_to", "weight": 1.0},
    ]
    graph_path = write_pair(root, commit, nodes, links)
    return root, graph_path


def run_adapter(*args: str, env_path: str | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if env_path is not None:
        # Only PATH is overridden (for the no_binary scenario) — sys.executable is absolute and
        # git stays resolvable from the system dirs, so nothing else about the run changes.
        env["PATH"] = env_path
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env
    )


def run_graph_build(
    args: list[str], *, path_prefix: str | None = None, path_override: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if path_override is not None:
        env["PATH"] = path_override
    elif path_prefix is not None:
        env["PATH"] = path_prefix + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        ["bash", str(GRAPH_BUILD_SCRIPT), *args], capture_output=True, text=True, env=env
    )


def path_without_any_graphify() -> str:
    """Current PATH with every directory that contains an executable named `graphify` removed —
    portable whether or not a real graphify happens to be installed in this environment (this
    sandbox has one), so the 'no binary' test is meaningful either way."""
    kept = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(entry) / "graphify" if entry else None
        if candidate is None or not candidate.exists():
            kept.append(entry)
    return os.pathsep.join(kept)


# Deterministic stand-in for the real `graphify` binary, used only by graph-build.sh's own tests:
# it mirrors graphify 0.9.17's actual `update --help` output (no --exclude flag — verified against
# the real binary) and emits one node per *.py file under the target root, so any other extension
# (e.g. .go) is a guaranteed "unparsed language" for the mixed-language/partial scenario (M6/M12)
# without depending on real tree-sitter language support. Links mirror the real binary's two
# habits the exclude-filter must distinguish: a dangling `imports os` per file (target node never
# exists — must SURVIVE the filter) and a `references` chain between consecutive files (both
# endpoints exist — dropped only when the filter cuts one of them).
FAKE_GRAPHIFY_SOURCE = '''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path


def cmd_update(argv):
    positional = [a for a in argv if not a.startswith("-")]
    root = Path(positional[0])
    out_dir = root / "graphify-out"
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {"graphify-out", ".git"})
        for name in sorted(files):
            if name.endswith(".py"):
                rel = (Path(current) / name).relative_to(root).as_posix()
                node_id = rel.replace("/", "_").replace(".", "_")
                nodes.append({"id": node_id, "label": name, "source_file": rel, "file_type": "code"})
    nodes.sort(key=lambda n: n["source_file"])
    links = []
    for node in nodes:
        links.append({"source": node["id"], "target": "os", "relation": "imports",
                      "confidence": "EXTRACTED", "weight": 1.0})
    for left, right in zip(nodes, nodes[1:]):
        links.append({"source": left["id"], "target": right["id"], "relation": "references",
                      "confidence": "EXTRACTED", "weight": 1.0})
    graph = {"nodes": nodes, "links": links}
    (out_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    print(f"[fake-graphify] wrote {len(nodes)} nodes", file=sys.stderr)


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: graphify <command>", file=sys.stderr)
        return 2
    command, rest = argv[0], argv[1:]
    if command == "--version":
        print("graphify 0.9.17-fake")
        return 0
    if command == "update":
        if rest and rest[0] in ("--help", "-h"):
            print("Run \\'graphify --help\\' for full usage.")
            return 0
        cmd_update(rest)
        return 0
    print(f"[fake-graphify] unknown command {command!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
'''


@pytest.fixture
def fake_graphify_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    """PATH prefix exposing the fake graphify binary — graph-build.sh only ever shells out to
    `graphify`, so this alone is enough to make its tests hermetic and deterministic."""
    bin_dir = tmp_path_factory.mktemp("fake-graphify-bin")
    shim = bin_dir / "graphify"
    shim.write_text(FAKE_GRAPHIFY_SOURCE, encoding="utf-8")
    shim.chmod(0o755)
    return str(bin_dir)


@pytest.fixture
def fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    return build_fixture(tmp_path)


# --- positive path -----------------------------------------------------------------------------


def test_check_ok(fixture: tuple[Path, Path, str]) -> None:
    _, graph_path, _ = fixture
    result = run_adapter("check", "--graph", str(graph_path))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["status"] == "ok"
    assert payload["reason"] is None
    source = payload["data"]["sources"][0]
    assert source["nodes"] == len(NODES)
    assert source["links"] == len(LINKS)


def test_neighbors_returns_v2_locators_and_gates_inferred(fixture: tuple[Path, Path, str]) -> None:
    _, graph_path, _ = fixture

    without_flag = run_adapter("neighbors", "--of", "a.py#Foo", "--graph", str(graph_path))
    assert without_flag.returncode == 0
    payload = json.loads(without_flag.stdout)
    neighbors = payload["data"]["neighbors"]
    # calls -> b.py#Child and references -> c.py#Util are EXTRACTED_CORE; contains/method
    # (a.py and a.py#Foo.bar) never show up in `neighbors`, inferred-only d.py#SimThing is absent.
    assert [n["locator"] for n in neighbors] == ["b.py#Child", "c.py#Util"]
    assert all("inferred" not in n for n in neighbors)

    with_flag = run_adapter(
        "neighbors", "--of", "a.py#Foo", "--graph", str(graph_path), "--include-inferred"
    )
    assert with_flag.returncode == 0
    by_locator = {n["locator"]: n for n in json.loads(with_flag.stdout)["data"]["neighbors"]}
    assert set(by_locator) == {"b.py#Child", "c.py#Util", "d.py#SimThing"}
    assert by_locator["d.py#SimThing"]["inferred"] is True
    assert "inferred" not in by_locator["b.py#Child"]
    assert "inferred" not in by_locator["c.py#Util"]


def test_edges_filters_by_relation_and_gates_inferred(fixture: tuple[Path, Path, str]) -> None:
    _, graph_path, _ = fixture

    structural = run_adapter("edges", "--relation", "contains,method", "--graph", str(graph_path))
    assert structural.returncode == 0
    structural_edges = json.loads(structural.stdout)["data"]["edges"]
    assert {e["relation"] for e in structural_edges} == {"contains", "method"}

    no_flag = run_adapter(
        "edges", "--relation", "calls,semantically_similar_to", "--graph", str(graph_path)
    )
    assert no_flag.returncode == 0
    assert [e["relation"] for e in json.loads(no_flag.stdout)["data"]["edges"]] == ["calls"]

    with_flag = run_adapter(
        "edges",
        "--relation", "calls,semantically_similar_to",
        "--graph", str(graph_path),
        "--include-inferred",
    )
    assert with_flag.returncode == 0
    by_relation = {e["relation"]: e for e in json.loads(with_flag.stdout)["data"]["edges"]}
    assert set(by_relation) == {"calls", "semantically_similar_to"}
    assert by_relation["semantically_similar_to"]["inferred"] is True
    assert "inferred" not in by_relation["calls"]


def test_slice_filters_by_root_and_applies_default_edge_policy(fixture: tuple[Path, Path, str]) -> None:
    root, graph_path, _ = fixture
    # source_file entries are relative to the fixture root, not this process's cwd — same as a
    # real caller whose cwd differs from the repo being sliced would need --project-root for.
    result = run_adapter(
        "slice", "--root", str(root), "--graph", str(graph_path), "--project-root", str(root)
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)["data"]
    assert {n["locator"] for n in data["nodes"]} == {
        "a.py", "a.py#Foo", "a.py#Foo.bar", "b.py", "b.py#Child", "c.py#Util", "d.py#SimThing",
    }
    # default policy: EXTRACTED_CORE only — no contains/method, no inferred without the flag.
    assert {l["relation"] for l in data["links"]} == {
        "calls", "references", "imports", "inherits", "implements",
    }


def test_parity_oracle_neighbors_is_byte_for_byte_deterministic(fixture: tuple[Path, Path, str]) -> None:
    _, graph_path, _ = fixture
    first = run_adapter(
        "neighbors", "--of", "a.py#Foo", "--graph", str(graph_path), "--include-inferred"
    )
    second = run_adapter(
        "neighbors", "--of", "a.py#Foo", "--graph", str(graph_path), "--include-inferred"
    )
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout


def run_model_consumer(root: Path, graph_path: Path, mode: str) -> tuple[str, list[str]]:
    """A minimal but REAL discovery consumer (M13's parity oracle b, ROADMAP invariant 2): it
    always calls the adapter the way a production consumer would — and actually parses its stdout.
    The completeness-bearing artifact is built ONLY from the graph-free deterministic core
    (git ls-files, sorted); hints from a successful `neighbors` call go into a separate channel
    that the core artifact never depends on. Returns (core_artifact_bytes_as_str, hints)."""
    core_result = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True,
    )
    core_files = sorted(line for line in core_result.stdout.splitlines() if line)

    adapter = run_adapter("neighbors", "--of", "a.py#Foo", "--graph", str(graph_path), "--mode", mode)
    hints: list[str] = []
    if adapter.returncode == 0:
        payload = json.loads(adapter.stdout)
        assert payload["status"] == "ok"
        hints = [n["locator"] for n in payload["data"]["neighbors"]]
    # The artifact a downstream gate would consume: serialized deterministically FROM THE CORE
    # ALONE — hints deliberately not part of it, per "граф меняет стоимость, не полноту".
    artifact = json.dumps({"files": core_files}, sort_keys=True)
    return artifact, hints


def test_parity_oracle_consumer_artifact_identical_off_vs_on(fixture: tuple[Path, Path, str]) -> None:
    root, graph_path, _ = fixture

    off_artifact, off_hints = run_model_consumer(root, graph_path, "off")
    on_artifact, on_hints = run_model_consumer(root, graph_path, "on")

    # Property 1: the completeness-bearing artifact is byte-for-byte identical whether the graph
    # was consulted (on, clean fixture, exit 0) or refused outright (off, exit 2 fallback).
    assert off_artifact == on_artifact

    # Property 2: the graph run REALLY used the graph — hints came out of the adapter's actual
    # stdout and live strictly beside the artifact, never inside it.
    assert off_hints == []
    assert on_hints == ["b.py#Child", "c.py#Util"]
    for hint in on_hints:
        assert hint not in off_artifact  # hint channel is not leaking into the core artifact


def test_mode_off_always_exits_2_without_reading_graph(tmp_path: Path) -> None:
    # A --graph pointing at nothing at all: mode=off must fall back WITHOUT ever looking at it.
    missing = tmp_path / "does-not-exist" / "graph.json"
    for op_args in (
        ["check"],
        ["meta"],
        ["neighbors", "--of", "a.py#Foo"],
        ["edges", "--relation", "calls"],
        ["slice", "--root", str(tmp_path)],
    ):
        result = run_adapter(*op_args, "--graph", str(missing), "--mode", "off")
        assert result.returncode == 2
        payload = json.loads(result.stdout)
        assert payload["status"] == "fallback"
        assert payload["reason"] == "mode=off"


def test_mode_off_short_circuits_before_graph_flag_is_required() -> None:
    # M4: off must not require --graph at all (argument checks happen AFTER the mode check).
    result = run_adapter("check", "--mode", "off")
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "fallback"
    assert payload["reason"] == "mode=off"


# --- invalid arguments (always exit 3, independent of --mode) -----------------------------------


def test_missing_graph_flag_is_invalid_argument() -> None:
    result = run_adapter("check")
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"


def test_allow_flags_without_mode_on_are_invalid_arguments(fixture: tuple[Path, Path, str]) -> None:
    _, graph_path, _ = fixture
    result = run_adapter("check", "--graph", str(graph_path), "--allow-stale")
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert "--mode on" in payload["reason"]


# --- normative negative matrix (ROADMAP block 1): EXACTLY the seven scenarios, each in both
# auto and on. Not every scenario maps onto fallback/error any more — the updated norm carves out
# two: no_binary is not a deviation at all (reading needs no binary; binary_available=false +
# stderr warning in BOTH modes), and partial gates only under --require-complete. The matrix
# encodes each scenario's own per-mode expectation instead of pretending they are uniform. ---


def _scenario_no_graph(tmp_path: Path) -> tuple[Path, list[str], str | None]:
    _, graph_path, _ = build_fixture(tmp_path, with_graph=False)
    return graph_path, [], None


def _scenario_unknown_schema(tmp_path: Path) -> tuple[Path, list[str], str | None]:
    _, graph_path, _ = build_fixture(tmp_path, schema_version=99)
    return graph_path, [], None


def _scenario_digest_mismatch(tmp_path: Path) -> tuple[Path, list[str], str | None]:
    _, graph_path, _ = build_fixture(tmp_path, digest="0" * 64)
    return graph_path, [], None


def _scenario_stale(tmp_path: Path) -> tuple[Path, list[str], str | None]:
    root, graph_path, _ = build_fixture(tmp_path)
    commit_again(root)  # HEAD now differs from what the manifest recorded
    return graph_path, [], None


def _scenario_dirty_live(tmp_path: Path) -> tuple[Path, list[str], str | None]:
    # Manifest's own dirty flag is False (a clean build) but a tracked file gets edited afterward
    # WITHOUT rebuilding — dirty must be judged live (B2), not only from the build-time flag.
    root, graph_path, _ = build_fixture(tmp_path, dirty=False)
    (root / "a.py").write_text("x = 999\n", encoding="utf-8")
    return graph_path, [], None


def _scenario_no_binary(tmp_path: Path) -> tuple[Path, list[str], str | None]:
    # Fresh, fully valid fixture — the ONLY thing wrong with this environment is the PATH.
    _, graph_path, _ = build_fixture(tmp_path)
    return graph_path, [], path_without_any_graphify()


def _scenario_partial_mixed_language(tmp_path: Path) -> tuple[Path, list[str], str | None]:
    # partial=true is what graph-build.sh's M6 predicate produces for a mixed-language repo (a
    # code extension seen but never parsed); it gates only for a caller that DECLARED it needs
    # completeness — hence --require-complete here, and the m15 warning-only tests elsewhere.
    _, graph_path, _ = build_fixture(tmp_path, partial=True)
    return graph_path, ["--require-complete"], None


# (name, setup, reason/stderr marker, is_deviation): is_deviation=True → auto: exit 2 fallback,
# on: exit 3 error; is_deviation=False (no_binary) → exit 0 ok in BOTH modes, marker in stderr,
# binary_available=false in data.
NORMATIVE_SCENARIOS = [
    ("no_graph", _scenario_no_graph, "graph not found", True),
    ("unknown_schema", _scenario_unknown_schema, "unknown schema_version", True),
    ("digest_mismatch", _scenario_digest_mismatch, "digest mismatch", True),
    ("stale", _scenario_stale, "HEAD", True),
    ("dirty_live", _scenario_dirty_live, "live git status", True),
    ("no_binary", _scenario_no_binary, "no_binary", False),
    ("mixed_language_partial", _scenario_partial_mixed_language, "partial", True),
]


@pytest.mark.parametrize("mode", ["auto", "on"])
@pytest.mark.parametrize(
    "name, setup, marker, is_deviation", NORMATIVE_SCENARIOS, ids=[s[0] for s in NORMATIVE_SCENARIOS]
)
def test_normative_matrix(
    tmp_path: Path, name: str, setup, marker: str, is_deviation: bool, mode: str
) -> None:
    graph_path, extra_args, env_path = setup(tmp_path)
    result = run_adapter(
        "check", "--graph", str(graph_path), "--mode", mode, *extra_args, env_path=env_path
    )
    payload = json.loads(result.stdout)
    if is_deviation:
        expected_exit, expected_status = (2, "fallback") if mode == "auto" else (3, "error")
        assert result.returncode == expected_exit
        assert payload["status"] == expected_status
        assert marker in payload["reason"]
        assert payload["data"] == {}
    else:
        assert result.returncode == 0
        assert payload["status"] == "ok"
        assert payload["data"]["binary_available"] is False
        assert marker in result.stderr


def test_binary_available_true_when_present_on_path(fixture: tuple[Path, Path, str]) -> None:
    # Counterpart of the no_binary scenario, hermetic either way: a shim dir prepended to PATH
    # guarantees `graphify` resolves regardless of whether the machine has a real install.
    _, graph_path, _ = fixture
    shim_dir = graph_path.parent / "shim-bin"
    shim_dir.mkdir()
    shim = shim_dir / "graphify"
    shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    shim.chmod(0o755)
    result = run_adapter(
        "check", "--graph", str(graph_path),
        env_path=str(shim_dir) + os.pathsep + os.environ.get("PATH", ""),
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["binary_available"] is True
    assert "no_binary" not in result.stderr


# --- supplementary deviations beyond the normative seven: manifest missing entirely, and the
# manifest's own build-time dirty flag (B2 keeps it as evidence of the build moment) ------------

SUPPLEMENTARY_DEVIATIONS = [
    ("no_manifest", dict(with_manifest=False), "manifest not found"),
    ("dirty_manifest_flag", dict(dirty=True), "manifest build flag"),
]


@pytest.mark.parametrize("mode", ["auto", "on"])
@pytest.mark.parametrize(
    "name, kwargs, reason_substring",
    SUPPLEMENTARY_DEVIATIONS,
    ids=[d[0] for d in SUPPLEMENTARY_DEVIATIONS],
)
def test_supplementary_deviations(
    tmp_path: Path, name: str, kwargs: dict, reason_substring: str, mode: str
) -> None:
    _, graph_path, _ = build_fixture(tmp_path, **kwargs)
    result = run_adapter("check", "--graph", str(graph_path), "--mode", mode)
    expected_exit, expected_status = (2, "fallback") if mode == "auto" else (3, "error")
    assert result.returncode == expected_exit
    payload = json.loads(result.stdout)
    assert payload["status"] == expected_status
    assert reason_substring in payload["reason"]
    assert payload["data"] == {}


def test_on_mode_allow_dirty_recovers_ok_for_live_dirty(tmp_path: Path) -> None:
    root, graph_path, _ = build_fixture(tmp_path, dirty=False)
    (root / "a.py").write_text("x = 999\n", encoding="utf-8")
    result = run_adapter("check", "--graph", str(graph_path), "--mode", "on", "--allow-dirty")
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "ok"


# --- on-mode overrides: only stale/dirty/partial are ever overridable ---------------------------


def test_on_mode_allow_stale_recovers_ok(tmp_path: Path) -> None:
    root, graph_path, _ = build_fixture(tmp_path)
    commit_again(root)
    result = run_adapter("check", "--graph", str(graph_path), "--mode", "on", "--allow-stale")
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "ok"


def test_on_mode_allow_dirty_recovers_ok(tmp_path: Path) -> None:
    _, graph_path, _ = build_fixture(tmp_path, dirty=True)
    result = run_adapter("check", "--graph", str(graph_path), "--mode", "on", "--allow-dirty")
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "ok"


def test_on_mode_allow_partial_recovers_ok(tmp_path: Path) -> None:
    # Without --require-complete, partial isn't gated at all (m15) — --allow-partial is simply a
    # harmless no-op here; the dedicated require-complete tests below cover the override itself.
    _, graph_path, _ = build_fixture(tmp_path, partial=True)
    result = run_adapter("check", "--graph", str(graph_path), "--mode", "on", "--allow-partial")
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "ok"


def test_on_mode_digest_mismatch_is_never_overridable(tmp_path: Path) -> None:
    # Structural corruption (bad digest/unknown schema/missing files) has no --allow-* — it is not
    # a freshness question, so even throwing every override flag at it must still hard-stop.
    _, graph_path, _ = build_fixture(tmp_path, digest="0" * 64)
    result = run_adapter(
        "check", "--graph", str(graph_path), "--mode", "on",
        "--allow-stale", "--allow-dirty", "--allow-partial",
    )
    assert result.returncode == 3
    assert json.loads(result.stdout)["status"] == "error"


# --- m15: partial is a warning by default, a deviation only under --require-complete ------------


def test_partial_without_require_complete_is_ok_with_warning(tmp_path: Path) -> None:
    _, graph_path, _ = build_fixture(tmp_path, partial=True)
    result = run_adapter("check", "--graph", str(graph_path))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["data"]["partial"] is True
    assert "partial" in result.stderr


def test_partial_with_require_complete_is_auto_fallback(tmp_path: Path) -> None:
    _, graph_path, _ = build_fixture(tmp_path, partial=True)
    result = run_adapter("check", "--graph", str(graph_path), "--require-complete")
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "fallback"
    assert "partial" in payload["reason"]


def test_partial_with_require_complete_on_mode_hard_errors(tmp_path: Path) -> None:
    _, graph_path, _ = build_fixture(tmp_path, partial=True)
    result = run_adapter("check", "--graph", str(graph_path), "--mode", "on", "--require-complete")
    assert result.returncode == 3
    assert json.loads(result.stdout)["status"] == "error"


def test_partial_with_require_complete_allow_partial_recovers_ok(tmp_path: Path) -> None:
    _, graph_path, _ = build_fixture(tmp_path, partial=True)
    result = run_adapter(
        "check", "--graph", str(graph_path), "--mode", "on", "--require-complete", "--allow-partial"
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "ok"


def test_not_partial_never_carries_partial_field(fixture: tuple[Path, Path, str]) -> None:
    _, graph_path, _ = fixture
    result = run_adapter("check", "--graph", str(graph_path))
    assert result.returncode == 0
    assert "partial" not in json.loads(result.stdout)["data"]


# --- B1/M11/M14: confidence-first edge gating ----------------------------------------------------


def test_confidence_first_extracted_unknown_relation_passes_unmarked(tmp_path: Path) -> None:
    _, graph_path = build_confidence_fixture(tmp_path)
    result = run_adapter("neighbors", "--of", "p.py", "--graph", str(graph_path))
    assert result.returncode == 0
    neighbors = {n["locator"]: n for n in json.loads(result.stdout)["data"]["neighbors"]}
    assert "q.py" in neighbors
    assert "inferred" not in neighbors["q.py"]


def test_confidence_first_gates_unknown_relation_marked_inferred(tmp_path: Path) -> None:
    _, graph_path = build_confidence_fixture(tmp_path)
    without = run_adapter("neighbors", "--of", "p.py", "--graph", str(graph_path))
    without_locators = {n["locator"] for n in json.loads(without.stdout)["data"]["neighbors"]}
    assert "r.py" not in without_locators  # uses/INFERRED gated by default

    with_flag = run_adapter("neighbors", "--of", "p.py", "--graph", str(graph_path), "--include-inferred")
    by_locator = {n["locator"]: n for n in json.loads(with_flag.stdout)["data"]["neighbors"]}
    assert by_locator["r.py"]["inferred"] is True


def test_confidence_overrides_extracted_core_name_dictionary(tmp_path: Path) -> None:
    # "calls" is in EXTRACTED_CORE by name, but this particular edge is tagged confidence=INFERRED
    # — the gate must follow the field, not the name (B1's whole point).
    _, graph_path = build_confidence_fixture(tmp_path)
    without = run_adapter("neighbors", "--of", "p.py", "--graph", str(graph_path))
    without_locators = {n["locator"] for n in json.loads(without.stdout)["data"]["neighbors"]}
    assert "s.py" not in without_locators

    with_flag = run_adapter("neighbors", "--of", "p.py", "--graph", str(graph_path), "--include-inferred")
    by_locator = {n["locator"]: n for n in json.loads(with_flag.stdout)["data"]["neighbors"]}
    assert by_locator["s.py"]["inferred"] is True


def test_confidence_absent_unknown_relation_defaults_conservative_inferred(tmp_path: Path) -> None:
    _, graph_path = build_confidence_fixture(tmp_path)
    without = run_adapter("neighbors", "--of", "p.py", "--graph", str(graph_path))
    without_locators = {n["locator"] for n in json.loads(without.stdout)["data"]["neighbors"]}
    assert "t.py" not in without_locators

    with_flag = run_adapter("neighbors", "--of", "p.py", "--graph", str(graph_path), "--include-inferred")
    by_locator = {n["locator"]: n for n in json.loads(with_flag.stdout)["data"]["neighbors"]}
    assert by_locator["t.py"]["inferred"] is True


def test_confidence_first_edges_op_same_semantics(tmp_path: Path) -> None:
    _, graph_path = build_confidence_fixture(tmp_path)
    result = run_adapter(
        "edges", "--relation", "imports_from,uses,calls,vibes_related_to", "--graph", str(graph_path)
    )
    assert result.returncode == 0
    edges = json.loads(result.stdout)["data"]["edges"]
    assert {e["relation"] for e in edges} == {"imports_from"}  # only the EXTRACTED one, unmarked
    assert "inferred" not in edges[0]

    with_flag = run_adapter(
        "edges", "--relation", "imports_from,uses,calls,vibes_related_to",
        "--graph", str(graph_path), "--include-inferred",
    )
    by_relation = {e["relation"]: e for e in json.loads(with_flag.stdout)["data"]["edges"]}
    assert set(by_relation) == {"imports_from", "uses", "calls", "vibes_related_to"}
    assert "inferred" not in by_relation["imports_from"]
    assert by_relation["uses"]["inferred"] is True
    assert by_relation["calls"]["inferred"] is True
    assert by_relation["vibes_related_to"]["inferred"] is True


# --- B3: multi-repo node-id collisions must never merge across --graph pairs ---------------------


def test_multi_repo_node_id_collision_is_isolated_by_source(tmp_path: Path) -> None:
    # Two independent repos whose graphs reuse the SAME node id ("shared") for UNRELATED symbols —
    # without qualifying every lookup by which --graph it came from, the second repo's node would
    # silently clobber the first's in a naive {id: node} merge, corrupting both slice and BFS.
    root_a = tmp_path / "repo_a"
    root_b = tmp_path / "repo_b"
    commit_a = init_repo(root_a)
    commit_b = init_repo(root_b)

    def pair(root: Path, commit: str, symbol: str, filename: str) -> Path:
        nodes = [
            {"id": "shared", "label": symbol, "source_file": filename, "file_type": "code"},
            {"id": "shared_helper", "label": "Helper", "source_file": filename, "file_type": "code"},
        ]
        links = [
            {"source": "shared", "target": "shared_helper", "relation": "calls", "confidence": "EXTRACTED", "weight": 1.0},
        ]
        return write_pair(root, commit, nodes, links)

    graph_a = pair(root_a, commit_a, "AlphaThing", "alpha.py")
    graph_b = pair(root_b, commit_b, "BetaThing", "beta.py")

    # slice on repo A must see only repo A's nodes, never repo B's same-id node.
    result = run_adapter(
        "slice", "--root", str(root_a),
        "--graph", str(graph_a), "--graph", str(graph_b),
        "--project-root", str(tmp_path),
    )
    assert result.returncode == 0
    locators = {n["locator"] for n in json.loads(result.stdout)["data"]["nodes"]}
    assert locators == {"alpha.py#AlphaThing", "alpha.py#Helper"}

    # neighbors of repo A's "shared" node must never reach into repo B, even though both graphs
    # use the SAME raw node id — BFS must stay inside its own (graph, manifest) pair.
    neighbors_result = run_adapter(
        "neighbors", "--of", "alpha.py#AlphaThing",
        "--graph", str(graph_a), "--graph", str(graph_b),
    )
    assert neighbors_result.returncode == 0
    neighbor_locators = {n["locator"] for n in json.loads(neighbors_result.stdout)["data"]["neighbors"]}
    assert neighbor_locators == {"alpha.py#Helper"}
    assert "beta.py#Helper" not in neighbor_locators


# --- M7: nodes outside every known root are marked external, never included in a root-slice.
# Parametrized over auto AND on: external is a marking, not a deviation — both modes must return
# the same successful envelope with the same flag, never diverge on it. -------------------------


@pytest.mark.parametrize("mode", ["auto", "on"])
def test_neighbors_and_slice_mark_node_outside_all_roots_as_external(tmp_path: Path, mode: str) -> None:
    root = tmp_path / "erepo"
    commit = init_repo(root)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "vendored.py"
    outside_file.write_text("y = 1\n", encoding="utf-8")
    outside_real = os.path.realpath(outside_file)

    nodes = [
        {"id": "in_root", "label": "", "source_file": "a.py", "file_type": "code"},
        {"id": "outside", "label": "", "source_file": str(outside_file), "file_type": "code"},
    ]
    links = [
        {"source": "in_root", "target": "outside", "relation": "imports", "confidence": "EXTRACTED", "weight": 1.0},
    ]
    graph_path = write_pair(root, commit, nodes, links)

    result = run_adapter("neighbors", "--of", "a.py", "--graph", str(graph_path), "--mode", mode)
    assert result.returncode == 0
    neighbors = {n["locator"]: n for n in json.loads(result.stdout)["data"]["neighbors"]}
    assert neighbors[outside_real]["external"] is True

    sliced = run_adapter(
        "slice", "--root", str(root), "--graph", str(graph_path),
        "--project-root", str(root), "--mode", mode,
    )
    assert sliced.returncode == 0
    sliced_locators = {n["locator"] for n in json.loads(sliced.stdout)["data"]["nodes"]}
    assert outside_real not in sliced_locators  # external nodes never belong to a root-slice
    assert "a.py" in sliced_locators


# --- M10: locator grammar validation flags but never hides an ungrammatical locator --------------


def test_locator_invalid_flag_for_ungrammatical_label(tmp_path: Path) -> None:
    # Real graphify 0.9.17 emits a leading-dot label for methods (".go()") which fails the v2
    # locator symbol grammar (must start with [A-Za-z_$]) — M10 requires this surfaced, not hidden.
    root = tmp_path / "lrepo"
    commit = init_repo(root)
    nodes = [
        {"id": "m", "label": "", "source_file": "m.py", "file_type": "code"},
        {"id": "m_cls", "label": "Cls", "source_file": "m.py", "file_type": "code"},
        {"id": "m_cls_go", "label": ".go()", "source_file": "m.py", "file_type": "code"},
    ]
    links = [
        {"source": "m", "target": "m_cls", "relation": "contains", "confidence": "EXTRACTED", "weight": 1.0},
        {"source": "m_cls", "target": "m_cls_go", "relation": "method", "confidence": "EXTRACTED", "weight": 1.0},
    ]
    graph_path = write_pair(root, commit, nodes, links)

    result = run_adapter("slice", "--root", str(root), "--graph", str(graph_path), "--project-root", str(root))
    assert result.returncode == 0
    nodes_out = {n["locator"]: n for n in json.loads(result.stdout)["data"]["nodes"]}
    assert nodes_out["m.py#Cls"].get("locator_invalid") is not True
    assert nodes_out["m.py#.go()"]["locator_invalid"] is True
    assert "locator failed grammar validation" in result.stderr


# --- M8: strict manifest schema — presence AND type, not just schema_version equality ------------


def _read_manifest(graph_path: Path) -> dict:
    return json.loads((graph_path.parent / "graph.meta.json").read_text())


def _write_manifest(graph_path: Path, manifest: dict) -> None:
    (graph_path.parent / "graph.meta.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_manifest_missing_required_field_is_unknown_schema(tmp_path: Path) -> None:
    _, graph_path, _ = build_fixture(tmp_path)
    manifest = _read_manifest(graph_path)
    del manifest["excludes"]
    _write_manifest(graph_path, manifest)
    result = run_adapter("check", "--graph", str(graph_path))
    assert result.returncode == 2
    assert "excludes" in json.loads(result.stdout)["reason"]


def test_manifest_roots_must_be_canonical_realpath(tmp_path: Path) -> None:
    root, graph_path, _ = build_fixture(tmp_path)
    manifest = _read_manifest(graph_path)
    manifest["roots"] = [str(root) + "/"]  # trailing slash: not the canonical realpath form
    manifest["revisions"][0]["root"] = str(root) + "/"
    _write_manifest(graph_path, manifest)
    result = run_adapter("check", "--graph", str(graph_path))
    assert result.returncode == 2
    assert "canonical realpath" in json.loads(result.stdout)["reason"]


def test_manifest_roots_revisions_must_correspond_1to1(tmp_path: Path) -> None:
    _, graph_path, _ = build_fixture(tmp_path)
    manifest = _read_manifest(graph_path)
    manifest["roots"] = sorted(manifest["roots"] + ["/tmp/some/other/root"])
    _write_manifest(graph_path, manifest)
    result = run_adapter("check", "--graph", str(graph_path))
    assert result.returncode == 2
    assert "1:1" in json.loads(result.stdout)["reason"]


def test_manifest_schema_version_wrong_type_is_unknown_schema(tmp_path: Path) -> None:
    _, graph_path, _ = build_fixture(tmp_path)
    manifest = _read_manifest(graph_path)
    manifest["schema_version"] = "1"  # string, not int
    _write_manifest(graph_path, manifest)
    result = run_adapter("check", "--graph", str(graph_path))
    assert result.returncode == 2
    assert "schema_version must be an int" in json.loads(result.stdout)["reason"]


# --- M9: dup node id within a pair is corruption; UnicodeDecodeError is a deviation, never a
# traceback; a dangling edge endpoint (real graphify shape, e.g. an unresolved stdlib import) is
# tolerated, not treated as corruption --------------------------------------------------------


def test_duplicate_node_id_within_pair_is_unknown_schema(tmp_path: Path) -> None:
    root = tmp_path / "duprepo"
    commit = init_repo(root)
    nodes = [
        {"id": "dup", "label": "One", "source_file": "a.py", "file_type": "code"},
        {"id": "dup", "label": "Two", "source_file": "a.py", "file_type": "code"},
    ]
    graph_path = write_pair(root, commit, nodes, [])
    result = run_adapter("check", "--graph", str(graph_path))
    assert result.returncode == 2
    assert "duplicate id" in json.loads(result.stdout)["reason"]


def test_graph_with_invalid_utf8_is_deviation_not_traceback(tmp_path: Path) -> None:
    _, graph_path, _ = build_fixture(tmp_path)
    graph_path.write_bytes(b'{"a": "\x80\x81"}')  # invalid UTF-8 continuation byte, no leading byte
    result = run_adapter("check", "--graph", str(graph_path))
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "fallback"
    assert "not valid JSON" in payload["reason"]
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_manifest_with_invalid_utf8_is_deviation_not_traceback(tmp_path: Path) -> None:
    _, graph_path, _ = build_fixture(tmp_path)
    (graph_path.parent / "graph.meta.json").write_bytes(b'{"a": "\x80\x81"}')
    result = run_adapter("check", "--graph", str(graph_path))
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "fallback"
    assert "not valid JSON" in payload["reason"]
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_dangling_edge_endpoint_is_tolerated_not_a_deviation(tmp_path: Path) -> None:
    # Real graphify 0.9.17 routinely emits edges like `imports os` whose target ("os") has no
    # corresponding node — treating this as structural corruption would fallback on every real
    # codebase with an import statement. It must be skipped at the point of use, not flagged.
    root = tmp_path / "danglerepo"
    commit = init_repo(root)
    nodes = [{"id": "a", "label": "", "source_file": "a.py", "file_type": "code"}]
    links = [
        {"source": "a", "target": "os", "relation": "imports", "confidence": "EXTRACTED", "weight": 1.0},
    ]
    graph_path = write_pair(root, commit, nodes, links)

    check_result = run_adapter("check", "--graph", str(graph_path))
    assert check_result.returncode == 0

    edges_result = run_adapter("edges", "--relation", "imports", "--graph", str(graph_path))
    assert edges_result.returncode == 0
    assert json.loads(edges_result.stdout)["data"]["edges"] == []
    assert "unresolved endpoint" in edges_result.stderr

    # neighbors must degrade just as loudly as edges: BFS reaches the dangling "os" endpoint,
    # cannot resolve it to a locator, skips it — and says so on stderr with the same wording.
    neighbors_result = run_adapter("neighbors", "--of", "a.py", "--graph", str(graph_path))
    assert neighbors_result.returncode == 0
    assert json.loads(neighbors_result.stdout)["data"]["neighbors"] == []
    assert "unresolved endpoint" in neighbors_result.stderr


# --- graph-build.sh --------------------------------------------------------------------------


def test_graph_build_no_binary_exits_3_with_message(tmp_path: Path) -> None:
    root = tmp_path / "norepo"
    init_repo(root)
    result = run_graph_build([str(root)], path_override=path_without_any_graphify())
    assert result.returncode == 3
    assert "graphify" in result.stderr


def test_graph_build_writes_manifest_with_effective_excludes(tmp_path: Path, fake_graphify_path: str) -> None:
    root = tmp_path / "brepo"
    init_repo(root)
    (root / "code.py").write_text("x = 1\n", encoding="utf-8")
    vendor_dir = root / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / "third.py").write_text("y = 1\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    git("commit", "-q", "-m", "add files", cwd=root)

    result = run_graph_build([str(root)], path_prefix=fake_graphify_path)
    assert result.returncode == 0, result.stderr

    graph_path = root / "graphify-out" / "graph.json"
    manifest = json.loads((root / "graphify-out" / "graph.meta.json").read_text())
    graph = json.loads(graph_path.read_text())

    # vendor/ is a default exclude (M5): even though the fake graphify has no --exclude flag and
    # doesn't know to skip it, the post-build deterministic filter must remove it from graph.json.
    source_files = {n["source_file"] for n in graph["nodes"]}
    assert "vendor/third.py" not in source_files
    assert "code.py" in source_files
    for expected in ("vendor", "generated", "graphify-out", ".git"):
        assert expected in manifest["excludes"]
    # digest recomputed from the FILTERED file (M5), not the pre-filter one.
    assert manifest["digest"] == hashlib.sha256(graph_path.read_bytes()).hexdigest()


def test_graph_build_filter_preserves_native_dangling_edges(tmp_path: Path, fake_graphify_path: str) -> None:
    # The exclude filter must distinguish two kinds of "missing endpoint": an endpoint node that
    # the filter itself just cut (edge must go), and an endpoint that NEVER existed as a node —
    # graphify's own routine dangling shape, e.g. `imports os` (edge must stay: it is a real code
    # fact the adapter is expected to tolerate downstream).
    root = tmp_path / "danglingbuild"
    init_repo(root)  # commits a.py
    (root / "code.py").write_text("x = 1\n", encoding="utf-8")
    vendor_dir = root / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / "third.py").write_text("y = 1\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    git("commit", "-q", "-m", "add files", cwd=root)

    result = run_graph_build([str(root)], path_prefix=fake_graphify_path)
    assert result.returncode == 0, result.stderr

    graph = json.loads((root / "graphify-out" / "graph.json").read_text())
    edges = {(l["source"], l["target"]) for l in graph["links"]}
    # dangling imports of never-materialized "os" survive for every KEPT node...
    assert ("a_py", "os") in edges
    assert ("code_py", "os") in edges
    # ...the chain edge between two kept nodes survives...
    assert ("a_py", "code_py") in edges
    # ...but every edge touching the filtered-out vendor node is gone, in both directions.
    assert ("code_py", "vendor_third_py") not in edges
    assert ("vendor_third_py", "os") not in edges


def test_graph_build_user_exclude_flag_filters_matching_files(tmp_path: Path, fake_graphify_path: str) -> None:
    root = tmp_path / "userexrepo"
    init_repo(root)
    (root / "keep.py").write_text("x = 1\n", encoding="utf-8")
    skip_dir = root / "generated_stuff"
    skip_dir.mkdir()
    (skip_dir / "skip.py").write_text("y = 1\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    git("commit", "-q", "-m", "add files", cwd=root)

    result = run_graph_build(["--exclude", "generated_stuff", str(root)], path_prefix=fake_graphify_path)
    assert result.returncode == 0, result.stderr

    graph = json.loads((root / "graphify-out" / "graph.json").read_text())
    source_files = {n["source_file"] for n in graph["nodes"]}
    assert "generated_stuff/skip.py" not in source_files
    assert "keep.py" in source_files

    manifest = json.loads((root / "graphify-out" / "graph.meta.json").read_text())
    assert "generated_stuff" in manifest["excludes"]


def test_graph_build_mixed_language_marks_partial(tmp_path: Path, fake_graphify_path: str) -> None:
    root = tmp_path / "polyglot"
    init_repo(root)  # already commits a.py
    (root / "b.go").write_text("package main\n", encoding="utf-8")  # fake graphify never parses .go
    git("add", "-A", cwd=root)
    git("commit", "-q", "-m", "add go file", cwd=root)

    result = run_graph_build([str(root)], path_prefix=fake_graphify_path)
    assert result.returncode == 0, result.stderr

    manifest = json.loads((root / "graphify-out" / "graph.meta.json").read_text())
    assert manifest["files_seen"].get(".go") == 1
    assert manifest["files_parsed"].get(".go", 0) == 0
    assert manifest["partial"] is True

    # m15: the adapter surfaces it as a warning by default, a hard deviation only with
    # --require-complete — tying M6 (partial detection) and m15 (partial gating) together.
    graph_path = root / "graphify-out" / "graph.json"
    default_run = run_adapter("check", "--graph", str(graph_path))
    assert default_run.returncode == 0
    assert json.loads(default_run.stdout)["data"]["partial"] is True

    strict_run = run_adapter("check", "--graph", str(graph_path), "--require-complete")
    assert strict_run.returncode == 2


def test_graph_build_excludes_symlink_pointing_outside_root(tmp_path: Path, fake_graphify_path: str) -> None:
    root = tmp_path / "symrepo"
    init_repo(root)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "outside.py"
    outside_file.write_text("z = 1\n", encoding="utf-8")
    (root / "inside.py").write_text("x = 1\n", encoding="utf-8")
    (root / "linked.py").symlink_to(outside_file)
    git("add", "-A", cwd=root)
    git("commit", "-q", "-m", "add symlink", cwd=root)

    result = run_graph_build([str(root)], path_prefix=fake_graphify_path)
    assert result.returncode == 0, result.stderr

    manifest = json.loads((root / "graphify-out" / "graph.meta.json").read_text())
    assert "linked.py" in manifest.get("excluded_symlinks", [])
    # a.py (from init_repo) + inside.py are counted; the outside-pointing symlink is not.
    assert manifest["files_seen"].get(".py") == 2


def test_graph_build_writes_atomically_no_tmp_leftovers(tmp_path: Path, fake_graphify_path: str) -> None:
    root = tmp_path / "atomicrepo"
    init_repo(root)  # already commits a.py

    result = run_graph_build([str(root)], path_prefix=fake_graphify_path)
    assert result.returncode == 0, result.stderr
    leftovers = list((root / "graphify-out").glob("*.tmp"))
    assert leftovers == []


def test_graph_build_output_is_accepted_by_adapter_check(tmp_path: Path, fake_graphify_path: str) -> None:
    # End-to-end: whatever graph-build.sh writes must be exactly what graph-adapter.py accepts —
    # the manifest schema (M8) and the digest recomputation (M5) have to actually agree in practice.
    root = tmp_path / "e2erepo"
    init_repo(root)  # already commits a.py

    build_result = run_graph_build([str(root)], path_prefix=fake_graphify_path)
    assert build_result.returncode == 0, build_result.stderr

    graph_path = root / "graphify-out" / "graph.json"
    check_result = run_adapter("check", "--graph", str(graph_path))
    assert check_result.returncode == 0, check_result.stdout + check_result.stderr
    assert json.loads(check_result.stdout)["status"] == "ok"
