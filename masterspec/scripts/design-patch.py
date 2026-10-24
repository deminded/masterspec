#!/usr/bin/env python3
"""Snapshot draft design inputs and plan a bounded recheck; never certify a layer."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml


LAYERS = ("01-requirements", "02-specifications", "04-decisions")
GLOBALS = ("00-glossary.md", "masterspec-config.yaml", "recover/_reconciliation.yaml")
KERNEL = Path(__file__).resolve().parents[1]
SCHEMA = 1


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def bounded(root: Path, path: Path) -> Path:
    require(path.resolve().is_relative_to(root), f"path escapes root: {path}")
    require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(),
            f"linked path: {path}")
    return path


def walk_files(root: Path, path: Path) -> list[Path]:
    bounded(root, path)
    if not path.exists():
        return []
    if path.is_file():
        return [path]
    result = []
    for child in sorted(path.iterdir()):
        if child.name in {"__pycache__", ".pytest_cache", ".git"}:
            continue
        result.extend(walk_files(root, child))
    return result


def policy_roots(root: Path, extra: list[str]) -> list[Path]:
    paths = [KERNEL]
    paths.extend(KERNEL.parent / name / "SKILL.md" for name in (
        "masterspec-derive", "masterspec-evolve", "masterspec-verify", "masterspec-gen",
        "masterspec-accept", "masterspec-apply-change"
    ))
    config = root / "masterspec-config.yaml"
    if config.exists():
        data = yaml.safe_load(bounded(root, config).read_text(encoding="utf-8")) or {}
        require(isinstance(data, dict), "masterspec-config.yaml must be a mapping")
        packs = data.get("guardrail_packs", [])
        require(isinstance(packs, list), "guardrail_packs must be a list")
        for pack in packs:
            require(isinstance(pack, dict) and isinstance(pack.get("path"), str),
                    "each guardrail pack must declare a path")
            paths.append(root / pack["path"])
    paths.extend(root / path for path in extra)
    return sorted({path.resolve() for path in paths})


def rules_snapshot(root: Path, extra: list[str]) -> dict:
    rules = {}
    for path in policy_roots(root, extra):
        require(path.exists(), f"unavailable rules: {path}")
        base = path if path.is_dir() else path.parent
        rules[str(path)] = {
            file.relative_to(base).as_posix(): digest(file.read_bytes())
            for file in walk_files(base, path)
            if file.suffix != ".pyc"
        }
    return rules


def machine_refs(value, seen: set[int] | None = None):
    seen = seen if seen is not None else set()
    if not isinstance(value, (dict, list)) or id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"$ref", "$dynamicRef"} and isinstance(item, str):
                yield item
            yield from machine_refs(item, seen)
    else:
        for item in value:
            yield from machine_refs(item, seen)


def input_contents(root: Path) -> dict[str, bytes]:
    result = {}
    for name in (*LAYERS, *GLOBALS):
        for path in walk_files(root, root / name):
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def snapshot(root: Path, extra_rules: list[str] | None = None, *,
             contents: dict[str, bytes] | None = None) -> dict:
    root = root.resolve()
    require(root.is_dir(), f"factory not found: {root}")
    files, texts, slugs = {}, {}, {}
    contents = input_contents(root) if contents is None else contents
    for key, raw in sorted(contents.items()):
        path = bounded(root, root / key)
        entry = {"sha256": digest(raw), "deps": []}
        files[key] = entry
        if path.suffix != ".md" or path.parts[len(root.parts)] not in LAYERS:
            continue
        text = raw.decode("utf-8-sig")
        match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
        require(match is not None, f"missing artifact frontmatter: {key}")
        meta = yaml.safe_load(match[1])
        require(isinstance(meta, dict), f"invalid artifact frontmatter: {key}")
        require(all(isinstance(meta.get(field), str) and meta[field] for field in ("type", "status")),
                f"missing artifact type/status: {key}")
        slug = meta.get("slug")
        require(isinstance(slug, str) and re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+", slug),
                f"missing/invalid artifact slug: {key}")
        require(slug not in slugs, f"duplicate artifact slug: {slug}")
        slugs[slug] = key
        texts[key] = text
        entry["meta"] = {field: meta.get(field) for field in (
            "slug", "type", "status", "sidecar", "sidecar_format", "contract_origin"
        )}
    unresolved = []
    mentions = re.compile(r"(?<![\w-])(?:" + "|".join(
        re.escape(slug) for slug in sorted(slugs, key=len, reverse=True)
    ) + r")(?![\w-])") if slugs else None
    for key, text in texts.items():
        entry = files[key]
        deps = {slugs[match[0]] for match in mentions.finditer(text)} if mentions else set()
        deps.discard(key)
        for target in re.findall(r"->\s*([a-z][a-z0-9]*(?:-[a-z0-9]+)+)", text):
            if target not in slugs:
                unresolved.append(f"{key}: unknown slug {target}")
        sidecar = entry["meta"]["sidecar"]
        if sidecar:
            require(isinstance(sidecar, str), f"sidecar must be a path: {key}")
            candidate = bounded(root, root / key).parent / sidecar
            bounded(root, candidate)
            sidecar_key = candidate.resolve().relative_to(root).as_posix()
            require(sidecar_key in files and "meta" not in files[sidecar_key],
                    f"missing/non-machine sidecar: {key}: {sidecar}")
            deps.add(sidecar_key)
        entry["deps"] = sorted(deps)
    for key, entry in files.items():
        if not key.startswith("02-specifications/") or Path(key).suffix not in {".json", ".yaml", ".yml"}:
            continue
        text = contents[key].decode("utf-8-sig")
        value = json.loads(text) if key.endswith(".json") else yaml.safe_load(text)
        deps = set()
        for ref in machine_refs(value):
            parsed = urlsplit(ref)
            if parsed.scheme or parsed.netloc or parsed.query:
                unresolved.append(f"{key}: non-local reference {ref}")
            elif parsed.path:
                candidate = bounded(root, (root / key).parent / unquote(parsed.path))
                target = candidate.resolve().relative_to(root).as_posix()
                if target in files:
                    deps.add(target)
                else:
                    unresolved.append(f"{key}: unavailable reference {ref}")
        entry["deps"] = sorted(deps)
    return {
        "schema": SCHEMA,
        "factory_root": str(root),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "extra_rules": sorted(extra_rules or []),
        "rules": rules_snapshot(root, extra_rules or []),
        "files": files,
        "unresolved": sorted(set(unresolved)),
    }


def state_digest(state: dict) -> str:
    keys = ("files", "rules", "unresolved", "workflow", "change_root", "factory_digest",
            "change_inputs", "change_contract", "change_status")
    return digest(json.dumps({name: state[name] for name in keys if name in state},
                             sort_keys=True, ensure_ascii=False).encode("utf-8"))


def closure(seeds: set[str], graph: dict[str, set[str]]) -> set[str]:
    found, pending = set(seeds), list(seeds)
    while pending:
        for neighbour in graph.get(pending.pop(), set()) - found:
            found.add(neighbour)
            pending.append(neighbour)
    return found


def plan_states(root: Path, baseline: dict, current: dict, targets: list[str] | None = None,
                *, workflow: str = "derive") -> dict:
    root = root.resolve()
    require(isinstance(baseline, dict), "baseline must be an object")
    require(baseline.get("schema") == SCHEMA, "unknown baseline schema")
    require(baseline.get("factory_root") == str(root), "baseline belongs to another factory")
    require(isinstance(baseline.get("extra_rules"), list)
            and all(isinstance(path, str) for path in baseline["extra_rules"]), "invalid baseline rules paths")
    require(isinstance(baseline.get("rules"), dict)
            and isinstance(baseline.get("unresolved"), list), "invalid baseline rules/references")
    require(current.get("factory_root") == str(root), "current inputs belong to another factory")
    old, new = baseline["files"], current["files"]
    require(isinstance(old, dict), "invalid baseline inventory")
    for key, entry in old.items():
        require(isinstance(entry, dict) and re.fullmatch(r"[a-f0-9]{64}", entry.get("sha256", ""))
                and isinstance(entry.get("deps"), list)
                and all(isinstance(dep, str) for dep in entry["deps"]), f"invalid baseline entry: {key}")
        require("meta" not in entry or (isinstance(entry["meta"], dict)
                and all(isinstance(entry["meta"].get(field), str)
                        for field in ("slug", "type", "status"))), f"invalid baseline metadata: {key}")
    changed = {key for key in old.keys() | new.keys()
               if old.get(key, {}).get("sha256") != new.get(key, {}).get("sha256")}
    graph, reverse = {}, {}
    for state in (old, new):
        for key, entry in state.items():
            graph.setdefault(key, set()).update(entry["deps"])
            for dep in entry["deps"]:
                reverse.setdefault(dep, set()).add(key)
    by_slug = {entry["meta"]["slug"]: key for key, entry in new.items() if "meta" in entry}
    anchors = set()
    for target in targets or []:
        key = by_slug.get(target, target.replace("\\", "/"))
        require(key in new and "meta" in new[key], f"unknown patch target: {target}")
        anchors.add(key)
    owners = {}
    for state in (old, new):
        for key, entry in state.items():
            if entry.get("meta", {}).get("sidecar"):
                for dep in entry["deps"]:
                    if dep in state and "meta" not in state[dep]:
                        owners.setdefault(dep, set()).add(key)
    touched = {key for key in changed if "meta" in new.get(key, old.get(key, {}))}
    for key in changed:
        touched.update(owners.get(key, set()))
    reasons, evolve = [], []
    if workflow == "derive":
        for key in sorted(touched | anchors):
            for state in (old, new):
                if key in state and state[key].get("meta", {}).get("status") != "draft":
                    evolve.append(f"non-draft artifact: {key}")
    if old.keys() != new.keys():
        reasons.append("file inventory changed (add/delete/rename)")
    if baseline["rules"] != current["rules"]:
        reasons.append("verification rules or guardrail packs changed")
    if baseline["unresolved"] or current["unresolved"]:
        reasons.append("dependency graph has unresolved references")
    for key in sorted(changed):
        allowed = ("01-requirements/", "02-specifications/") if workflow == "evolve" else ("02-specifications/",)
        if not key.startswith(allowed):
            reasons.append(f"change outside draft specification layer: {key}")
        elif "meta" in old.get(key, {}) and "meta" in new.get(key, {}):
            if old[key]["meta"] != new[key]["meta"]:
                reasons.append(f"artifact identity/status/sidecar metadata changed: {key}")
        elif key not in owners:
            reasons.append(f"changed file has no declared artifact owner: {key}")
        elif Path(key).suffix not in {".yaml", ".yml", ".json"}:
            reasons.append(f"changed machine format requires full review: {key}")
        for owner in owners.get(key, set()):
            if new.get(owner, old.get(owner, {})).get("meta", {}).get("contract_origin") == "imported":
                reasons.append(f"imported sidecar is immutable: {key}")
    impacted = closure(changed | anchors, reverse)
    artifacts = {key for key in impacted if "meta" in new.get(key, old.get(key, {}))}
    context = closure(impacted, graph) - impacted
    route = "evolve" if evolve else "full" if reasons else "patch" if changed else "noop"
    return {
        "schema": SCHEMA, "factory_root": str(root), "route": route,
        "reasons": sorted(set(evolve + reasons)),
        "baseline_digest": state_digest(baseline), "current_digest": state_digest(current),
        "changed_files": sorted(changed), "write_artifacts": sorted(touched),
        "verify_artifacts": sorted(artifacts), "verify_files": sorted(impacted),
        "read_only_context": sorted(context),
        "semantic_review_required": True,
    }


def plan(root: Path, baseline: dict, targets: list[str] | None = None) -> dict:
    require(isinstance(baseline, dict), "baseline must be an object")
    require("workflow" not in baseline, "change baseline requires change-plan")
    return plan_states(root, baseline, snapshot(root, baseline.get("extra_rules")), targets)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("snapshot", help="capture bytes, not a verification certificate")
    capture.add_argument("factory", type=Path)
    capture.add_argument("--out", type=Path, required=True)
    capture.add_argument("--rules", action="append", default=[], help="additional active rules path")
    check = sub.add_parser("plan", help="include every changed file and old/new reverse dependents")
    check.add_argument("factory", type=Path)
    check.add_argument("--baseline", type=Path, required=True)
    check.add_argument("--target", action="append", default=[], help="slug or factory-relative path")
    check.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            value = snapshot(args.factory, args.rules)
            write_json(args.out, value)
            print(f"Design baseline: {args.out}; files={len(value['files'])}; not a certificate")
            return 0
        value = plan(args.factory, json.loads(args.baseline.read_text(encoding="utf-8")), args.target)
        if args.out:
            write_json(args.out, value)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value["route"] in {"patch", "noop"} else 1
    except (OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError) as error:
        value = {"route": "full", "reasons": [str(error)]}
        if args.command == "plan" and args.out:
            write_json(args.out, value)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
