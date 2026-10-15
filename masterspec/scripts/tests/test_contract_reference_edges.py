"""Reference resolution regressions exercised through the operational-envelope gate."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


SCRIPT = Path(__file__).parents[1] / "check-operational-envelope.py"
SPEC = importlib.util.spec_from_file_location("contract_reference_edge_checker", SCRIPT)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)


class ContractReferenceEdgesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sidecar = self.root / "api-example.yaml"

    def openapi(self) -> dict:
        return {
            "openapi": "3.1.0",
            "info": {"title": "Example API", "version": "1.0"},
            "paths": {"/items": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

    def check(self, document: dict, fmt: str = "openapi-3.1") -> list[str]:
        self.sidecar.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return CHECKER.check_sidecar(self.sidecar, fmt)

    def asyncapi(self, version: str, headers: dict) -> dict:
        message = {"headers": headers}
        channel = ({"publish": {"message": message}} if version.startswith("2.")
                   else {"messages": {"created": message}})
        return {
            "asyncapi": version,
            "info": {"title": "Example events", "version": "1.0"},
            "channels": {"orders": channel},
        }

    def assert_f2(self, errors: list[str], address: str) -> None:
        self.assertTrue(errors, "Invalid reference passed the gate")
        self.assertTrue(all("(F2)" in error for error in errors), errors)
        self.assertTrue(any(address in error for error in errors), errors)

    def test_openapi_map_extensions_contain_arbitrary_payloads(self) -> None:
        for location in ("paths", "responses"):
            with self.subTest(location=location):
                document = self.openapi()
                target = (document["paths"] if location == "paths"
                          else document["paths"]["/items"]["get"]["responses"])
                target["x-metadata"] = {"$ref": "literal-example-data"}
                self.assertEqual(self.check(document), [])

    def test_x_prefixed_component_name_still_contains_real_schema_references(self) -> None:
        document = self.openapi()
        document["components"] = {"schemas": {"x-real-schema": {"$ref": "#/missing"}}}
        self.assert_f2(self.check(document), "#/components/schemas/x-real-schema/$ref")

    def test_x_prefixed_asyncapi_channel_name_still_contains_real_references(self) -> None:
        document = {
            "asyncapi": "2.6.0",
            "info": {"title": "Example events", "version": "1.0"},
            "channels": {"x-orders": {"$ref": "missing-channel.yaml"}},
        }
        self.assert_f2(self.check(document, "asyncapi-2.6"), "#/channels/x-orders/$ref")

    def test_reference_siblings_cannot_mask_invalid_external_schema(self) -> None:
        (self.root / "bad.yaml").write_text("type: not-a-type\n", encoding="utf-8")
        document = self.openapi()
        document["components"] = {"schemas": {"Item": {"$ref": "bad.yaml", "type": "string"}}}
        self.assert_f2(self.check(document), "#/components/schemas/Item")

    def test_reference_sibling_with_shared_keyword_keeps_its_nested_references(self) -> None:
        document = self.openapi()
        document["components"] = {"schemas": {"Item": {
            "$ref": "valid.yaml",
            "properties": {"other": {"$ref": "missing.yaml"}},
        }}}
        for target in ("type: object\nproperties:\n  name:\n    type: string\n", "true\n"):
            with self.subTest(target=target):
                (self.root / "valid.yaml").write_text(target, encoding="utf-8")
                self.assert_f2(self.check(document), "#/components/schemas/Item/properties/other/$ref")

    def test_asyncapi_message_headers_resolve_schema_references(self) -> None:
        for version in ("2.6.0", "3.0.0"):
            with self.subTest(version=version):
                document = self.asyncapi(version, {"$ref": "#/missing"})
                self.assert_f2(self.check(document, "asyncapi-" + version[:3]), "/headers/$ref")

    def test_asyncapi_message_header_property_named_default_is_a_schema(self) -> None:
        for version in ("2.6.0", "3.0.0"):
            with self.subTest(version=version):
                document = self.asyncapi(version, {
                    "type": "object", "properties": {"default": {"$ref": "#/missing"}},
                })
                self.assert_f2(self.check(document, "asyncapi-" + version[:3]),
                               "/headers/properties/default/$ref")

    def test_asyncapi_message_header_examples_defaults_and_constants_are_data(self) -> None:
        literal = {"$ref": "literal-example-data"}
        for version in ("2.6.0", "3.0.0"):
            with self.subTest(version=version):
                document = self.asyncapi(version, {
                    "type": "object", "example": literal, "default": literal, "const": literal,
                })
                self.assertEqual(self.check(document, "asyncapi-" + version[:3]), [])

    def test_recursive_relative_schema_id_is_applied_once(self) -> None:
        document = self.openapi()
        document["components"] = {"schemas": {"Node": {
            "$id": "schemas/person.json",
            "type": "object",
            "properties": {"next": {"$ref": "person.json"}},
        }}}
        self.assertEqual(self.check(document), [])

    def test_recursive_schema_id_can_be_a_urn(self) -> None:
        document = self.openapi()
        document["components"] = {"schemas": {"Node": {
            "$id": "urn:example:person",
            "type": "object",
            "properties": {"next": {"$ref": "#"}},
        }}}
        self.assertEqual(self.check(document), [])

    def test_external_reference_error_points_into_its_own_document(self) -> None:
        models = self.root / "models.yaml"
        models.write_text(
            "Item:\n  type: object\n  properties:\n    name:\n      $ref: 'types.yaml#/Missing'\n",
            encoding="utf-8",
        )
        (self.root / "types.yaml").write_text("Name:\n  type: string\n", encoding="utf-8")
        document = self.openapi()
        document["components"] = {"schemas": {"Item": {"$ref": "models.yaml#/Item"}}}
        self.assert_f2(self.check(document), f"{models}#/Item/properties/name/$ref")

    def test_cyclic_yaml_alias_is_a_diagnostic_instead_of_an_exception(self) -> None:
        self.sidecar.write_text(
            "openapi: 3.1.0\ninfo:\n  title: Example API\n  version: '1.0'\n"
            "paths: {}\nx-cycle: &cycle\n  self: *cycle\n",
            encoding="utf-8",
        )
        self.assert_f2(CHECKER.check_sidecar(self.sidecar, "openapi-3.1"), "api-example.yaml#")


if __name__ == "__main__":
    unittest.main()
