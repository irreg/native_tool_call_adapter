import copy
import json
import xml.etree.ElementTree as ET
from typing import Any

from parser import (
    JsonObj,
    build_tool_schema,
    convert_obj_to_xml_with_id,
    convert_xml_example_to_json,
    convert_xml_to_obj_exclude_id,
    extract_tools_section,
    extract_xml_blocks_for_tool,
    parse_tools_section,
    remove_duplicated_section_from_doc,
)


class Parser:
    def __init__(self, schemas: list[JsonObj]):
        self._schemas = schemas

    @property
    def schemas(self) -> list[JsonObj]:
        return self._schemas

    def modify_xml_messages_to_tool_calls(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[JsonObj],
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
                    xml_tool_calls = extract_xml_blocks_for_tool(
                        message["content"],
                        [s["function"]["name"] for s in tool_schemas],
                    )
                    for xml in xml_tool_calls:
                        try:
                            name, json_dict, id_value = convert_xml_to_obj_exclude_id(
                                xml, tool_schemas
                            )
                        except ET.ParseError:
                            continue  # Skip if content is not valid XML
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

    def modify_tool_call_to_xml_message(
        self, name: str, tool_call: str, id: str
    ) -> dict[str, Any]:
        return convert_obj_to_xml_with_id(json.loads(tool_call), root_name=name, id=id)

    def modify_tool_calls_to_xml_messages(
        self,
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


def build_tool_parser(doc: str) -> tuple[Parser, str]:
    tools_md = extract_tools_section(doc)
    new_doc = remove_duplicated_section_from_doc(doc)

    tools = parse_tools_section(tools_md)
    tools_schemas = []
    for t in tools:
        schema = build_tool_schema(t)
        tools_schemas.append(schema)
        # Convert each XML usage into a JSON call sample
        for x in t.xml_samples:
            json_example = convert_xml_example_to_json(t.name, x, tools_schemas)
            new_doc = new_doc.replace(x, json_example)

    return Parser(tools_schemas), new_doc
