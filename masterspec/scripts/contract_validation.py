"""Offline OpenAPI/AsyncAPI contract validation using pinned upstream JSON Schemas.

JSON Schema validation is delegated to jsonschema. The traversal below only resolves
contract references; it deliberately treats example/default/const values as data.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlsplit
from urllib.request import url2pathname

import yaml


SCHEMAS = Path(__file__).with_name("schemas")
FORM = re.compile(r"^(openapi|asyncapi)(?:[-\s]?v?(\d+)(?:\.(\d+|x))?(?:\.(\d+|x))?)?$", re.I)
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].+)?$")
SCHEMA_MAPS = {"$defs", "definitions", "properties", "patternProperties", "dependentSchemas"}
SCHEMA_ARRAYS = {"allOf", "anyOf", "oneOf", "prefixItems"}
SCHEMA_VALUES = {
    "items", "additionalItems", "additionalProperties", "unevaluatedProperties",
    "unevaluatedItems", "contains", "propertyNames", "not", "if", "then", "else", "contentSchema",
}
API_MAPS = {
    "paths", "webhooks", "channels", "operations", "responses", "headers", "requestBodies",
    "callbacks", "pathItems", "messages", "securitySchemes", "links", "examples",
    "parameters", "servers", "variables",
}


def pointer(parts: tuple = ()) -> str:
    return "#" + "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def diagnostic(path: Path, parts: tuple, message: str) -> str:
    return f"{path}{pointer(parts)}: {message} (F2)"


def _join(scope: str, ref: str) -> str:
    # urllib.urljoin drops an opaque URI base (e.g. urn:) for fragment references.
    return urldefrag(scope)[0] + ref if ref.startswith("#") else urljoin(scope, ref)


def _children(node: dict, role: str):
    """Assign reference-bearing contexts, without interpreting a data payload as a schema."""
    for key, value in node.items():
        child = "data"
        if role == "schema-map":
            child = "schema"
        elif role in {"api-map", "extension-map", "message-map"}:
            child = "message" if role == "message-map" else "api"
            if role == "extension-map" and isinstance(key, str) and key.startswith("x-"):
                child = "data"
        elif role == "schema":
            if key in SCHEMA_MAPS or (key == "dependencies" and isinstance(value, dict)):
                child = "schema-map"
            elif key in SCHEMA_ARRAYS or key in SCHEMA_VALUES:
                child = "schema"
            elif key == "schema" and "schemaFormat" in node:
                child = "schema"
        elif role in {"api", "components", "message"}:
            if not isinstance(key, str) or key.startswith("x-"):
                pass
            elif key in {"example", "default", "const", "enum", "value"}:
                pass
            elif key == "examples" and isinstance(value, list):
                pass
            elif key == "components":
                child = "components"
            elif key == "schemas" and role == "components":
                child = "schema-map"
            elif key in {"schema", "payload"} or (key == "headers" and role == "message"):
                child = "schema"
            elif key == "message" or (role == "message" and key in {"oneOf", "traits"}):
                child = "message"
            elif key in {"messages", "messageTraits"}:
                child = "message-map"
            elif key in API_MAPS and isinstance(value, dict):
                child = "extension-map" if key in {"paths", "responses"} and role != "components" else "api-map"
            else:
                child = "api"
        yield key, value, child


def _json_shape(value: object, parts: tuple = (), ancestors: frozenset = frozenset()) -> tuple[tuple, str] | None:
    if isinstance(value, (dict, list)):
        if id(value) in ancestors:
            return parts, "cyclic YAML aliases are not JSON values"
        ancestors = ancestors | {id(value)}
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                return parts, "YAML mapping keys must be JSON strings (quote numeric response codes)"
            if error := _json_shape(item, parts + (key,), ancestors):
                return error
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if error := _json_shape(item, parts + (index,), ancestors):
                return error
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        return parts, f"YAML value {type(value).__name__} is not a JSON value"
    return None


def _bundle():
    from jsonschema_specifications import REGISTRY
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT4, DRAFT7, DRAFT202012
    from referencing.exceptions import NoSuchResource

    def unavailable(uri):
        raise NoSuchResource(ref=uri)

    registry = Registry(retrieve=unavailable).with_resources(REGISTRY.items())
    manifest = json.loads((SCHEMAS / "manifest.json").read_text(encoding="utf-8"))
    documents = {}
    for filename, metadata in manifest.items():
        raw = (SCHEMAS / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
            raise ValueError(f"bundled schema digest mismatch: {filename}")
        if not filename.endswith(".json"):
            continue
        schema = json.loads(raw)
        documents[filename] = schema
        dialect = schema.get("$schema", "")
        specification = DRAFT4 if "draft-04" in dialect else DRAFT7 if "draft-07" in dialect else DRAFT202012
        resource = Resource.from_contents(schema, default_specification=specification)
        registry = registry.with_resource(metadata["url"], resource)
        if identifier := schema.get("$id", schema.get("id")):
            registry = registry.with_resource(identifier, resource)
    return documents, registry.crawl()


class _References:
    def __init__(self, sidecar: Path, document: dict):
        self.documents = {}
        self.resources = {}
        self.anchors = {}
        self.scopes = {}
        self.locations = {}
        self.origins = {}
        self.uses = {}
        self.errors = []
        self.add_document(sidecar.resolve(), document)

    def add_document(self, path: Path, document: object):
        uri = path.as_uri()
        self.documents[uri] = document
        self.resources[uri] = (path, document)

        def index(node, role, scope, parts=()):
            if role == "data":
                return
            if isinstance(node, list):
                for number, item in enumerate(node):
                    index(item, role, scope, parts + (number,))
            elif isinstance(node, dict):
                self.scopes[id(node)] = scope
                self.locations[id(node)] = parts
                if role == "schema":
                    if isinstance(node.get("$id"), str):
                        scope = _join(scope, node["$id"])
                        self.resources[urldefrag(scope)[0]] = (path, node)
                    for key in ("$anchor", "$dynamicAnchor"):
                        if isinstance(node.get(key), str):
                            self.anchors[(urldefrag(scope)[0], node[key])] = (path, node)
                for key, value, child_role in _children(node, role):
                    index(value, child_role, scope, parts + (key,))

        # A referenced file may contain an API document, a single schema, or API objects.
        index(document, "api", uri)
        index(document, "schema", uri)

    def resolve(self, ref, scope):
        uri, fragment = urldefrag(_join(scope, ref))
        if uri not in self.resources:
            parsed = urlsplit(uri)
            if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
                raise ValueError(f"reference {ref!r} is unavailable offline (remote retrieval disabled)")
            path = Path(url2pathname(parsed.path)).resolve()
            try:
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                raise ValueError(f"unresolved reference {ref!r}: {exc.__class__.__name__}") from exc
            if error := _json_shape(document):
                raise ValueError(f"invalid referenced document {path}{pointer(error[0])}: {error[1]}")
            self.add_document(path, document)
        path, target = self.resources[uri]
        parts = self.locations.get(id(target), ())
        fragment = unquote(fragment)
        if fragment and not fragment.startswith("/"):
            if (uri, fragment) not in self.anchors:
                raise ValueError(f"unresolved reference {ref!r}: anchor does not exist")
            path, target = self.anchors[(uri, fragment)]
            parts = self.locations.get(id(target), ())
        elif fragment:
            try:
                for token in fragment[1:].split("/"):
                    if re.search(r"~(?![01])", token):
                        raise KeyError(token)
                    token = token.replace("~1", "/").replace("~0", "~")
                    parts += (token,)
                    if isinstance(target, list):
                        if not re.fullmatch(r"0|[1-9][0-9]*", token):
                            raise KeyError(token)
                        target = target[int(token)]
                    else:
                        target = target[token]
            except (KeyError, IndexError, TypeError) as exc:
                raise ValueError(f"unresolved reference {ref!r}: JSON pointer does not exist") from exc
        return path, target, self.scopes.get(id(target), uri), (uri, fragment), parts

    def expand(self, node, path, role="api", parts=(), scope=None, chain=()):
        if role == "data":
            return copy.deepcopy(node)
        scope = scope or path.resolve().as_uri()
        if isinstance(node, list):
            expanded = [self.expand(value, path, role, parts + (index,), scope, chain) for index, value in enumerate(node)]
            self.origins[id(expanded)] = (path, parts)
            return expanded
        if not isinstance(node, dict):
            return node
        if role == "schema" and isinstance(node.get("$id"), str):
            scope = _join(scope, node["$id"])
        for keyword in ("$ref", "$dynamicRef"):
            if keyword not in node or role in {"schema-map", "api-map", "extension-map", "message-map", "components"}:
                continue
            ref = node[keyword]
            if not isinstance(ref, str):
                continue  # The official schema supplies the type diagnostic.
            try:
                target_path, target, target_scope, identity, target_parts = self.resolve(ref, scope)
                if identity in chain:
                    if role != "schema":
                        raise ValueError(f"unresolved cyclic reference {ref!r} has no concrete API object")
                    return copy.deepcopy(node)  # Recursive JSON Schema is valid.
                expanded = self.expand(target, target_path, role, target_parts, target_scope, chain + (identity,))
                if role == "schema":
                    siblings = {
                        key: self.expand(value, path, child_role, parts + (key,), scope, chain)
                        for key, value, child_role in _children(node, role)
                        if key not in {"$ref", "$dynamicRef"}
                    }
                    if siblings:
                        # Validate both schema bodies without letting either overwrite keywords.
                        self.origins[id(siblings)] = (path, parts)
                        expanded = {"allOf": [expanded, siblings]}
                        self.origins[id(expanded)] = (path, parts)
                if isinstance(expanded, (dict, list)):
                    self.uses[id(expanded)] = (path, parts + (keyword,))
                return expanded
            except ValueError as exc:
                self.errors.append(diagnostic(path, parts + (keyword,), str(exc)))
        expanded = {
            key: self.expand(value, path, child_role, parts + (key,), scope, chain)
            for key, value, child_role in _children(node, role)
        }
        self.origins[id(expanded)] = (path, parts)
        return expanded


def _schema_errors(validator, document, sidecar, origins=None, uses=None):
    def leaves(error):
        if error.context:
            for child in error.context:
                yield from leaves(child)
        else:
            yield error

    errors = [leaf for error in validator.iter_errors(document) for leaf in leaves(error)]
    errors.sort(key=lambda error: (-len(error.absolute_path), str(list(error.absolute_path)), error.message))
    messages = []
    for error in errors:
        parts = tuple(error.absolute_path)
        source, source_parts = sidecar, parts
        use = None
        if origins:
            node = document
            for offset in range(len(parts) + 1):
                if id(node) in origins:
                    source, origin_parts = origins[id(node)]
                    source_parts = origin_parts + parts[offset:]
                if uses and id(node) in uses:
                    use = uses[id(node)]
                if offset < len(parts):
                    node = node[parts[offset]]
        context = f" (referenced from {use[0]}{pointer(use[1])})" if use else ""
        message = diagnostic(source, source_parts, error.message + context)
        if message not in messages:
            messages.append(message)
    return messages[:20]


def validate_contract(sidecar: Path, document: object, fmt: str) -> list[str]:
    match = FORM.fullmatch(fmt)
    if not match:
        return [diagnostic(sidecar, (), f"unsupported contract sidecar_format {fmt!r}")]
    family = match[1].lower()
    if not isinstance(document, dict):
        return [diagnostic(sidecar, (), f"declared {fmt} but document is not a mapping")]
    if error := _json_shape(document):
        return [diagnostic(sidecar, error[0], error[1])]
    if family not in document:
        return [diagnostic(sidecar, (family,), f"missing root keys ['{family}'] — contract version is required")]
    version = document[family]
    version_match = VERSION.fullmatch(version) if isinstance(version, str) else None
    if not version_match:
        return [diagnostic(sidecar, (family,), f"{family} version must be a semantic version string")]
    version_parts = version_match.groups()
    for declared, actual in zip(match.groups()[1:], version_parts):
        if declared is not None and declared != "x" and declared != actual:
            return [diagnostic(sidecar, (family,), f"document version {version!r} does not match sidecar_format {fmt!r}")]
    minor = ".".join(version_parts[:2])
    if family == "openapi" and minor in {"3.0", "3.1", "3.2"}:
        filename = f"openapi-{minor}" + (".json" if minor == "3.0" else "-schema-base.json")
    elif family == "asyncapi" and version in {f"2.{minor}.0" for minor in range(7)} | {"3.0.0"}:
        filename = f"asyncapi-{version}.json"
    else:
        return [diagnostic(sidecar, (family,), f"unsupported {family} version {version!r}; no pinned offline schema")]
    try:
        from jsonschema import validators
        documents, registry = _bundle()
        schema = documents[filename]
        validator = validators.validator_for(schema)(schema, registry=registry)
    except (ImportError, OSError, ValueError, KeyError) as exc:
        return [diagnostic(sidecar, (), f"contract validator unavailable: {exc}; install scripts/requirements.txt and restore bundled schemas")]
    try:
        errors = _schema_errors(validator, document, sidecar)
        references = _References(sidecar, document)
        expanded = references.expand(document, sidecar)
        errors.extend(references.errors)
        if expanded != document:
            errors.extend(_schema_errors(validator, expanded, sidecar, references.origins, references.uses))
        return list(dict.fromkeys(errors))
    except Exception as exc:
        # Missing resolver resources and unsupported evaluation must fail closed.
        return [diagnostic(sidecar, (), f"contract validation unavailable/failed ({exc.__class__.__name__}: {exc})")]
