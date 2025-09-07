import copy
import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from extra_parser import (
    ApplyDiffParser,
    ExtraParserIF,
    ReplaceInFileParser,
    UpdateTodoListParser,
    UseMcpToolParser,
)
from model import JsonObj
from parser import (
    ToolDoc,
    build_tool_schema,
    convert_obj_to_xml_with_id,
    convert_xml_element_to_obj,
    convert_xml_to_obj_exclude_id,
    extract_section,
    extract_xml_blocks_for_tool,
    parse_tools_section,
    parse_xml_example,
    remove_duplicated_section_from_doc,
)
from strict_parser import prune_nulls_by_type, strictify_schema


class Parser:
    def __init__(
        self, system_prompt: str, tool_docs: list[ToolDoc], strict: bool = True
    ):
        schemas: list[JsonObj] = []
        modified_schemas: list[JsonObj] = []
        extra_parsers: list[ExtraParserIF] = []
        for t in tool_docs:
            schema = build_tool_schema(t)
            schemas.append(schema)
            extra_parser, modified_schema, extra_replacement = self._get_extra_parser(
                t.tool_md, schema, system_prompt
            )
            if extra_parser:
                extra_parsers.append(extra_parser)
                if isinstance(modified_schema, list):
                    modified_schemas.extend(modified_schema)
                else:
                    modified_schemas.append(modified_schema)
            else:
                modified_schemas.append(schema)
            for before, after in extra_replacement.items():
                system_prompt = system_prompt.replace(before, after)
        self._original_schemas = schemas
        self._schemas = modified_schemas
        strict_schemas = []
        for schema in modified_schemas:
            copied = copy.deepcopy(schema)
            copied["function"]["parameters"] = strictify_schema(
                copied["function"]["parameters"]
            )
            copied["function"]["strict"] = True
            strict_schemas.append(copied)
        self._strict_schemas = strict_schemas
        self._extra_parsers = extra_parsers
        self._system_prompt = system_prompt

    @staticmethod
    def _get_extra_parser(
        doc: str, schema: JsonObj, system_prompt: str
    ) -> tuple[ExtraParserIF | None, JsonObj | list[JsonObj] | None, dict[str, str]]:
        parsers: list[ExtraParserIF] = [
            UpdateTodoListParser(),
            ApplyDiffParser(),
            ReplaceInFileParser(),
            UseMcpToolParser(),
        ]
        for parser in parsers:
            modified_schema, extra_replacement = parser.get_schema(
                doc, schema, system_prompt
            )
            if modified_schema:
                return parser, modified_schema, extra_replacement
        return None, None, {}

    @property
    def schemas(self) -> list[JsonObj]:
        return self._strict_schemas

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def _postconvert_to_tool_call(
        self, name: str, arguments_obj: JsonObj
    ) -> tuple[str, str]:
        for extra_parser in self._extra_parsers:
            name, arguments_obj = extra_parser.postconvert_to_tool_call(
                name, arguments_obj
            )
        return name, json.dumps(arguments_obj, ensure_ascii=False)

    def modify_xml_messages_to_tool_calls(
        self,
        messages: list[dict[str, Any]],
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
                        [s["function"]["name"] for s in self._original_schemas],
                    )
                    for xml in xml_tool_calls:
                        try:
                            name, json_dict, id_value = convert_xml_to_obj_exclude_id(
                                xml, self._original_schemas
                            )
                        except (ET.ParseError, ValueError):
                            continue  # Skip if content is not valid XML
                        name, arguments = self._postconvert_to_tool_call(
                            name, json_dict
                        )
                        tool_call = {
                            "type": "function",
                            "id": id_value,
                            "function": {
                                "name": name,
                                "arguments": arguments,
                            },
                        }
                        tool_calls.append(tool_call)
                        last_id_value.append(id_value)
                        last_tool_name.append(name)
                        message["content"] = message["content"].replace(xml, "")
                    if tool_calls:
                        message["tool_calls"] = tool_calls
                    continue
            if (
                message["role"] == "user"
                and isinstance(message["content"], list)
                and message["content"]
            ):
                content_head = message["content"][0].get("text") or ""
                if last_id_value and re.match(
                    rf"^\[{last_tool_name[0]}\b", content_head
                ):
                    # If user message has tool calls, append last tool call
                    message["role"] = "tool"
                    message["tool_call_id"] = last_id_value[0]
                    last_id_value = last_id_value[1:]
                    last_tool_name = last_tool_name[1:]
                    continue
                elif content_head.startswith("[ERROR] "):
                    tool_use_section = extract_section(
                        content_head, "Reminder: Instructions for Tool Use"
                    )
                    message["content"][0]["text"] = content_head.replace(
                        tool_use_section, ""
                    )

            last_id_value = []
            last_tool_name = []
        return messages

    def _preconvert_to_xml_message(
        self, name: str, arguments: str
    ) -> tuple[str, JsonObj]:
        arguments_obj = json.loads(arguments.strip())
        strict_schema = next(
            schema
            for schema in self._strict_schemas
            if schema["function"]["name"] == name
        )
        arguments_obj = prune_nulls_by_type(
            arguments_obj, strict_schema["function"]["parameters"]
        )
        for extra_parser in self._extra_parsers:
            name, arguments_obj = extra_parser.preconvert_to_xml(name, arguments_obj)
        return name, arguments_obj

    def _has_schema(self, name: str):
        return any(
            schema["function"]["name"] == name for schema in self._original_schemas
        )

    def modify_tool_call_to_xml_message(
        self, name: str, tool_call: str, id: str
    ) -> str:
        name, arguments = self._preconvert_to_xml_message(name, tool_call)
        if not self._has_schema(name):
            return ""
        return convert_obj_to_xml_with_id(arguments, root_name=name, id=id)

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
                    name, arguments = self._preconvert_to_xml_message(
                        tool_call["function"]["name"],
                        tool_call["function"]["arguments"],
                    )
                    if not self._has_schema(name):
                        continue
                    xml_parts.append(
                        convert_obj_to_xml_with_id(
                            arguments,
                            root_name=name,
                            id=tool_call["id"],
                        )
                    )
                choice["message"]["content"] = (
                    choice["message"].get("content") or ""
                ) + "\n".join(xml_parts)
                if choice["finish_reason"] == "tool_calls":
                    choice["finish_reason"] = "stop"
        return messages

    def convert_xml_example_to_json(self, tool_name: str, xml_str: str) -> str:
        root = parse_xml_example(xml_str)
        assert root.tag == tool_name, (
            f"Unexpected root tag {root.tag}, expected {tool_name}"
        )
        payload = convert_xml_element_to_obj(root, self._original_schemas)
        # The OpenAI "arguments" is everything inside the tool root
        name, arguments = self._postconvert_to_tool_call(tool_name, payload)
        return f"{name} arguments: {arguments}"


def build_tool_parser(system_prompt: str) -> tuple[Parser, str]:
    # Remove xml formatting explanation from doc
    tool_formatting = extract_section(system_prompt, "Tool Use Formatting")
    new_system_prompt = system_prompt.replace(tool_formatting, "", count=1)

    # parse tools
    tools_md = extract_section(system_prompt, "Tools")
    new_system_prompt = remove_duplicated_section_from_doc(new_system_prompt)

    tools = parse_tools_section(tools_md)

    parser = Parser(new_system_prompt, tools)
    new_system_prompt = parser.system_prompt
    for t in tools:
        # Convert each XML usage into a JSON call sample
        for x in t.xml_samples:
            json_example = parser.convert_xml_example_to_json(t.name, x)
            new_system_prompt = new_system_prompt.replace(x, json_example)

    return parser, new_system_prompt
