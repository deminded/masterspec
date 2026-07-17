#!/usr/bin/env bash
# Build wrapper: runs graphify per root, then writes the graph.meta.json trust manifest that
# graph-adapter.py requires beside every graph.json. One (graph, manifest) pair per root, written
# where graphify already puts graph.json (<root>/graphify-out/graph.json) — no merging across
# roots, because cross-repo edges don't exist by construction (tree-sitter never sees network
# calls or foreign packages) and the adapter itself is what stitches multiple repos together via
# repeated --graph flags, not graphify's own merge-graphs.
set -euo pipefail

DEFAULT_EXCLUDES=(vendor node_modules build dist target)

usage() {
  echo "Usage: $(basename "$0") [--exclude PATTERN]... <root> [<root> ...]" >&2
}

excludes=()
roots=()
while [ $# -gt 0 ]; do
  case "$1" in
    --exclude)
      [ $# -ge 2 ] || { usage; exit 3; }
      excludes+=("$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      roots+=("$1")
      shift
      ;;
  esac
done

if [ "${#roots[@]}" -eq 0 ]; then
  usage
  exit 3
fi

if ! command -v graphify >/dev/null 2>&1; then
  echo "graph-build: graphify not found in PATH — install it before building the graph" >&2
  exit 3
fi

graphify_version="$(graphify --version 2>/dev/null | awk '{print $NF}')"

# M5: pass excludes to graphify natively IF it advertises support — verified against the real
# graphify 0.9.17 `update --help` (no such flag exists today; `update` only takes --force/
# --no-cluster), so this is a forward-compatible best-effort optimization, never the correctness
# mechanism. Correctness comes from the deterministic post-build filter below regardless.
exclude_flag_supported=false
update_help="$(graphify update --help 2>&1 || true)"
if printf '%s' "$update_help" | grep -qi -- '--exclude'; then
  exclude_flag_supported=true
fi

# Empty-safe JSON array of --exclude values, built without a bash/JSON quoting dance.
excludes_json="$(printf '%s\n' "${excludes[@]+"${excludes[@]}"}" | python3 -c '
import json, sys
print(json.dumps([line.rstrip("\n") for line in sys.stdin if line.strip()]))
')"

for root in "${roots[@]}"; do
  if [ ! -d "$root" ]; then
    echo "graph-build: root not found: $root" >&2
    exit 3
  fi
  resolved_root="$(realpath "$root")"
  if ! git -C "$resolved_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "graph-build: $resolved_root is not a git worktree — freshness cannot be tracked" >&2
    exit 3
  fi

  graphify_cmd=(graphify update "$resolved_root")
  if [ "$exclude_flag_supported" = true ]; then
    for pattern in "${excludes[@]+"${excludes[@]}"}"; do
      graphify_cmd+=(--exclude "$pattern")
    done
  fi
  "${graphify_cmd[@]}"

  graph_path="$resolved_root/graphify-out/graph.json"
  if [ ! -f "$graph_path" ]; then
    echo "graph-build: graphify did not produce $graph_path" >&2
    exit 3
  fi
  manifest_path="$resolved_root/graphify-out/graph.meta.json"

  commit="$(git -C "$resolved_root" rev-parse HEAD)"
  dirty=false
  [ -n "$(git -C "$resolved_root" status --short)" ] && dirty=true

  python3 - "$resolved_root" "$graph_path" "$manifest_path" "$graphify_version" \
    "$commit" "$dirty" "$excludes_json" "${DEFAULT_EXCLUDES[@]}" <<'PY'
import fnmatch
import hashlib
import json
import os
import sys
from pathlib import Path

(root, graph_path_str, manifest_path_str, graphify_version,
 commit, dirty_flag, excludes_json, *default_excludes) = sys.argv[1:]
excludes = json.loads(excludes_json)
graph_path = Path(graph_path_str)
manifest_path = Path(manifest_path_str)

# Full effective exclude list written to the manifest (M5): caller excludes + our own defaults +
# the bookkeeping dirs that are never source regardless of what the caller asked for. "generated"
# and "graphify-out" are graphify's own conventions for "not source"; ".git" is bookkeeping noise.
effective_excludes = sorted(set(default_excludes) | set(excludes) | {"generated", "graphify-out", ".git"})
skip_dirs = set(effective_excludes)

root_path = Path(root)
root_real = os.path.realpath(root_path)

files_seen: dict[str, int] = {}
excluded_symlinks: list[str] = []
for current, dirs, files in os.walk(root_path, followlinks=False):
    dirs[:] = sorted(d for d in dirs if d not in skip_dirs)
    for name in sorted(files):
        path = Path(current) / name
        if path.is_symlink():
            target_real = os.path.realpath(path)
            if target_real != root_real and not target_real.startswith(root_real + os.sep):
                # M7: a symlink pointing outside root is never counted as seen/parsed — recorded
                # by name instead of silently disappearing.
                excluded_symlinks.append(path.relative_to(root_path).as_posix())
                continue
        try:
            with path.open("rb") as handle:
                head = handle.read(200)
        except OSError:
            continue
        if b"@generated" in head:  # header marker, per the design's generated-file exclusion
            continue
        ext = path.suffix
        if ext:
            files_seen[ext] = files_seen.get(ext, 0) + 1


def is_excluded(source_file: str) -> bool:
    """Path-component match against effective_excludes (a whole directory-name segment, the way a
    human reads '--exclude vendor'), plus a glob fallback for wildcard patterns a caller might
    pass (e.g. '*.min.js') — not a naive substring test, which would over-match."""
    parts = Path(source_file).parts
    for pattern in effective_excludes:
        if pattern in parts:
            return True
        if any(ch in pattern for ch in "*?[") and fnmatch.fnmatch(source_file, pattern):
            return True
    return False


graph = json.loads(graph_path.read_text(encoding="utf-8"))
nodes = graph.get("nodes", [])
kept_nodes = [n for n in nodes if not is_excluded(n.get("source_file", ""))]
kept_ids = {n["id"] for n in kept_nodes if "id" in n}
# A link is dropped ONLY when one of its endpoints existed in the graph and was cut by THIS
# filter — requiring both endpoints to be materialized nodes would also delete graphify's own
# routine dangling edges (e.g. `imports os` whose target node never exists), silently losing
# real code facts the adapter is expected to tolerate (see ROADMAP block 1's dangling proviso).
removed_ids = {n["id"] for n in nodes if "id" in n} - kept_ids
kept_links = [
    link for link in graph.get("links", [])
    if link.get("source") not in removed_ids and link.get("target") not in removed_ids
]
graph["nodes"] = kept_nodes
graph["links"] = kept_links

# M5: graphify itself has no --exclude support to rely on (verified against 0.9.17's --help), so
# this deterministic post-filter is the actual exclude mechanism, not a belt-and-suspenders extra —
# rewritten atomically (m16: tmp file in the same dir + os.replace, never a half-written file).
filtered_bytes = json.dumps(graph, sort_keys=True).encode("utf-8")
tmp_graph = graph_path.parent / (graph_path.name + ".tmp")
tmp_graph.write_bytes(filtered_bytes)
os.replace(tmp_graph, graph_path)
digest = hashlib.sha256(filtered_bytes).hexdigest()  # recomputed from the FILTERED file, not the pre-filter one

# files_parsed only tallies extensions graphify actually emitted (post-filter) nodes for — that
# avoids having to hardcode tree-sitter's ~36-language extension list just to tell "code" from
# "not code" here; CODE_EXTS (below) is only used for the partial predicate, not this tally.
parsed_files = sorted({n["source_file"] for n in kept_nodes if n.get("source_file")})
files_parsed: dict[str, int] = {}
for source_file in parsed_files:
    ext = Path(source_file).suffix
    if ext:
        files_parsed[ext] = files_parsed.get(ext, 0) + 1

# Explicit code-extension list (M6), documented here rather than left implicit: a language whose
# files were SEEN but NEVER emitted a single parsed node (e.g. a .go file when graphify only knows
# Python) must still trigger partial — iterating files_parsed's own keys alone is blind to that,
# since an entirely-unparsed extension never appears there at all.
CODE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".kts",
    ".rb", ".php", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift", ".scala",
    ".sh", ".sql", ".lua", ".pl", ".m", ".mm",
}
partial = any(
    files_parsed.get(ext, 0) < files_seen[ext]
    for ext in files_seen
    if ext in CODE_EXTS
)

manifest = {
    "graphify_version": graphify_version,
    "schema_version": 1,
    "revisions": [{"root": root, "commit": commit, "dirty": dirty_flag == "true"}],
    "roots": [root],
    "excludes": effective_excludes,
    "digest": digest,
    "files_seen": dict(sorted(files_seen.items())),
    "files_parsed": dict(sorted(files_parsed.items())),
    "partial": partial,
    "excluded_symlinks": sorted(excluded_symlinks),
}
tmp_manifest = manifest_path.parent / (manifest_path.name + ".tmp")
tmp_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(tmp_manifest, manifest_path)  # m16: atomic — a reader never observes a half-written manifest
print(f"graph-build: wrote {manifest_path}", file=sys.stderr)
PY
done
