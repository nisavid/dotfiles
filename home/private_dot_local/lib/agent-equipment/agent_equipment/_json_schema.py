"""Dependency-free validation for the local agent-equipment JSON Schemas.

The module deliberately implements only the closed JSON Schema 2020-12 subset
used by the agent-equipment contracts.  Both schema preflight and instance
validation fail closed; callers receive no partial or best-effort result.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

__all__ = ("validate_document", "validate_schema_documents")


_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_SUPPORTED_TYPE_NAMES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)
_SUPPORTED_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "title",
        "description",
        "$comment",
        "examples",
        "default",
        "deprecated",
        "$defs",
        "$ref",
        "type",
        "required",
        "properties",
        "additionalProperties",
        "unevaluatedProperties",
        "items",
        "const",
        "enum",
        "pattern",
        "format",
        "minLength",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
        "minProperties",
        "uniqueItems",
        "oneOf",
        "allOf",
        "if",
        "then",
        "else",
    }
)
_SCHEMA_MAP_KEYWORDS = ("$defs", "properties")
_SCHEMA_ARRAY_KEYWORDS = ("oneOf", "allOf")
_SCHEMA_KEYWORDS = (
    "additionalProperties",
    "unevaluatedProperties",
    "items",
    "if",
    "then",
    "else",
)
_NONNEGATIVE_INTEGER_KEYWORDS = (
    "minLength",
    "minItems",
    "maxItems",
    "minProperties",
)
_DATE_TIME_PATTERN = re.compile(
    r"^(?P<year>[0-9]{4})-"
    r"(?P<month>0[1-9]|1[0-2])-"
    r"(?P<day>0[1-9]|[12][0-9]|3[01])[Tt]"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:[.,][0-9]+)?"
    r"(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z"
)
_SCHEMA_ID_PATTERN = re.compile(r"^[^#]*#?$")

_SchemaLocation = tuple[str, tuple[str, ...]]


@dataclass(frozen=True)
class _Evaluation:
    valid: bool
    evaluated_properties: frozenset[str] = frozenset()


def validate_document(
    document: Any,
    *,
    schema_directory: str | Path,
    root_schema_name: str,
    allowed_schema_names: Collection[str],
    schema_documents: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether *document* satisfies one closed, local JSON Schema set.

    ``root_schema_name`` and every filename in ``allowed_schema_names`` must be
    plain filenames rooted directly in ``schema_directory``.  Only exact local
    references to those files and local JSON Pointer fragments are accepted.
    Malformed schemas, unsupported keywords, unresolved references, reference
    cycles, and non-JSON in-memory documents all return ``False``.
    """

    try:
        schemas = (
            _load_schemas(schema_directory, root_schema_name, allowed_schema_names)
            if schema_documents is None
            else _schemas_from_documents(
                schema_documents,
                root_schema_name,
                allowed_schema_names,
            )
        )
        if schemas is None or not _is_json_value(document):
            return False
        schema_set = _SchemaSet(schemas)
        if not schema_set.preflight():
            return False
        return schema_set.evaluate(document, (root_schema_name, ())).valid
    except RecursionError:
        return False


def validate_schema_documents(
    schema_documents: Mapping[str, Any],
    *,
    allowed_schema_names: Collection[str],
) -> bool:
    """Validate one already parsed closed local schema set without filesystem I/O."""

    if isinstance(allowed_schema_names, (str, bytes)):
        return False
    try:
        allowed = frozenset(allowed_schema_names)
    except TypeError:
        return False
    if not allowed or set(schema_documents) != set(allowed):
        return False
    schemas = _schemas_from_documents(
        schema_documents,
        min(allowed),
        allowed,
    )
    if schemas is None:
        return False
    try:
        return _SchemaSet(schemas).preflight()
    except RecursionError:
        return False


class _SchemaSet:
    def __init__(self, schemas: dict[str, dict[str, Any]]) -> None:
        self._schemas = schemas

    def preflight(self) -> bool:
        complete: set[_SchemaLocation] = set()
        active: set[_SchemaLocation] = set()
        return all(
            self._preflight_location((name, ()), complete, active)
            for name in sorted(self._schemas)
        )

    def _preflight_location(
        self,
        location: _SchemaLocation,
        complete: set[_SchemaLocation],
        active: set[_SchemaLocation],
    ) -> bool:
        if location in complete:
            return True
        if location in active:
            return False
        schema = self._at(location)
        if type(schema) is not dict:
            return False
        active.add(location)
        valid = self._preflight_schema(schema, location, complete, active)
        active.remove(location)
        if valid:
            complete.add(location)
        return valid

    def _preflight_schema(
        self,
        schema: dict[str, Any],
        location: _SchemaLocation,
        complete: set[_SchemaLocation],
        active: set[_SchemaLocation],
    ) -> bool:
        if set(schema) - _SUPPORTED_KEYWORDS:
            return False
        if "$schema" in schema and schema["$schema"] != _DRAFT_2020_12:
            return False
        if "$id" in schema and (location[1] or not _valid_schema_id(schema["$id"])):
            return False
        if "title" in schema and type(schema["title"]) is not str:
            return False
        if "type" in schema and (
            type(schema["type"]) is not str
            or schema["type"] not in _SUPPORTED_TYPE_NAMES
        ):
            return False
        if "$ref" in schema:
            if type(schema["$ref"]) is not str:
                return False
            target = self._resolve(schema["$ref"], location[0])
            if target is None or not self._preflight_location(target, complete, active):
                return False
        if "required" in schema and not _valid_unique_string_array(
            schema["required"], allow_empty=True
        ):
            return False
        for keyword in _SCHEMA_MAP_KEYWORDS:
            if keyword not in schema:
                continue
            children = schema[keyword]
            if type(children) is not dict:
                return False
            for name in children:
                child_location = _child_location(location, keyword, name)
                if not self._preflight_location(child_location, complete, active):
                    return False
        for keyword in _SCHEMA_ARRAY_KEYWORDS:
            if keyword not in schema:
                continue
            children = schema[keyword]
            if type(children) is not list or not children:
                return False
            for index in range(len(children)):
                child_location = _child_location(location, keyword, str(index))
                if not self._preflight_location(child_location, complete, active):
                    return False
        for keyword in _SCHEMA_KEYWORDS:
            if keyword not in schema:
                continue
            child = schema[keyword]
            if (
                keyword in {"additionalProperties", "unevaluatedProperties"}
                and type(child) is bool
            ):
                continue
            if type(child) is not dict or not self._preflight_location(
                _child_location(location, keyword), complete, active
            ):
                return False
        if "const" in schema and not _is_json_value(schema["const"]):
            return False
        if "enum" in schema:
            values = schema["enum"]
            if type(values) is not list or not values or not _all_json_unique(values):
                return False
        if "pattern" in schema:
            if type(schema["pattern"]) is not str:
                return False
            try:
                re.compile(schema["pattern"])
            except re.error:
                return False
        if "format" in schema and schema["format"] != "date-time":
            return False
        for keyword in _NONNEGATIVE_INTEGER_KEYWORDS:
            if keyword in schema and not _is_nonnegative_integer(schema[keyword]):
                return False
        for keyword in ("minimum", "maximum"):
            if keyword in schema and not _is_finite_number(schema[keyword]):
                return False
        return not ("uniqueItems" in schema and type(schema["uniqueItems"]) is not bool)

    def evaluate(
        self,
        instance: Any,
        location: _SchemaLocation,
        active: frozenset[_SchemaLocation] = frozenset(),
    ) -> _Evaluation:
        if location in active:
            return _Evaluation(False)
        schema = self._at(location)
        if type(schema) is not dict:
            return _Evaluation(False)
        nested_active = active | {location}
        evaluated: set[str] = set()

        reference = schema.get("$ref")
        if reference is not None:
            target = self._resolve(reference, location[0])
            if target is None:
                return _Evaluation(False)
            result = self.evaluate(instance, target, nested_active)
            if not result.valid:
                return _Evaluation(False)
            evaluated.update(result.evaluated_properties)

        expected_type = schema.get("type")
        if expected_type is not None and not _matches_type(instance, expected_type):
            return _Evaluation(False)
        if "const" in schema and not _json_equal(instance, schema["const"]):
            return _Evaluation(False)
        if "enum" in schema and not any(
            _json_equal(instance, value) for value in schema["enum"]
        ):
            return _Evaluation(False)

        all_of = schema.get("allOf", [])
        for index in range(len(all_of)):
            result = self.evaluate(
                instance,
                _child_location(location, "allOf", str(index)),
                nested_active,
            )
            if not result.valid:
                return _Evaluation(False)
            evaluated.update(result.evaluated_properties)

        one_of = schema.get("oneOf")
        if one_of is not None:
            matches: list[_Evaluation] = []
            for index in range(len(one_of)):
                result = self.evaluate(
                    instance,
                    _child_location(location, "oneOf", str(index)),
                    nested_active,
                )
                if result.valid:
                    matches.append(result)
            if len(matches) != 1:
                return _Evaluation(False)
            evaluated.update(matches[0].evaluated_properties)

        if "if" in schema:
            condition = self.evaluate(
                instance, _child_location(location, "if"), nested_active
            )
            if condition.valid:
                evaluated.update(condition.evaluated_properties)
                if "then" in schema:
                    result = self.evaluate(
                        instance, _child_location(location, "then"), nested_active
                    )
                    if not result.valid:
                        return _Evaluation(False)
                    evaluated.update(result.evaluated_properties)
            elif "else" in schema:
                result = self.evaluate(
                    instance, _child_location(location, "else"), nested_active
                )
                if not result.valid:
                    return _Evaluation(False)
                evaluated.update(result.evaluated_properties)

        if type(instance) is str:
            if len(instance) < schema.get("minLength", 0):
                return _Evaluation(False)
            if "pattern" in schema and re.search(schema["pattern"], instance) is None:
                return _Evaluation(False)
            if schema.get("format") == "date-time" and not _valid_date_time(instance):
                return _Evaluation(False)

        if (
            type(instance) in {int, float}
            and "minimum" in schema
            and instance < schema["minimum"]
        ):
            return _Evaluation(False)
        if (
            type(instance) in {int, float}
            and "maximum" in schema
            and instance > schema["maximum"]
        ):
            return _Evaluation(False)

        if type(instance) is list:
            if len(instance) < schema.get("minItems", 0):
                return _Evaluation(False)
            if "maxItems" in schema and len(instance) > schema["maxItems"]:
                return _Evaluation(False)
            if schema.get("uniqueItems") is True and not _all_json_unique(instance):
                return _Evaluation(False)
            if "items" in schema:
                item_location = _child_location(location, "items")
                if any(
                    not self.evaluate(item, item_location, nested_active).valid
                    for item in instance
                ):
                    return _Evaluation(False)

        if type(instance) is dict:
            if len(instance) < schema.get("minProperties", 0):
                return _Evaluation(False)
            if any(name not in instance for name in schema.get("required", [])):
                return _Evaluation(False)
            properties = schema.get("properties", {})
            for name in instance.keys() & properties.keys():
                result = self.evaluate(
                    instance[name],
                    _child_location(location, "properties", name),
                    nested_active,
                )
                if not result.valid:
                    return _Evaluation(False)
                evaluated.add(name)
            extras = instance.keys() - properties.keys()
            if "additionalProperties" in schema:
                additional = schema["additionalProperties"]
                if additional is False and extras:
                    return _Evaluation(False)
                if additional is True:
                    evaluated.update(extras)
                elif type(additional) is dict:
                    additional_location = _child_location(
                        location, "additionalProperties"
                    )
                    if any(
                        not self.evaluate(
                            instance[name], additional_location, nested_active
                        ).valid
                        for name in extras
                    ):
                        return _Evaluation(False)
                    evaluated.update(extras)
            if "unevaluatedProperties" in schema:
                unevaluated = instance.keys() - evaluated
                unevaluated_schema = schema["unevaluatedProperties"]
                if unevaluated_schema is False and unevaluated:
                    return _Evaluation(False)
                if unevaluated_schema is True:
                    evaluated.update(unevaluated)
                elif type(unevaluated_schema) is dict:
                    unevaluated_location = _child_location(
                        location, "unevaluatedProperties"
                    )
                    if any(
                        not self.evaluate(
                            instance[name], unevaluated_location, nested_active
                        ).valid
                        for name in unevaluated
                    ):
                        return _Evaluation(False)
                    evaluated.update(unevaluated)

        return _Evaluation(True, frozenset(evaluated))

    def _at(self, location: _SchemaLocation) -> Any:
        value: Any = self._schemas.get(location[0])
        for token in location[1]:
            if type(value) is dict and token in value:
                value = value[token]
            elif type(value) is list:
                index = _array_index(token, len(value))
                if index is None:
                    return None
                value = value[index]
            else:
                return None
        return value

    def _resolve(self, reference: str, current_name: str) -> _SchemaLocation | None:
        if type(reference) is not str or "%" in reference:
            return None
        file_name, separator, fragment = reference.partition("#")
        if separator and "#" in fragment:
            return None
        target_name = current_name if not file_name else file_name
        if target_name not in self._schemas or (
            file_name and not _safe_filename(file_name)
        ):
            return None
        if not separator:
            return (target_name, ())
        if not fragment:
            return (target_name, ())
        if not fragment.startswith("/"):
            return None
        tokens: list[str] = []
        for encoded_token in fragment[1:].split("/"):
            token = _decode_pointer_token(encoded_token)
            if token is None:
                return None
            tokens.append(token)
        location = (target_name, tuple(tokens))
        return location if type(self._at(location)) is dict else None


def _child_location(
    location: _SchemaLocation, keyword: str, child: str | None = None
) -> _SchemaLocation:
    suffix = (keyword,) if child is None else (keyword, child)
    return (location[0], location[1] + suffix)


def _decode_pointer_token(value: str) -> str | None:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "~":
            result.append(value[index])
            index += 1
            continue
        if index + 1 >= len(value) or value[index + 1] not in {"0", "1"}:
            return None
        result.append("~" if value[index + 1] == "0" else "/")
        index += 2
    return "".join(result)


def _array_index(value: str, length: int) -> int | None:
    if not (value == "0" or (value and value[0] != "0" and value.isdigit())):
        return None
    maximum = str(length - 1)
    if length == 0 or len(value) > len(maximum):
        return None
    index = int(value)
    return index if index < length else None


def _load_schemas(
    schema_directory: str | Path,
    root_schema_name: str,
    allowed_schema_names: Collection[str],
) -> dict[str, dict[str, Any]] | None:
    if isinstance(allowed_schema_names, (str, bytes)):
        return None
    try:
        allowed = frozenset(allowed_schema_names)
        directory = Path(schema_directory).resolve(strict=True)
    except (OSError, TypeError, ValueError):
        return None
    if type(root_schema_name) is not str or root_schema_name not in allowed:
        return None
    if not allowed or any(not _safe_filename(name) for name in allowed):
        return None
    schemas: dict[str, dict[str, Any]] = {}
    for name in allowed:
        try:
            path = (directory / name).resolve(strict=True)
            if path.parent != directory or not path.is_file():
                return None
            parsed = json.loads(
                path.read_bytes().decode("utf-8"),
                object_pairs_hook=_object_without_duplicates,
                parse_constant=_reject_constant,
                parse_float=_finite_float,
            )
        except (OSError, UnicodeError, ValueError):
            return None
        if type(parsed) is not dict or not _is_json_value(parsed):
            return None
        schemas[name] = parsed
    return schemas


def _schemas_from_documents(
    schema_documents: Mapping[str, Any],
    root_schema_name: str,
    allowed_schema_names: Collection[str],
) -> dict[str, dict[str, Any]] | None:
    if isinstance(allowed_schema_names, (str, bytes)):
        return None
    try:
        allowed = frozenset(allowed_schema_names)
    except TypeError:
        return None
    if type(root_schema_name) is not str or root_schema_name not in allowed:
        return None
    if not allowed or any(not _safe_filename(name) for name in allowed):
        return None
    schemas: dict[str, dict[str, Any]] = {}
    for name in allowed:
        parsed = schema_documents.get(name)
        if type(parsed) is not dict or not _is_json_value(parsed):
            return None
        schemas[name] = parsed
    return schemas


def _safe_filename(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value not in {".", ".."}
        and Path(value).name == value
    )


def _valid_schema_id(value: Any) -> bool:
    # JSON Schema ``pattern`` uses search semantics, including ``$`` matching
    # immediately before one final newline.
    return type(value) is str and _SCHEMA_ID_PATTERN.search(value) is not None


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object member")
        result[key] = value
    return result


def _reject_constant(_: str) -> Any:
    raise ValueError("non-JSON numeric constant")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _is_json_value(value: Any, active: frozenset[int] = frozenset()) -> bool:
    if value is None or type(value) in {bool, int}:
        return True
    if type(value) is str:
        return _is_unicode_scalar_string(value)
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        if id(value) in active:
            return False
        nested = active | {id(value)}
        return all(_is_json_value(item, nested) for item in value)
    if type(value) is dict:
        if id(value) in active:
            return False
        nested = active | {id(value)}
        return all(
            type(key) is str
            and _is_unicode_scalar_string(key)
            and _is_json_value(item, nested)
            for key, item in value.items()
        )
    return False


def _is_unicode_scalar_string(value: str) -> bool:
    return all(not 0xD800 <= ord(character) <= 0xDFFF for character in value)


def _valid_unique_string_array(value: Any, *, allow_empty: bool) -> bool:
    return (
        type(value) is list
        and (allow_empty or bool(value))
        and all(type(item) is str for item in value)
        and len(set(value)) == len(value)
    )


def _is_nonnegative_integer(value: Any) -> bool:
    return (
        type(value) is int
        or (type(value) is float and math.isfinite(value) and value.is_integer())
    ) and value >= 0


def _is_finite_number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _all_json_unique(values: list[Any]) -> bool:
    seen: set[bytes] = set()
    for value in values:
        digest = _json_digest(value)
        if digest in seen:
            return False
        seen.add(digest)
    return True


def _json_equal(left: Any, right: Any) -> bool:
    return _json_digest(left) == _json_digest(right)


def _json_digest(value: Any) -> bytes:
    """Return a collision-resistant digest under JSON Schema equality."""

    digest = sha256()
    if value is None:
        digest.update(b"null")
    elif type(value) is bool:
        digest.update(b"boolean:true" if value else b"boolean:false")
    elif type(value) is int or (type(value) is float and value.is_integer()):
        digest.update(b"integer:")
        integer = int(value)
        magnitude = abs(integer)
        encoded = magnitude.to_bytes(max(1, (magnitude.bit_length() + 7) // 8), "big")
        digest.update(b"-" if integer < 0 else b"+")
        _update_framed(digest, encoded)
    elif type(value) is float:
        digest.update(b"float:")
        digest.update(value.hex().encode("ascii"))
    elif type(value) is str:
        digest.update(b"string:")
        _update_framed(digest, value.encode("utf-8"))
    elif type(value) is list:
        digest.update(b"array:")
        digest.update(str(len(value)).encode("ascii"))
        digest.update(b":")
        for item in value:
            digest.update(_json_digest(item))
    elif type(value) is dict:
        digest.update(b"object:")
        digest.update(str(len(value)).encode("ascii"))
        digest.update(b":")
        for key in sorted(value):
            _update_framed(digest, key.encode("utf-8"))
            digest.update(_json_digest(value[key]))
    else:
        raise TypeError("value is outside the closed JSON domain")
    return digest.digest()


def _update_framed(digest: Any, value: bytes) -> None:
    digest.update(str(len(value)).encode("ascii"))
    digest.update(b":")
    digest.update(value)


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "null": value is None,
        "boolean": type(value) is bool,
        "integer": type(value) is int or (type(value) is float and value.is_integer()),
        "number": type(value) in {int, float},
        "string": type(value) is str,
        "array": type(value) is list,
        "object": type(value) is dict,
    }[expected]


def _valid_date_time(value: str) -> bool:
    match = _DATE_TIME_PATTERN.fullmatch(value)
    if match is None:
        return False
    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    leap_year = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    month_lengths = (
        31,
        29 if leap_year else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    )
    return day <= month_lengths[month - 1]
