import copy
import json
import re
import textwrap
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Union


@dataclass
class ToolDoc:
    name: str
    description: str = ""
    parameters_markdown: str = ""
    xml_samples: list[str] = field(default_factory=list)


def extract_tools_section(doc: str) -> str:
    # Extract from "# Tools" up to the next top-level heading "# "
    m = re.search(r"^#\s+Tools\b", doc, flags=re.MULTILINE)
    if not m:
        return ""
    start = m.start()
    m2 = re.search(r"^#\s+", doc[m.end() :], flags=re.MULTILINE)
    end = len(doc) if not m2 else m.end() + m2.start()
    return doc[start:end]


def parse_tools_section(tools_md: str) -> list[ToolDoc]:
    # Split by "## <tool_name>"
    chunks = re.split(r"^##\s+(\w+)\s*$", tools_md, flags=re.MULTILINE)
    # re.split keeps delimiters: [before, name1, body1, name2, body2,...]
    out: list[ToolDoc] = []
    for i in range(1, len(chunks), 2):
        name = chunks[i].strip()
        body = chunks[i + 1]
        desc = extract_block_after_label(body, "Description:")
        params = extract_block_after_label(body, "Parameters:")
        params2 = extract_block_after_label(body, "Required Parameters:")
        params3 = extract_block_after_label(body, "Optional Parameters:")
        combined_params = (
            params
            + "\n"
            + params2
            + "\n"
            + re.sub(r"^(\w+: )", r"\1(optional) ", params3)
        )
        xmls = extract_xml_blocks_for_tool(
            body.replace(desc, "")
            .replace(params, "")
            .replace(params2, "")
            .replace(params3, ""),
            name,
        )
        out.append(
            ToolDoc(
                name=name,
                description=desc.strip(),
                parameters_markdown=combined_params.strip(),
                xml_samples=xmls,
            )
        )
    return out


def extract_block_after_label(body: str, label: str) -> str:
    """
    Get specified label block (e.g. 'Description:', 'Parameters:' etc.)
    """
    # Allow text to continue on the same line after the label
    pattern = re.compile(
        rf"^(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*([\s\S]*?)(?=^(\*\*)?((Required |Optional )?Parameters?:|##?\s+|Usages?:|(Usage )?Examples?(\b[\w ]+)?:|\Z)(\*\*)?)",
        flags=re.MULTILINE,
    )
    m = pattern.search(body)
    if not m:
        return ""
    block = (m.group(1) or "").strip()

    return block


def extract_xml_blocks_for_tool(body: str, tool_name: str | list[str]) -> list[str]:
    # Find all <tool_name>...</tool_name> blocks
    tag_name = (
        tool_name
        if isinstance(tool_name, str)
        else f"(?:{'|'.join(map(re.escape, tool_name))})"
    )
    pattern = re.compile(rf"<{tag_name}\b[\s\S]*?</{tag_name}>", re.IGNORECASE)
    return [m.group(0) for m in pattern.finditer(body)]


# -------- Parameters markdown parsing (bullets) --------


@dataclass
class ParamNode:
    name: str
    description: str = ""
    required: bool = True
    children: list["ParamNode"] = field(default_factory=list)
    indent: int = 0


def parse_parameters_bullets(md: str) -> list[ParamNode]:
    """
    Parse a simple indented bullet list such as:
    - args: Contains one or more file elements...
      - file: ...
        - path: (required) File path
    Returns:
        a forest (list) of ParamNode trees.
    """
    lines = [ln for ln in md.splitlines() if ln.strip() != ""]
    bullet_re = re.compile(r"^(\s*)-\s*(\w+)\s*:\s*(.*)$")
    nodes: list[ParamNode] = []
    stack: list[ParamNode] = []

    for ln in lines:
        m = bullet_re.match(ln)
        if not m:
            # Non-bullet line: append to the last node's description if exists
            if stack:
                stack[-1].description = (
                    stack[-1].description + "\n" + ln.strip()
                ).strip()
            continue
        indent = len(m.group(1).replace("\t", "    "))
        name = m.group(2).strip()
        desc = m.group(3).strip()
        req = "(optional)" not in desc.lower()
        desc = desc.replace("(required)", "").replace("(Required)", "").strip()

        node = ParamNode(name=name, description=desc, required=req, indent=indent)
        # attach to parent by indent
        while stack and stack[-1].indent >= indent:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            nodes.append(node)
        stack.append(node)

    return nodes


def flatten_param_info(nodes: list[ParamNode]) -> tuple[dict[str, str], set]:
    """
    Returns:
        - descriptions: map from parameter name (lower) -> description
        - required_names: set of parameter names marked required
    Notes:
        this is name-based (not path-aware), but works well for common cases.
    """
    descs: dict[str, str] = {}
    reqs: set = set()

    def dfs(n: ParamNode) -> None:
        key = n.name.lower()
        if n.description and key not in descs:
            descs[key] = n.description
        if n.required:
            reqs.add(key)
        for c in n.children:
            dfs(c)

    for n in nodes:
        dfs(n)
    return descs, reqs


# -------- XML analysis to derive schema --------


def parse_xml_example(xml_str: str) -> ET.Element:
    # Normalize indentation
    xml_str = textwrap.dedent(xml_str).strip()
    try:
        return ET.fromstring(xml_str)
    except ET.ParseError:

        def replace_pseudo_tags_in_parentheses(text: str) -> str:
            def repl_paren(match):
                content = match.group(1)
                # 括弧内のタグを変換
                converted = re.sub(r"</?([\w]*)\s*/?>", r"`\1`", content)
                return f"({converted})"

            return re.sub(r"\(([^)]*)\)", repl_paren, text)

        xml_str = replace_pseudo_tags_in_parentheses(xml_str)
        try:
            return ET.fromstring(xml_str)
        except ET.ParseError:
            xml_str = xml_str.replace("&", "&amp;")
            return ET.fromstring(xml_str)  # Try again after replacing ampersands


def group_children_by_tag(elem: ET.Element) -> dict[str, list[ET.Element]]:
    groups: dict[str, list[ET.Element]] = defaultdict(list)
    for child in list(elem):
        groups[child.tag].append(child)
    return groups


JsonVal = Union[str, "JsonArray", "JsonObj"]
JsonArray = list[JsonVal]
JsonObj = dict[str, JsonVal]


def convert_xml_element_to_obj(
    elem: ET.Element, tool_schemas: list[JsonObj]
) -> JsonObj:
    """
    Convert one XML sample to a Python structure.
    - Element with only text -> string
    - Element with children -> dict
    - Repeated tags under same parent -> list
    """
    schema = next((s for s in tool_schemas if s["function"]["name"] == elem.tag), None)
    assert schema is not None, f"No schema found for tool {elem.tag}"

    def inner(elem: ET.Element, inner_schema: JsonObj) -> JsonObj:
        children = list(elem)
        if not children:
            if inner_schema.get("properties", {}).get("value"):
                return {"value": (elem.text or ""), **elem.attrib}
            return elem.text or ""
        groups = group_children_by_tag(elem)
        obj: JsonObj = {}
        schema_props = inner_schema["properties"]
        for tag, elems in groups.items():
            tag_schema = schema_props[tag]
            if tag_schema["type"] == "array":
                obj[tag] = [inner(e, tag_schema["items"]) for e in elems]
            else:
                if value_schema := inner_schema.get("properties", {}).get("value"):
                    obj[tag] = {"value": inner(elems[0], value_schema), **elem.attrib}
                else:
                    obj[tag] = inner(elems[0], tag_schema)
        return obj

    return inner(elem, schema["function"]["parameters"])


def collect_structure_stats(
    root: ET.Element,
) -> tuple[dict[tuple[tuple[str, ...], str], int], dict[tuple[str, ...], set[str]]]:
    """
    Collect structure statistics across all samples to infer arrays and requireds

    Returns:
        - child_counts[(path_tuple, child_tag)] = max multiplicity seen under that parent across this sample
    """
    child_counts: dict[tuple[tuple[str, ...], str], int] = defaultdict(int)
    attribs: dict[tuple[str, ...], set[str]] = defaultdict(set)

    def walk(e: ET.Element, path: tuple[str, ...]) -> None:
        groups = group_children_by_tag(e)
        for tag, elems in groups.items():
            child_counts[(path, tag)] = max(child_counts[(path, tag)], len(elems))
            for child_elem in elems:
                walk(child_elem, path + (tag,))
        for attr_name in e.attrib:
            attribs[path].add(attr_name)

    walk(root, (root.tag,))
    return child_counts, attribs


def merge_stats(samples: list[ET.Element]) -> dict[str, Any]:
    total_child_counts: dict[tuple[tuple[str, ...], str], int] = defaultdict(int)
    total_attribs: dict[tuple[str, ...], set[str]] = defaultdict(set)
    child_present_samples: dict[tuple[tuple[str, ...], str], int] = defaultdict(int)

    for root in samples:
        child_counts, attribs = collect_structure_stats(root)
        # child max multiplicity
        for k, v in child_counts.items():
            total_child_counts[k] = max(total_child_counts[k], v)
            # presence (>=1) in this sample
            child_present_samples[k] += 1
        total_attribs.update(attribs)

    return {
        "child_max": total_child_counts,
        "child_presence": child_present_samples,
        "attribs": total_attribs,
    }


def build_schema_from_xml_samples(
    tool_name: str,
    xml_samples: list[str],
    param_descs: dict[str, str],
    required_names: set,
) -> JsonObj:
    if not xml_samples:
        # Fallback minimal schema
        return {
            "name": tool_name,
            "description": "",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }

    roots = [parse_xml_example(x) for x in xml_samples]
    stats = merge_stats(roots)

    # Build tree of children for all paths
    children_by_path: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for (path, child), _ in stats["child_max"].items():
        if child not in children_by_path[path]:
            children_by_path[path].append(child)

    def is_array(path: tuple[str, ...], child: str) -> bool:
        return stats["child_max"][(path, child)] > 1

    def required_children(path: tuple[str, ...]) -> list[str]:
        req = []
        for child in children_by_path.get(path, []):
            if stats["child_presence"][(path, child)] < len(xml_samples):
                continue  # not present in all samples
            if child.lower() in required_names and child not in req:
                req.append(child)
        return req

    def node_schema(path: tuple[str, ...]) -> tuple[JsonObj, list[str]]:
        # path is the parent; we build a schema for this element (object with its children)
        props: JsonObj = {}
        for child in children_by_path.get(path, []):
            child_path = path + (child,)
            base = {}
            # attach description if available (leaf only by name-based lookup)
            if desc := param_descs.get(child.lower()):
                base["description"] = desc
            # Does child itself have children?
            has_grand = len(children_by_path.get(child_path, [])) > 0
            has_attrib = child_path in stats["attribs"]
            if has_grand:
                base["type"] = "object"
                # recurse for objects
                base["properties"], base["required"] = node_schema(child_path)
            else:
                base["type"] = "string"
            if has_attrib:
                base = {
                    "properties": {
                        "value": base,
                        **{
                            k: {"type": "str"}
                            for k in stats["attribs"][(child_path, child)]
                        },
                    },
                    "type": "object",
                    "required": ["value"],
                }

            # wrap as array if multiplicity > 1 in any sample
            if is_array(path, child):
                schema = {"type": "array", "items": base}
            else:
                schema = base
            props[child] = schema

        req = required_children(path)
        return props, req

    # Root is the tool element; OpenAI parameters correspond to its children (arguments)
    root_path = (roots[0].tag,)
    root_props, root_req = node_schema(root_path)

    # If the root has exactly one child (common for tools), we keep full structure under parameters.
    # Otherwise, we expose all children as parameters.
    parameters_schema = {
        "type": "object",
        "properties": root_props,
        "required": root_req,
    }
    return {
        "name": tool_name,
        "description": "",
        "parameters": parameters_schema,
    }


def build_tool_schema(tool: ToolDoc) -> JsonObj:
    # Parse parameter bullets (optional enrichment)
    nodes = parse_parameters_bullets(tool.parameters_markdown)
    param_descs, required_names = flatten_param_info(nodes)

    schema = build_schema_from_xml_samples(
        tool.name, tool.xml_samples, param_descs, required_names
    )
    # Attach tool-level description if present
    if tool.description:
        schema["description"] = tool.description
    return {"type": "function", "function": schema}


def convert_xml_example_to_json(
    tool_name: str, xml_str: str, schemas: list[JsonObj]
) -> str:
    root = parse_xml_example(xml_str)
    assert root.tag == tool_name, (
        f"Unexpected root tag {root.tag}, expected {tool_name}"
    )
    payload = convert_xml_element_to_obj(root, schemas)
    # The OpenAI "arguments" is everything inside the tool root
    return json.dumps(
        {"name": tool_name, "arguments": json.dumps(payload, ensure_ascii=False)},
        indent=2,
        ensure_ascii=False,
    )


def generate_tool_schemas(doc: str) -> tuple[list[JsonObj], str]:
    tools_md = extract_tools_section(doc)
    tools = parse_tools_section(tools_md)
    tools_schemas = []
    new_doc = doc

    for t in tools:
        schema = build_tool_schema(t)
        tools_schemas.append(schema)
        # Convert each XML usage into a JSON call sample
        for x in t.xml_samples:
            json_example = convert_xml_example_to_json(t.name, x, tools_schemas)
            new_doc = new_doc.replace(x, json_example)

    # Remove duplicated sections from the doc
    new_doc = re.sub(
        r"^(?:\*\*)?(Required |Optional )?(Description|Parameter)s?:(?:\*\*)?\s*([\s\S]*?)(?=^(\*\*)?((Required |Optional ) ?Parameters?:|##?\s+|Usages?:|(Usage )?Examples?(\b[\w ]+)?:|\Z)(\*\*)?)",
        "",
        new_doc,
        flags=re.MULTILINE,
    )
    return tools_schemas, new_doc


def convert_obj_to_xml_with_id(
    json_obj: JsonObj, root_name: str = "root", id: str = ""
) -> str:
    def build_xml_element(parent: ET.Element, obj: JsonObj) -> None:
        if isinstance(obj, dict):
            if "value" in obj:
                if obj["value"] is None or isinstance(obj["value"], str):
                    parent.text = obj["value"]
                else:
                    build_xml_element(parent, obj["value"])
                parent.attrib = {k: v for k, v in obj.items() if k != "value"}
            else:
                for key, value in obj.items():
                    if isinstance(value, list):
                        for item in value:
                            item_elem = ET.SubElement(
                                parent, key
                            )  # Use the same tag for list items
                            build_xml_element(item_elem, item)
                    else:
                        child = ET.SubElement(parent, key)
                        build_xml_element(child, value)
        else:
            parent.text = str(obj)

    root = ET.Element(root_name)
    build_xml_element(root, json_obj)
    ET.SubElement(root, "id").text = id  # Add id as a child element
    return ET.tostring(root, encoding="unicode")


def modify_tool_calls_to_xml_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    messages = copy.deepcopy(messages)
    for choice in messages.get("choices", []):
        if choice["message"]["role"] == "assistant" and choice["message"].get(
            "tool_calls"
        ):
            xml_parts = []
            for tool_call in choice["message"]["tool_calls"]:
                xml_parts.append(
                    convert_obj_to_xml_with_id(
                        json.loads(tool_call["function"]["arguments"]),
                        root_name=tool_call["function"]["name"],
                        id=tool_call["id"],
                    )
                )
            choice["message"]["content"] = (
                choice["message"].get("content") or ""
            ) + "\n".join(xml_parts)
            if choice["finish_reason"] == "tool_calls":
                choice["finish_reason"] = "stop"
    return messages


def modify_tool_call_to_xml_message(
    name: str, tool_call: str, id: str
) -> dict[str, Any]:
    return convert_obj_to_xml_with_id(json.loads(tool_call), root_name=name, id=id)


def convert_xml_to_obj_exclude_id(
    xml_string: str, tool_schemas: list[JsonObj]
) -> tuple[str, JsonObj, str]:
    root = ET.fromstring(xml_string)

    # Get id tag value under root and remove it
    id_value = None
    for child in list(root):
        if child.tag == "id":
            id_value = child.text
            root.remove(child)
            break

    return root.tag, convert_xml_element_to_obj(root, tool_schemas), id_value


def modify_xml_messages_to_tool_calls(
    messages: list[dict[str, Any]], tool_schemas: list[JsonObj]
) -> list[dict[str, Any]]:
    messages = copy.deepcopy(messages)
    last_id_value: list[str] | None = []
    last_tool_name: list[str] | None = []
    for message in messages:
        if message["role"] == "assistant":
            if message["content"] and isinstance(message["content"], str):
                tool_calls = []
                last_id_value = []
                last_tool_name = []
                # Parse XML content
                try:
                    xml_tool_calls = extract_xml_blocks_for_tool(
                        message["content"],
                        [s["function"]["name"] for s in tool_schemas],
                    )
                    for xml in xml_tool_calls:
                        name, json_dict, id_value = convert_xml_to_obj_exclude_id(
                            xml, tool_schemas
                        )
                        tool_call = {
                            "type": "function",
                            "id": id_value,
                            "function": {
                                "name": name,
                                "arguments": json.dumps(json_dict, ensure_ascii=False),
                            },
                        }
                        tool_calls.append(tool_call)
                        last_id_value.append(id_value)
                        last_tool_name.append(name)
                        message["content"] = message["content"].replace(xml, "")
                except ET.ParseError:
                    continue  # Skip if content is not valid XML
                message["tool_calls"] = tool_calls
                continue
        if (
            message["role"] == "user"
            and last_id_value
            and isinstance(message["content"], list)
            and message["content"]
            and (message["content"][0].get("text") or "").startswith(
                f"[{last_tool_name[0]} "
            )
        ):
            # If user message has tool calls, append last tool call
            message["role"] = "tool"
            message["tool_call_id"] = last_id_value[0]
            last_id_value = last_id_value[1:]
            last_tool_name = last_tool_name[1:]
            continue
        last_id_value = []
        last_tool_name = []
    return messages
