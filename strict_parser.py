import copy
from functools import partial
from typing import Any, Callable

from model import AnyJsonObj, AnyJsonVal


def _resolve_ref(
    ref: str, root_schema: AnyJsonObj, processed_refs: set[str]
) -> AnyJsonObj:
    if ref in processed_refs:
        return {}
    processed_refs.add(ref)
    if not ref.startswith("#/"):
        raise ValueError(f"Unsupported $ref format: {ref}")
    parts = ref.lstrip("#/").split("/")
    resolved = root_schema
    for part in parts:
        resolved = resolved.get(part)
        if resolved is None:
            raise KeyError(f"Could not resolve $ref: {ref}")
    return resolved


def strictify_schema(schema: AnyJsonObj) -> AnyJsonObj:
    #  Convert variables not marked as required to required and nullable
    schema_copy = copy.deepcopy(schema)
    # # Since a ref that has been processed once does not need to be processed again, use a global set.
    processed_refs = set()
    resolve_ref = partial(
        _resolve_ref, processed_refs=processed_refs, root_schema=schema_copy
    )

    def process(node: AnyJsonObj) -> None:
        if any(
            (key in node)
            for key in (
                "allOf",
                "not",
                "dependentRequired",
                "dependentSchemas",
                "if",
                "then",
                "else",
                "$anchor",
                "$dynamicAnchor",
                "$dynamicRef",
                "$id",
                "patternProperties",
                "prefixItems",
                "unevaluatedItems",
                "unevaluatedProperties",
            )
        ):
            # fallback
            raise ValueError("Unsupported parameter")
        while "$ref" in node:
            node = resolve_ref(node["$ref"])
        for keyword in ("anyOf", "oneOf"):
            items = node.get(keyword) or []
            if not isinstance(items, list):
                continue
            for sub_schema in items:
                process(sub_schema)

        types = node.get("type")
        types = types if isinstance(types, list) else [types]
        if "object" in types:
            props = node.get("properties") or {}
            # make required
            originally_required = node.get("required") or []
            node["required"] = list(props.keys())
            node["additionalProperties"] = False

            if isinstance(props, dict):
                for prop_name, prop_schema in props.items():
                    while "$ref" in node:
                        prop_schema = resolve_ref(prop_schema["$ref"])
                    if prop_name not in originally_required:
                        make_nullable(prop_schema)
                    process(prop_schema)

        if "array" in types:
            process(node.get("items") or node.get("contains") or {})

    def make_nullable(prop_schema: AnyJsonObj) -> None:
        if "type" in prop_schema:
            types = prop_schema["type"]
            types = types if isinstance(types, list) else [types]
            if "null" not in types:
                prop_schema["type"] = types + ["null"]
        for keyword in ("anyOf", "oneOf"):
            if keyword not in prop_schema:
                continue
            schemas = prop_schema[keyword]
            schemas = schemas if isinstance(schemas, list) else [schemas]
            for schema in schemas:
                types = schema.get("type")
                types = types if isinstance(types, list) else [types]
                if "null" in types:
                    break
            else:
                prop_schema[keyword] = schemas + [{"type": "null"}]

    process(schema_copy)
    return schema_copy


primitive_type_table = {
    "string": str,
    "number": (int, float),
    "integer": (int, float),
    "boolean": bool,
}


def _resolve_schema(
    data: AnyJsonVal,
    schemas: list[AnyJsonObj],
    resolve_ref: Callable[[str, set[str]], AnyJsonObj],
) -> AnyJsonObj | None:
    # Search for a matching schema
    for schema in schemas:

        def check_schema(
            data: AnyJsonVal, schema: AnyJsonObj, required: bool = True
        ) -> AnyJsonObj | None:
            processed_refs = set()
            while "$ref" in schema:
                schema = resolve_ref(schema["$ref"], processed_refs=processed_refs)
            any_of = schema.get("anyOf") or schema.get("oneOf") or []
            if any_of and not required:
                any_of.append({"type": "null"})
            if result := _resolve_schema(data, any_of, resolve_ref):
                return result
            enum = schema.get("enum") or []
            if schema.get("const"):
                enum.append(schema["const"])
            if data in enum:
                return schema
            types = schema.get("type") or []
            if not isinstance(types, list):
                types = [types]
            if isinstance(data, dict) and "object" in types:
                props = schema.get("properties") or {}
                if set(data.keys()) == set(props.keys()):
                    required_params = schema.get("required") or []
                    for key, data_item in data.items():
                        if not check_schema(
                            data_item, props[key], key in required_params
                        ):
                            return None
                    return schema
            if isinstance(data, list) and "array" in types:
                for data_item in data:
                    sub_schema = schema.get("items") or schema.get("contains")
                    if not check_schema(data_item, sub_schema):
                        return None
                return schema
            for t in types:
                intrinsic_type = primitive_type_table.get(t)
                if not required and data is None:
                    return schema
                if intrinsic_type and isinstance(data, intrinsic_type):
                    return schema
            return None

        if result := check_schema(data, schema):
            return result
    return None


_DELETE = object()


def _prune_nulls_by_type(
    data: AnyJsonVal,
    schema: AnyJsonObj,
    resolve_ref: Callable[[str, set[str]], AnyJsonObj],
) -> Any:
    processed_refs = set()
    while "$ref" in schema:
        schema = resolve_ref(schema["$ref"], processed_refs=processed_refs)

    items = schema.get("anyOf") or schema.get("oneOf") or []
    if items:
        if result := _resolve_schema(data, items, resolve_ref):
            schema = result

    types = schema.get("type") or []
    if not isinstance(types, list):
        types = [types]

    if data is None and "null" not in types:
        return _DELETE

    if isinstance(data, dict) and "object" in types:
        props = schema.get("properties") or {}
        out = {}
        for k, v in data.items():
            prop_schema = props.get(k) or {}
            result = _prune_nulls_by_type(v, prop_schema, resolve_ref)
            if result != _DELETE:
                out[k] = result
        return out

    elif isinstance(data, list) and "array" in types:
        item_schema = schema.get("items") or schema.get("contains") or {}
        out = []
        for item in data:
            result = _prune_nulls_by_type(item, item_schema, resolve_ref)
            if result != _DELETE:
                out.append(result)
        return out

    else:
        return data


def prune_nulls_by_type(data: AnyJsonObj, schema: AnyJsonObj) -> AnyJsonObj:
    # Remove when a non-nullable variable becomes null
    resolve_ref = partial(_resolve_ref, root_schema=schema)
    return _prune_nulls_by_type(data, schema, resolve_ref)
