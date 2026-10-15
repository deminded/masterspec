from __future__ import annotations

import importlib.util
import builtins
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


SCRIPT = Path(__file__).parents[1] / "check-operational-envelope.py"
SPEC = importlib.util.spec_from_file_location("contract_sidecar_checker", SCRIPT)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)


class ContractValidationTest(unittest.TestCase):
    def openapi(self, version: str = "3.1.0") -> dict:
        return {
            "openapi": version,
            "info": {"title": "Example API", "version": "1.0"},
            "paths": {"/items": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

    def asyncapi(self, version: str = "2.6.0") -> dict:
        return {
            "asyncapi": version,
            "info": {"title": "Example events", "version": "1.0"},
            "channels": {},
        }

    def check(self, doc: object, fmt: str = "openapi-3.1", directory: str | None = None) -> list[str]:
        if directory is None:
            with tempfile.TemporaryDirectory() as directory:
                return self.check(doc, fmt, directory)
        path = Path(directory) / "api-example.yaml"
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        return CHECKER.check_sidecar(path, fmt)

    def assert_f2(self, errors: list[str], pointer: str | None = None) -> None:
        self.assertTrue(errors, "Invalid contract passed the gate")
        self.assertTrue(all("(F2)" in error for error in errors), errors)
        self.assertTrue(all("api-example.yaml" in error and "#" in error for error in errors), errors)
        if pointer is not None:
            self.assertTrue(any(pointer in error for error in errors), errors)

    def test_valid_documents_are_checked_offline(self) -> None:
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network access")):
            for version in ("3.0.0", "3.0.4", "3.1.0", "3.1.2", "3.2.0"):
                with self.subTest(version=version):
                    self.assertEqual(self.check(self.openapi(version), "openapi-" + version[:3]), [])
            for version in ("2.0.0", "2.1.0", "2.2.0", "2.3.0", "2.4.0", "2.5.0", "2.6.0", "3.0.0"):
                with self.subTest(version=version):
                    self.assertEqual(self.check(self.asyncapi(version), "asyncapi-" + version[:3]), [])

    def test_openapi_requires_info(self) -> None:
        doc = self.openapi()
        del doc["info"]
        self.assert_f2(self.check(doc))

    def test_yaml_non_string_mapping_key_is_diagnostic(self) -> None:
        doc = self.openapi()
        doc["paths"]["/items"]["get"]["responses"] = {200: {"description": "OK"}}
        self.assert_f2(self.check(doc), "#/paths/~1items/get/responses")

    def test_openapi_rejects_wrong_nested_types(self) -> None:
        for value in ([], "wrong", 7, None):
            with self.subTest(value=value):
                doc = self.openapi()
                doc["paths"]["/items"]["get"]["responses"] = value
                self.assert_f2(self.check(doc), "#/paths/~1items/get/responses")

    def test_openapi_rejects_missing_required_response_field(self) -> None:
        doc = self.openapi()
        doc["paths"]["/items"]["get"]["responses"]["200"] = {}
        self.assert_f2(self.check(doc), "#/paths/~1items/get/responses/200")

    def test_unknown_fields_rejected_and_extensions_allowed(self) -> None:
        for target in ("root", "operation"):
            with self.subTest(target=target):
                doc = self.openapi()
                owner = doc if target == "root" else doc["paths"]["/items"]["get"]
                owner["x-owner"] = {"$ref": "this-is-example-data"}
                self.assertEqual(self.check(doc), [])
                owner["respones"] = {}
                self.assert_f2(self.check(doc))

    def test_openapi_schema_object_is_validated(self) -> None:
        for version in ("3.0.3", "3.1.0"):
            with self.subTest(version=version):
                doc = self.openapi(version)
                doc["components"] = {"schemas": {"Item": {"type": "not-a-type"}}}
                self.assert_f2(self.check(doc, "openapi-" + version[:3]), "#/components/schemas/Item")

    def test_version_specific_schema_rules(self) -> None:
        doc = self.openapi("3.0.3")
        doc["components"] = {"schemas": {"Item": {"type": ["string", "null"]}}}
        self.assert_f2(self.check(doc, "openapi-3.0"))
        doc["openapi"] = "3.1.0"
        self.assertEqual(self.check(doc), [])

    def test_openapi_31_webhook_only_document_is_valid(self) -> None:
        doc = self.openapi()
        del doc["paths"]
        doc["webhooks"] = {"newItem": {"post": {"responses": {"200": {"description": "OK"}}}}}
        self.assertEqual(self.check(doc), [])

    def test_asyncapi_rejects_invalid_channel_and_message(self) -> None:
        for channel in ([], {"publish": {"message": []}}, {"publish": {"message": {"unknown": True}}}):
            with self.subTest(channel=channel):
                doc = self.asyncapi()
                doc["channels"] = {"orders/created": channel}
                self.assert_f2(self.check(doc, "asyncapi-2.6"), "#/channels/orders~1created")

    def test_asyncapi_3_operation_requires_action(self) -> None:
        doc = self.asyncapi("3.0.0")
        doc["channels"] = {"orders": {"address": "orders", "messages": {}}}
        doc["operations"] = {"sendOrder": {"channel": {"$ref": "#/channels/orders"}}}
        self.assert_f2(self.check(doc, "asyncapi-3.0"), "#/operations/sendOrder")

    def test_declared_version_mismatch_is_blocker(self) -> None:
        for doc, fmt in ((self.openapi(), "openapi-3.0"), (self.asyncapi(), "asyncapi-3.0")):
            with self.subTest(fmt=fmt):
                self.assert_f2(self.check(doc, fmt))

    def test_unsupported_or_invalid_version_cannot_pass(self) -> None:
        for version in ("9.0.0", "3.99.0", "three", 3.1, None):
            with self.subTest(version=version):
                doc = self.openapi()
                doc["openapi"] = version
                self.assert_f2(self.check(doc, "openapi"))

    def test_broken_internal_reference_has_reference_address(self) -> None:
        doc = self.openapi()
        doc["paths"]["/items"]["get"]["responses"]["200"] = {"$ref": "#/components/responses/Missing"}
        self.assert_f2(self.check(doc), "#/paths/~1items/get/responses/200/$ref")

    def test_asyncapi_broken_reference_is_blocker(self) -> None:
        doc = self.asyncapi()
        doc["channels"] = {"orders": {"publish": {"message": {"$ref": "#/components/messages/Missing"}}}}
        self.assert_f2(self.check(doc, "asyncapi-2.6"), "#/channels/orders/publish/message/$ref")

    def test_asyncapi_message_headers_are_schemas(self) -> None:
        for version in ("2.6.0", "3.0.0"):
            with self.subTest(version=version):
                doc = self.asyncapi(version)
                doc["components"] = {"messages": {"Order": {"headers": {"$ref": "#/missing"}}}}
                self.assert_f2(self.check(doc, "asyncapi-" + version[:3]), "#/components/messages/Order/headers/$ref")

    def test_internal_escaped_pointers_and_recursive_schema_are_valid(self) -> None:
        doc = self.openapi()
        doc["components"] = {
            "schemas": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/components/schemas/Node"}}}},
            "responses": {"OK": {"description": "OK"}},
        }
        doc["paths"]["/items"]["get"]["responses"]["200"] = {"$ref": "#/components/responses/OK"}
        doc["paths"]["/alias"] = {"$ref": "#/paths/~1items"}
        self.assertEqual(self.check(doc), [])

    def test_examples_default_and_const_are_payloads(self) -> None:
        doc = self.openapi()
        literal = {"$ref": "#/nonexistent-payload-field"}
        doc["components"] = {"schemas": {"Item": {"type": "object", "example": literal, "default": literal, "const": literal}}}
        response = doc["paths"]["/items"]["get"]["responses"]["200"]
        response["content"] = {"application/json": {"schema": {"type": "object"}, "example": literal}}
        self.assertEqual(self.check(doc), [])

    def test_properties_named_example_are_still_schemas(self) -> None:
        for name in ("example", "default", "const", "x-property"):
            with self.subTest(name=name):
                doc = self.openapi()
                doc["components"] = {"schemas": {"Item": {"type": "object", "properties": {name: {"$ref": "#/missing"}}}}}
                self.assert_f2(self.check(doc), f"#/components/schemas/Item/properties/{name}/$ref")

    def test_missing_external_reference_is_blocker(self) -> None:
        doc = self.openapi()
        doc["components"] = {"schemas": {"Item": {"$ref": "missing.yaml#/Item"}}}
        self.assert_f2(self.check(doc), "#/components/schemas/Item/$ref")

    def test_external_local_schema_and_nested_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "models.yaml").write_text("Item:\n  type: object\n  properties:\n    name:\n      $ref: 'types.yaml#/Name'\n", encoding="utf-8")
            (root / "types.yaml").write_text("Name:\n  type: string\n", encoding="utf-8")
            doc = self.openapi()
            doc["components"] = {"schemas": {"Item": {"$ref": "models.yaml#/Item"}}}
            self.assertEqual(self.check(doc, directory=directory), [])
            (root / "types.yaml").write_text("WrongName:\n  type: string\n", encoding="utf-8")
            errors = self.check(doc, directory=directory)
            self.assertTrue(errors, "Broken reference in an external file passed")
            self.assertTrue(all("(F2)" in error for error in errors), errors)

    def test_external_reference_target_must_match_its_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "responses.yaml").write_text("OK:\n  description: 7\n", encoding="utf-8")
            doc = self.openapi()
            doc["paths"]["/items"]["get"]["responses"]["200"] = {"$ref": "responses.yaml#/OK"}
            self.assert_f2(self.check(doc, directory=directory))

    def test_unavailable_remote_reference_does_not_pass_or_fetch(self) -> None:
        doc = self.openapi()
        doc["components"] = {"schemas": {"Item": {"$ref": "https://example.invalid/Item.json"}}}
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network access")):
            self.assert_f2(self.check(doc), "#/components/schemas/Item/$ref")

    def test_missing_jsonschema_is_a_blocker(self) -> None:
        original_import = builtins.__import__

        def without_validator(name, *args, **kwargs):
            if name == "jsonschema":
                raise ModuleNotFoundError("No module named 'jsonschema'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_validator):
            errors = self.check(self.openapi())
        self.assert_f2(errors)
        self.assertTrue(any("requirements.txt" in error for error in errors), errors)

    def test_missing_schema_bundle_is_a_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(CHECKER._CONTRACT_VALIDATION, "SCHEMAS", Path(directory)):
                self.assert_f2(self.check(self.openapi()))

    def test_schema_error_reaches_verify_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "02-specifications" / "04-apis" / "external"
            folder.mkdir(parents=True)
            (folder / "api-example.md").write_text(
                "---\ntype: api\nslug: api-example\ncontract_origin: authored\n"
                "sidecar_format: openapi-3.1\nsidecar: api-example.yaml\n---\n# API\n",
                encoding="utf-8",
            )
            doc = self.openapi()
            doc["info"]["version"] = 1
            self.check(doc, directory=str(folder))
            self.assert_f2(CHECKER.validate_forms(root), "#/info/version")


if __name__ == "__main__":
    unittest.main()
