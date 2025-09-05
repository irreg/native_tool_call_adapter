import re
import xml.etree.ElementTree as ET

from model import JsonObj


def from_unescaped_string(raw_str: str, schemas: list[JsonObj]) -> ET.Element:
    """Deserialize str without escape"""

    def parse_text(
        part_str: str, inner_schemas: dict[str, JsonObj]
    ) -> tuple[list[ET.Element], int]:
        """Parse inner elements"""
        match = re.search(
            rf"(?P<head><(?P<tag>{'|'.join(inner_schemas.keys())})(?:\s[^>]*)?>)(?P<content>[\s\S]*?)(?P<foot></(?P=tag)>)",
            part_str,
        )
        if not match:
            return [], 0
        new_node = ET.fromstring(match.group("head") + match.group("foot"))
        inner_raw = match.group("content")
        schema = inner_schemas[new_node.tag]
        if schema["type"] == "object" and "value" in schema["properties"]:
            schema = schema["properties"]["value"]

        is_array = schema["type"] == "array"

        original_schema = schema
        if is_array:
            schema = schema["items"]
        if schema["type"] in ("string", "boolean", "number"):
            new_node.text = inner_raw
        elif schema["type"] == "object":
            pos = match.end("head")
            while True:
                result, end_pos = parse_text(
                    part_str[pos : match.start("foot")], schema["properties"]
                )
                if not result:
                    break
                pos += end_pos
                new_node.extend(result)
        else:
            # Not Implemented
            pass
        if is_array:
            result, end_pos = parse_text(part_str[match.end() :], original_schema)
            return [new_node].extend(result), match.end() + end_pos
        else:
            return [new_node], match.end()

    elem, _ = parse_text(
        raw_str,
        {
            schema["function"]["name"]: schema["function"]["parameters"]
            for schema in schemas
        },
    )
    return elem[0]


def to_unescaped_string(elem: ET.Element) -> str:
    """Serialize ElementTree.Element without escape"""

    # serialize attrib
    attrs = "".join(f' {k}="{v}"' for k, v in elem.attrib.items())
    start_tag = f"<{elem.tag}{attrs}>"
    end_tag = f"</{elem.tag}>"

    inner = elem.text or ""

    for child in list(elem):
        inner += to_unescaped_string(child)

    return f"{start_tag}{inner}{end_tag}"
