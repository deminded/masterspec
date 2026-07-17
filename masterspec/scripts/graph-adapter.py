#!/usr/bin/env python3
"""Single point of reading a graphify code graph — masterspec-graphify design v2.1, tact 0
(rewritten after Sol-review "ПЕРЕДЕЛЫВАТЬ" 16.07 — see ROADMAP.md block 1 for the corrected norm).

Consumers never parse graph.json/graph.meta.json themselves and never see graph node ids: they
call this adapter and get back locators (source_file[#label]) plus a status that tells them
whether the graph was even usable. That is the "optionality" invariant — no graph, or any
detected deviation, degrades to a visible fallback (auto) or a hard stop (on), never a silent
guess. Determinism (sorted output, no wall-clock/PID leakage) is the "parity" invariant: the
same fixture must produce byte-identical stdout across runs, so callers can diff on/off.

Multiple --graph pairs (multi-repo) are never merged into one id space: every node/edge lookup is
keyed by (source_index, node_id), so two repos are free to reuse the same graphify node id without
corrupting each other's slice/neighbors/edges (B3).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

# (source_index, node_id) — the collision-proof handle every op uses internally once nodes are
# loaded. Never exposed to a consumer; the only handle a consumer ever sees is a v2 locator string.
Key = tuple[int, str]

# Confidence-first edge policy (corrected 16.07 against live graphify 0.9.17 — see B1). The gate
# that matters is the link's own `confidence` field: EXTRACTED passes as a code fact, INFERRED is
# gated behind --include-inferred, regardless of whether the relation NAME is one we recognize.
# These three sets are only a FALLBACK for graphs that omit confidence (or an unrecognized relation
# with no confidence at all, treated conservatively as inferred — see is_edge_inferred). They are
# not an allowlist a real graph's edges must belong to: live graphify already uses relation names
# beyond these five (imports_from, uses) and those pass through untouched once they carry
# confidence=EXTRACTED. The named allowlist for a *specific* consumer's math (e.g. domain
# clustering, ROADMAP block 3) belongs to that consumer, not to this adapter's trust gate.
EXTRACTED_CORE = frozenset({"references", "calls", "imports", "inherits", "implements"})
# Nesting relations: never a default discovery hint (neighbors/slice) regardless of confidence —
# only reachable via `edges --relation contains,method` on explicit request.
STRUCTURAL_ON_REQUEST = frozenset({"contains", "method"})
INFERRED_CLASSES = frozenset(
    {
        "semantically_similar_to",
        "conceptually_related_to",
        "shares_data_with",
        "part_of",
        "rationale_for",
    }
)

REQUIRED_NODE_FIELDS = ("id", "source_file", "file_type")
REQUIRED_LINK_FIELDS = ("source", "target", "relation")

# Deviation kinds that --allow-stale/--allow-dirty/--allow-partial may override in mode=on.
# Everything else (missing files, bad digest, unknown schema) is structural corruption, not a
# freshness question, and stays a hard stop even under `on` — there is no flag for it by design.
OVERRIDABLE_KINDS = frozenset({"stale", "dirty", "partial"})

# v2 locator grammar (ROADMAP block 2 §4.3): path has no space/#/: ; symbol is an identifier with
# an optional "()" suffix. Used to flag (not reject) locators the adapter cannot vouch for (M10).
_PATH_INVALID_CHARS = re.compile(r"[ #:]")
_SYMBOL_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$.]*(\(\))?$")

# Note: `partial` itself is computed once, at build time, by graph-build.sh (whose own CODE_EXTS
# list — M6 — decides it) and stored as a plain bool in the manifest; this adapter only ever reads
# that bool (see collect_deviations/op_meta), so it has no CODE_EXTS of its own to duplicate.


class AdapterArgError(Exception):
    """Raised for invalid CLI input — always a hard stop (exit 3), independent of --mode."""


class ArgParser(argparse.ArgumentParser):
    """Route argparse's own usage errors through our JSON envelope instead of printing to stderr
    and exiting 2 — this CLI's contract is "always one JSON object on stdout", no exceptions."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise AdapterArgError(message)


@dataclass
class Source:
    graph_path: Path
    manifest_path: Path
    graph_data: dict | None
    manifest_data: dict | None


def log(diagnostic: dict) -> None:
    """Diagnostics are JSON lines on stderr — never mixed into the single stdout JSON object."""
    print(json.dumps(diagnostic, sort_keys=True, ensure_ascii=False), file=sys.stderr)


def emit(status: str, reason: str | None, data: dict, exit_code: int) -> int:
    payload = {"schema_version": SCHEMA_VERSION, "status": status, "reason": reason, "data": data}
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    return exit_code


def emit_error(message: str) -> int:
    log({"level": "error", "message": message})
    return emit("error", message, {}, 3)


def git_head(root: str) -> str | None:
    """Current HEAD of the repo at root, or None if it cannot be determined (no git, not a repo,
    detached weirdness) — treated as a staleness deviation rather than crashing the adapter."""
    try:
        result = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_dirty_live(root: str) -> bool | None:
    """Live worktree dirtiness at read time (B2), independent of the manifest's build-time dirty
    flag: a build can be clean and the worktree can go dirty seconds later, and the manifest only
    ever attests to the moment graph-build.sh ran. None (git unavailable/timeout) is not itself a
    deviation — it just means this particular signal could not be collected."""
    try:
        result = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and value != ""


def validate_manifest_schema(manifest_data: dict) -> list[str]:
    """Strict manifest shape (M8): every field's presence AND type, not just schema_version
    equality — a manifest that merely 'looks like JSON' but has the wrong shape is exactly the
    kind of adapter-side guess the norm forbids. Returns human-readable error strings; the caller
    tags each one as an unknown_schema deviation."""
    errors: list[str] = []

    if not _is_nonempty_str(manifest_data.get("graphify_version")):
        errors.append("manifest.graphify_version must be a non-empty string")

    schema_version = manifest_data.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        errors.append("manifest.schema_version must be an int")

    revisions = manifest_data.get("revisions")
    revision_roots: list[str] = []
    if not isinstance(revisions, list) or not revisions:
        errors.append("manifest.revisions must be a non-empty list")
    else:
        for index, revision in enumerate(revisions):
            if not isinstance(revision, dict):
                errors.append(f"manifest.revisions[{index}] must be an object")
                continue
            if not _is_nonempty_str(revision.get("root")):
                errors.append(f"manifest.revisions[{index}].root must be a non-empty string")
            else:
                revision_roots.append(revision["root"])
            if not _is_nonempty_str(revision.get("commit")):
                errors.append(f"manifest.revisions[{index}].commit must be a non-empty string")
            if not isinstance(revision.get("dirty"), bool):
                errors.append(f"manifest.revisions[{index}].dirty must be a bool")
        if len(revision_roots) != len(set(revision_roots)):
            errors.append("manifest.revisions must have exactly one entry per root (duplicate root found)")

    roots = manifest_data.get("roots")
    if not isinstance(roots, list) or not roots or not all(_is_nonempty_str(r) for r in roots):
        errors.append("manifest.roots must be a non-empty list of non-empty strings")
    else:
        if len(roots) != len(set(roots)):
            errors.append("manifest.roots must be unique")
        if roots != sorted(roots):
            errors.append("manifest.roots must be sorted")
        for root in roots:
            if os.path.realpath(root) != root:
                errors.append(f"manifest.roots entry is not a canonical realpath: {root!r}")
        if revision_roots and set(roots) != set(revision_roots):
            errors.append("manifest.roots must correspond 1:1 with revisions[].root")

    excludes = manifest_data.get("excludes")
    if not isinstance(excludes, list) or not all(isinstance(e, str) for e in excludes):
        errors.append("manifest.excludes must be a list of strings")

    if not _is_nonempty_str(manifest_data.get("digest")):
        errors.append("manifest.digest must be a non-empty string")

    for field in ("files_seen", "files_parsed"):
        if not isinstance(manifest_data.get(field), dict):
            errors.append(f"manifest.{field} must be an object")

    if not isinstance(manifest_data.get("partial"), bool):
        errors.append("manifest.partial must be a bool")

    return errors


def validate_graph_structure(graph_data: object) -> list[str]:
    """Structural half of 'unknown schema', scoped to one (graph, manifest) pair (M9): duplicate
    node ids WITHIN the pair and wrong field types are corruption the adapter refuses to guess
    through. Dangling edge endpoints are deliberately NOT flagged here — real graphify 0.9.17
    output routinely has them (e.g. an `imports os` edge whose target is the bare string "os" with
    no corresponding node, because the stdlib module was never materialized); treating every
    dangling endpoint as structural corruption would make `auto` mode fall back on any real
    codebase with an import statement. Dangling endpoints are tolerated at the point of use
    instead — op_edges/op_neighbors skip an unresolved endpoint and log a warning."""
    errors: list[str] = []
    if not isinstance(graph_data, dict):
        return ["graph.json root is not a JSON object"]

    nodes = graph_data.get("nodes")
    if not isinstance(nodes, list):
        errors.append("graph.json missing 'nodes' array")
    else:
        seen_ids: set[str] = set()
        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                errors.append(f"node[{index}] is not an object")
                continue
            missing = [f for f in REQUIRED_NODE_FIELDS if not isinstance(node.get(f), str) or not node.get(f)]
            if missing:
                errors.append(f"node[{index}] missing required field(s): {', '.join(missing)}")
                continue
            node_id = node["id"]
            if node_id in seen_ids:
                errors.append(f"node[{index}] duplicate id within pair: {node_id!r}")
            seen_ids.add(node_id)

    links = graph_data.get("links")
    if not isinstance(links, list):
        errors.append("graph.json missing 'links' array")
    else:
        for index, link in enumerate(links):
            if not isinstance(link, dict):
                errors.append(f"link[{index}] is not an object")
                continue
            missing = [f for f in REQUIRED_LINK_FIELDS if not isinstance(link.get(f), str) or not link.get(f)]
            if missing:
                errors.append(f"link[{index}] missing required field(s): {', '.join(missing)}")
                continue
            confidence = link.get("confidence")
            if confidence is not None and not isinstance(confidence, str):
                errors.append(f"link[{index}].confidence must be a string when present")

    return errors


def collect_deviations(
    graph_path: Path, manifest_path: Path
) -> tuple[list[tuple[str, str]], str | None, dict | None, dict | None]:
    """All checks the norm requires before any operation runs: existence, shape (M8/M9), parity of
    digest, known schema, freshness (per-repo HEAD), dirty worktree (build-flag OR live — B2).
    Partial coverage is reported separately (partial_note) rather than folded into `deviations`
    (m15): whether it actually blocks anything depends on --require-complete, decided by the
    caller. Returns (deviations, partial_note, graph_data, manifest_data) — the data is only fully
    populated once both files at least parse as JSON, so operations can reuse it without
    re-reading from disk."""
    deviations: list[tuple[str, str]] = []

    if not graph_path.is_file():
        deviations.append(("no_graph", f"graph not found: {graph_path}"))
        return deviations, None, None, None
    if not manifest_path.is_file():
        deviations.append(("no_manifest", f"manifest not found: {manifest_path}"))
        return deviations, None, None, None

    # UnicodeDecodeError is caught alongside OSError/JSONDecodeError (M9): a corrupt/binary file on
    # either path must become a deviation, never a raw traceback out of json.loads' own decoding.
    try:
        graph_raw = graph_path.read_bytes()
        graph_data = json.loads(graph_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        deviations.append(("unknown_schema", f"{graph_path}: not valid JSON ({exc})"))
        return deviations, None, None, None
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        deviations.append(("unknown_schema", f"{manifest_path}: not valid JSON ({exc})"))
        return deviations, None, graph_data, None
    if not isinstance(manifest_data, dict):
        deviations.append(("unknown_schema", f"{manifest_path}: root is not a JSON object"))
        return deviations, None, graph_data, None

    for error in validate_manifest_schema(manifest_data):
        deviations.append(("unknown_schema", f"{manifest_path}: {error}"))

    manifest_schema = manifest_data.get("schema_version")
    if manifest_schema != SCHEMA_VERSION:
        deviations.append(
            ("unknown_schema", f"{manifest_path}: unknown schema_version {manifest_schema!r} (expected {SCHEMA_VERSION})")
        )

    for error in validate_graph_structure(graph_data):
        deviations.append(("unknown_schema", f"{graph_path}: {error}"))

    digest = manifest_data.get("digest")
    if isinstance(digest, str) and digest:
        actual = hashlib.sha256(graph_raw).hexdigest()
        if actual != digest:
            deviations.append(("digest_mismatch", f"{graph_path}: digest mismatch (graph={actual}, manifest={digest})"))

    revisions = manifest_data.get("revisions")
    if isinstance(revisions, list):
        for revision in revisions:
            if not isinstance(revision, dict):
                continue  # already reported as a shape error by validate_manifest_schema
            root = revision.get("root")
            commit = revision.get("commit")
            if revision.get("dirty"):
                deviations.append(("dirty", f"root {root}: worktree is dirty per manifest build flag"))
            if not isinstance(root, str) or not root or not isinstance(commit, str) or not commit:
                continue  # ditto — shape already reported
            live_dirty = git_dirty_live(root)
            if live_dirty:
                deviations.append(("dirty", f"root {root}: worktree is dirty (live git status)"))
            head = git_head(root)
            if head is None:
                deviations.append(("stale", f"root {root}: cannot resolve current HEAD"))
            elif head != commit:
                deviations.append(("stale", f"root {root}: manifest commit {commit} != HEAD {head}"))

    partial_note = None
    if manifest_data.get("partial"):
        partial_note = f"{manifest_path}: partial coverage (parsed < seen for some code extension)"

    return deviations, partial_note, graph_data, manifest_data


def resolve_mode(
    mode: str,
    deviations: list[tuple[str, str]],
    allow_stale: bool,
    allow_dirty: bool,
    allow_partial: bool,
) -> tuple[str, str | None, int]:
    """The off/auto/on matrix, applied once all deviations are known. mode=off is handled by the
    caller before this is even reached (it must not read the graph at all); this only decides
    between auto's blanket fallback and on's overridable hard stop."""
    if not deviations:
        return "ok", None, 0
    if mode == "auto":
        # ANY deviation is a fallback in auto — parity means "same result, visible degradation",
        # not "guess which deviations are safe to ignore".
        return "fallback", "; ".join(message for _, message in deviations), 2
    allow = {"stale": allow_stale, "dirty": allow_dirty, "partial": allow_partial}
    active = [(kind, message) for kind, message in deviations if not allow.get(kind, False)]
    if active:
        return "error", "; ".join(message for _, message in active), 3
    return "ok", None, 0


def locator_path_valid(path: str) -> bool:
    return bool(path) and not _PATH_INVALID_CHARS.search(path)


def locator_symbol_valid(symbol: str) -> bool:
    return bool(_SYMBOL_RE.match(symbol))


def normalize_source_file(raw: str, own_roots: list[str]) -> tuple[str, bool]:
    """POSIX-relative-from-root normalization (M10): backslashes become '/'; an absolute path
    inside one of THIS pair's own roots (from its own manifest, not a global --project-root —
    B3/M7) becomes relative to that root; an absolute path outside every root is left as an
    absolute POSIX path and flagged external (M7) instead of silently leaking a foreign filesystem
    layout as if it were an ordinary project-relative locator."""
    posix = raw.replace("\\", "/")
    if not os.path.isabs(posix):
        return posix, False
    abs_real = os.path.realpath(posix)
    for root in own_roots:
        root_norm = root.rstrip(os.sep)
        if abs_real == root_norm or abs_real.startswith(root_norm + os.sep):
            return os.path.relpath(abs_real, root_norm).replace(os.sep, "/"), False
    return abs_real.replace(os.sep, "/"), True


def prepare_sources(sources: list[Source]) -> dict[Key, dict]:
    """Every node, once, decorated with the locator fields every op needs — normalized path,
    external flag (M7), locator_invalid flag (M10) — and keyed by (source_index, node_id) so an id
    collision between two --graph pairs can never merge them (B3). Ops read through this map
    instead of re-deriving locators ad hoc at each call site."""
    by_key: dict[Key, dict] = {}
    for idx, source in enumerate(sources):
        own_roots = sorted({os.path.realpath(r) for r in (source.manifest_data or {}).get("roots") or []})
        for node in (source.graph_data or {}).get("nodes", []):
            node_id = node.get("id")
            if node_id is None:
                continue
            path, external = normalize_source_file(node.get("source_file", ""), own_roots)
            label = node.get("label") or ""
            invalid = not locator_path_valid(path) or (bool(label) and not locator_symbol_valid(label))
            if invalid:
                log(
                    {
                        "level": "warning",
                        "kind": "locator_invalid",
                        "message": f"locator failed grammar validation, kept but flagged: path={path!r} symbol={label!r}",
                    }
                )
            prepared = dict(node)
            prepared["_locator_path"] = path
            prepared["_external"] = external
            prepared["_locator_invalid"] = invalid
            by_key[(idx, node_id)] = prepared
    return by_key


def node_locator(node: dict) -> str:
    """v2 locator as the norm defines it: normalized source_file (M10), plus #label when label is
    non-empty. The adapter never exposes graph node ids — this is the only handle a consumer gets."""
    label = node.get("label") or ""
    path = node.get("_locator_path", node.get("source_file"))
    return f"{path}#{label}" if label else path


def parse_locator(locator: str) -> tuple[str, str | None]:
    if not locator:
        raise AdapterArgError("locator must not be empty")
    if "#" in locator:
        path, symbol = locator.split("#", 1)
        if not path:
            raise AdapterArgError(f"invalid locator {locator!r}: missing path before '#'")
        return path, symbol or None
    return locator, None


def all_links(sources: list[Source]) -> list[tuple[int, dict]]:
    """Every link, tagged with the index of the source pair it came from — an edge's two endpoint
    ids are only ever meaningful within that same pair's own id space (B3)."""
    return [(idx, link) for idx, source in enumerate(sources) for link in (source.graph_data or {}).get("links", [])]


def is_edge_inferred(link: dict) -> bool:
    """Confidence-first classification (B1): the link's own `confidence` field is authoritative
    when present. Only a link with NO confidence field at all falls back to the named
    dictionaries — and an unrecognized relation with no confidence is treated conservatively as
    inferred, never silently trusted as a code fact just because its name happens to be unknown."""
    confidence = link.get("confidence")
    if confidence == "INFERRED":
        return True
    if confidence == "EXTRACTED":
        return False
    relation = link.get("relation")
    if relation in INFERRED_CLASSES:
        return True
    if relation in EXTRACTED_CORE or relation in STRUCTURAL_ON_REQUEST:
        return False
    return True


def edge_allowed_for_hints(link: dict, include_inferred: bool) -> bool:
    """Default traversal/emission policy for neighbors and slice (edges gates purely on
    is_edge_inferred, since its relations are always explicitly named by the caller — see M11):
    nesting (contains/method) is never a default hint regardless of confidence, and inferred edges
    need the explicit flag."""
    if link.get("relation") in STRUCTURAL_ON_REQUEST:
        return False
    return include_inferred if is_edge_inferred(link) else True


def bfs(edges: list[tuple[Key, Key, dict]], origin_keys: set[Key], depth: int, include_inferred: bool) -> set[Key]:
    """Undirected discovery BFS over pre-qualified (source_index, node_id) edges. Isolation across
    --graph pairs (B3) falls out of construction, not a special case here: every edge's two keys
    always share the same source_index, because both were derived from the same link object within
    one (graph, manifest) pair — there is no adjacency entry that could ever cross pairs."""
    if depth <= 0 or not origin_keys:
        return set()
    adjacency: dict[Key, set[Key]] = {}
    for source_key, target_key, link in edges:
        if not edge_allowed_for_hints(link, include_inferred):
            continue
        adjacency.setdefault(source_key, set()).add(target_key)
        adjacency.setdefault(target_key, set()).add(source_key)  # "neighbor" is undirected for discovery

    visited = set(origin_keys)
    frontier = set(origin_keys)
    reached: set[Key] = set()
    for _ in range(depth):
        next_frontier: set[Key] = set()
        for key in frontier:
            next_frontier.update(adjacency.get(key, ()) - visited)
        if not next_frontier:
            break
        reached |= next_frontier
        visited |= next_frontier
        frontier = next_frontier
    return reached


def op_check(sources: list[Source]) -> dict:
    entries = [
        {
            "graph": str(source.graph_path),
            "manifest": str(source.manifest_path),
            "nodes": len((source.graph_data or {}).get("nodes", [])),
            "links": len((source.graph_data or {}).get("links", [])),
            "roots": sorted((source.manifest_data or {}).get("roots") or []),
        }
        for source in sources
    ]
    entries.sort(key=lambda entry: entry["graph"])
    return {"sources": entries}


def op_meta(sources: list[Source]) -> dict:
    entries = []
    for source in sources:
        manifest = source.manifest_data or {}
        entries.append(
            {
                "graph": str(source.graph_path),
                "graphify_version": manifest.get("graphify_version"),
                "schema_version": manifest.get("schema_version"),
                "revisions": manifest.get("revisions"),
                "roots": sorted(manifest.get("roots") or []),
                "excludes": sorted(manifest.get("excludes") or []),
                "digest": manifest.get("digest"),
                "files_seen": manifest.get("files_seen"),
                "files_parsed": manifest.get("files_parsed"),
                "partial": bool(manifest.get("partial")),
            }
        )
    entries.sort(key=lambda entry: entry["graph"])
    return {"sources": entries}


def canonical(path_str: str, base: Path) -> str:
    """Absolute, symlink-resolved form used only for root-membership comparisons (slice / multi-repo
    addressing) — never leaked as a locator, which always stays the normalized _locator_path."""
    path = Path(path_str)
    if not path.is_absolute():
        path = base / path
    return os.path.realpath(path)


def best_matching_root(node_abs: str, roots: list[str]) -> str | None:
    """Longest-prefix match, not 'first path segment' — required so nested checkouts/worktrees
    resolve to the innermost root that actually owns them (norm: multi-repo playbook)."""
    matches = [root for root in roots if node_abs == root or node_abs.startswith(root.rstrip(os.sep) + os.sep)]
    return max(matches, key=len) if matches else None


def op_slice(by_key: dict[Key, dict], sources: list[Source], root_arg: str, project_root: Path, include_inferred: bool) -> dict:
    requested_root = os.path.realpath(root_arg)
    all_roots = sorted(
        {os.path.realpath(root) for source in sources for root in ((source.manifest_data or {}).get("roots") or [])}
    )
    # Base directory for resolving a RELATIVE node path is THIS node's own pair's root (B3) — a
    # single global --project-root would be wrong for any pair beyond the first in a multi-repo call.
    source_bases: list[Path] = []
    for source in sources:
        own_roots = sorted({os.path.realpath(r) for r in (source.manifest_data or {}).get("roots") or []})
        source_bases.append(Path(own_roots[0]) if own_roots else project_root)

    kept_keys: set[Key] = set()
    node_entries = []
    for (idx, node_id), node in by_key.items():
        node_abs = canonical(node.get("_locator_path", ""), source_bases[idx])
        if best_matching_root(node_abs, all_roots) != requested_root:
            continue
        kept_keys.add((idx, node_id))
        entry = {"locator": node_locator(node), "file_type": node.get("file_type")}
        if node.get("_external"):
            entry["external"] = True
        if node.get("_locator_invalid"):
            entry["locator_invalid"] = True
        node_entries.append(entry)
    node_entries.sort(key=lambda entry: entry["locator"])

    kept_links = []
    for idx, link in all_links(sources):
        source_key, target_key = (idx, link.get("source")), (idx, link.get("target"))
        if source_key not in kept_keys or target_key not in kept_keys:
            continue
        if not edge_allowed_for_hints(link, include_inferred):
            continue
        entry = {
            "source": node_locator(by_key[source_key]),
            "target": node_locator(by_key[target_key]),
            "relation": link["relation"],
        }
        if is_edge_inferred(link):
            entry["inferred"] = True
        kept_links.append(entry)
    kept_links.sort(key=lambda entry: (entry["source"], entry["target"], entry["relation"]))

    return {"root": root_arg, "nodes": node_entries, "links": kept_links}


def op_neighbors(by_key: dict[Key, dict], sources: list[Source], locator_arg: str, depth: int, include_inferred: bool) -> dict:
    if depth < 0:
        raise AdapterArgError("--depth must be >= 0")
    path, symbol = parse_locator(locator_arg)
    # Match against the NORMALIZED path (M10), not the raw source_file — a caller only ever sees
    # normalized locators from prior adapter output, so round-tripping one back in via --of must
    # compare like for like.
    origin_keys = {
        key
        for key, node in by_key.items()
        if node.get("_locator_path") == path and (symbol is None or (node.get("label") or "") == symbol)
    }

    edges: list[tuple[Key, Key, dict]] = []
    for idx, link in all_links(sources):
        source_id, target_id = link.get("source"), link.get("target")
        if source_id is None or target_id is None:
            continue
        edges.append(((idx, source_id), (idx, target_id), link))

    extracted_keys = bfs(edges, origin_keys, depth, include_inferred=False)
    full_keys = bfs(edges, origin_keys, depth, include_inferred=True) if include_inferred else extracted_keys
    inferred_only = full_keys - extracted_keys

    result = []
    # sorted(): the skip-warnings below go to stderr as they are hit — iterating the raw set
    # would leak hash-seed ordering into the diagnostic stream, breaking run-to-run comparability.
    for key in sorted(full_keys):
        node = by_key.get(key)
        if node is None:
            # Dangling edge endpoint (e.g. an import target with no materialized node) — never
            # resolvable to a locator, so it cannot be reported as a "neighbor" (M9's tolerant
            # stance on dangling endpoints; see validate_graph_structure's docstring). Warned
            # about with the same wording as op_edges, so both ops degrade equally loudly.
            log({"level": "warning", "kind": "dangling_endpoint", "message": f"edge with unresolved endpoint skipped: node {key[1]!r}"})
            continue
        entry = {"locator": node_locator(node)}
        if node.get("_external"):
            entry["external"] = True
        if node.get("_locator_invalid"):
            entry["locator_invalid"] = True
        if key in inferred_only:
            entry["inferred"] = True
        result.append(entry)
    result.sort(key=lambda entry: (entry["locator"], entry.get("inferred", False)))
    return {"of": locator_arg, "depth": depth, "neighbors": result}


def op_edges(by_key: dict[Key, dict], sources: list[Source], relation_csv: str, include_inferred: bool) -> dict:
    requested = {value.strip() for value in relation_csv.split(",") if value.strip()}
    if not requested:
        raise AdapterArgError("--relation must list at least one relation")

    result = []
    for idx, link in all_links(sources):
        relation = link.get("relation")
        if relation not in requested:
            continue
        if is_edge_inferred(link) and not include_inferred:
            log(
                {
                    "level": "info",
                    "message": f"skipped inferred relation {relation!r} requested without --include-inferred",
                }
            )
            continue
        source_node = by_key.get((idx, link.get("source")))
        target_node = by_key.get((idx, link.get("target")))
        if source_node is None or target_node is None:
            # Same structured shape as op_neighbors' dangling warning: name the missing node id(s),
            # not the whole link repr — both ops must degrade identically for diff-able diagnostics.
            missing = [link.get(side) for side, node in (("source", source_node), ("target", target_node)) if node is None]
            for node_id in missing:
                log({"level": "warning", "kind": "dangling_endpoint", "message": f"edge with unresolved endpoint skipped: node {node_id!r}"})
            continue
        entry = {
            "source": node_locator(source_node),
            "target": node_locator(target_node),
            "relation": relation,
        }
        if "weight" in link:
            entry["weight"] = link["weight"]
        if is_edge_inferred(link):
            entry["inferred"] = True
        result.append(entry)
    result.sort(key=lambda entry: (entry["source"], entry["target"], entry["relation"]))
    return {"relations": sorted(requested), "edges": result}


def build_parser() -> ArgParser:
    common = ArgParser(add_help=False)
    common.add_argument(
        "--graph", action="append", default=[], dest="graphs", type=Path,
        help="path to a graph.json; repeat for multi-repo (manifest is graph.meta.json beside it)",
    )
    common.add_argument("--mode", choices=("off", "auto", "on"), default="auto")
    common.add_argument("--include-inferred", action="store_true")
    common.add_argument("--allow-stale", action="store_true")
    common.add_argument("--allow-dirty", action="store_true")
    common.add_argument("--allow-partial", action="store_true")
    common.add_argument(
        "--require-complete", action="store_true",
        help="treat manifest partial=true as a deviation (m15); without this flag it is a warning",
    )
    common.add_argument("--project-root", type=Path, default=None)

    parser = ArgParser(prog="graph-adapter.py")
    sub = parser.add_subparsers(dest="operation", required=True)

    sub.add_parser("check", parents=[common])
    sub.add_parser("meta", parents=[common])

    slice_parser = sub.add_parser("slice", parents=[common])
    slice_parser.add_argument("--root", required=True)

    neighbors_parser = sub.add_parser("neighbors", parents=[common])
    neighbors_parser.add_argument("--of", dest="locator", required=True)
    neighbors_parser.add_argument("--depth", type=int, default=1)

    edges_parser = sub.add_parser("edges", parents=[common])
    edges_parser.add_argument("--relation", required=True)

    return parser


def run(args: argparse.Namespace) -> int:
    if args.mode == "off":
        # off means "not read", full stop — no file access, no argument requirements beyond what
        # argparse itself demands, always this exact reason (M4: checked before --graph/allow-*).
        log({"level": "info", "message": "mode=off: graph not read"})
        return emit("fallback", "mode=off", {}, 2)

    if not args.graphs:
        raise AdapterArgError("at least one --graph is required")
    if (args.allow_stale or args.allow_dirty or args.allow_partial) and args.mode != "on":
        raise AdapterArgError("--allow-stale/--allow-dirty/--allow-partial require --mode on")

    # A missing graphify binary is NOT a deviation (norm updated 16.07): reading a valid, fresh
    # graph needs no binary at all — freshness is already gated by the stale check, and a graph
    # that DOES go stale with no binary around surfaces as stale anyway. "No binary" is a hard
    # error only for BUILDING (graph-build.sh, exit 3). Here it is reported (binary_available on
    # check/meta) and warned about on every operation, so callers deciding whether to rebuild
    # still see it without losing a perfectly readable graph.
    binary_available = shutil.which("graphify") is not None
    if not binary_available:
        log(
            {
                "level": "warning",
                "kind": "no_binary",
                "message": "graphify binary not found in PATH — existing graph stays readable, but cannot be rebuilt",
            }
        )

    project_root = (args.project_root or Path.cwd()).resolve()

    sources: list[Source] = []
    deviations: list[tuple[str, str]] = []
    partial_notes: list[str] = []
    for graph_path in args.graphs:
        manifest_path = graph_path.parent / "graph.meta.json"
        source_deviations, partial_note, graph_data, manifest_data = collect_deviations(graph_path, manifest_path)
        deviations.extend(source_deviations)
        if partial_note:
            partial_notes.append(partial_note)
        sources.append(Source(graph_path, manifest_path, graph_data, manifest_data))

    if args.require_complete:
        # Only a caller that declared it needs completeness turns partial into a real deviation
        # (m15) — everyone else gets a visible warning instead of every polyglot repo permanently
        # fallback-ing just because one language extension has thinner coverage.
        deviations.extend(("partial", note) for note in partial_notes)
    elif partial_notes:
        for note in partial_notes:
            log({"level": "warning", "kind": "partial", "message": note})

    for kind, message in deviations:
        log({"level": "deviation", "kind": kind, "message": message})

    status, reason, exit_code = resolve_mode(
        args.mode, deviations, args.allow_stale, args.allow_dirty, args.allow_partial
    )
    if status != "ok":
        return emit(status, reason, {}, exit_code)

    by_key = prepare_sources(sources)

    if args.operation == "check":
        data = op_check(sources)
        data["binary_available"] = binary_available  # environment-global, hence not per-source
    elif args.operation == "meta":
        data = op_meta(sources)
        data["binary_available"] = binary_available
    elif args.operation == "slice":
        data = op_slice(by_key, sources, args.root, project_root, args.include_inferred)
    elif args.operation == "neighbors":
        data = op_neighbors(by_key, sources, args.locator, args.depth, args.include_inferred)
    elif args.operation == "edges":
        data = op_edges(by_key, sources, args.relation, args.include_inferred)
    else:  # pragma: no cover — argparse restricts operation to the subparsers registered above
        raise AdapterArgError(f"unknown operation {args.operation!r}")

    if partial_notes:
        data["partial"] = True

    return emit("ok", None, data, 0)


def main() -> int:
    try:
        args = build_parser().parse_args()
        return run(args)
    except AdapterArgError as exc:
        return emit_error(str(exc))
    except Exception as exc:  # noqa: BLE001 - last-resort net: never a raw traceback (M9)
        # Everything upstream is already defensive (isinstance guards throughout validation, no
        # bare dict/list indexing on untrusted input) — this only catches whatever a future,
        # currently-unanticipated malformed-input shape slips past those checks, still exiting
        # through the one JSON envelope contract instead of a Python traceback on stdout.
        log({"level": "error", "message": f"unexpected internal error: {exc!r}"})
        return emit_error(f"internal error: {exc}")


if __name__ == "__main__":
    sys.exit(main())
