import copy
import json
import re
from abc import ABC, abstractmethod

from mcp_parser import build_mcp_tool_schema, extract_mcp_section, parse_mcp_sections
from model import JsonObj
from parser import extract_block_after_label


class ExtraParserIF(ABC):
    tool_name: str

    @staticmethod
    @abstractmethod
    def search_patterns(text: str) -> list[dict[str, str]]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def get_schema(
        doc: str, original_schema: JsonObj, system_prompt: str
    ) -> tuple[JsonObj | list[JsonObj] | None, dict[str, str]]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def postconvert_to_tool_call(
        tool_name: str, arguments: JsonObj
    ) -> tuple[str, JsonObj]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def preconvert_to_xml(tool_name: str, arguments: JsonObj) -> tuple[str, JsonObj]:
        raise NotImplementedError


class ReplaceInFileParser(ExtraParserIF):
    tool_name = "replace_in_file"

    @staticmethod
    def search_patterns(text: str) -> list[dict[str, str]]:
        pattern = re.compile(
            r"(?P<indent>[ \t]*)------- SEARCH\n(?P<search>.*?)\n"
            r"(?P=indent)=======\n(?P<replace>.*?)\n"
            r"(?P=indent)\+\+\+\+\+\+\+ REPLACE",
            re.DOTALL,
        )

        results = []
        for m in pattern.finditer(text):
            results.append(
                {
                    "matched": m.group(0),
                    "search": m.group("search"),
                    "replace": m.group("replace"),
                }
            )
        return results

    @staticmethod
    def get_schema(
        doc: str, original_schema: JsonObj, system_prompt: str
    ) -> tuple[JsonObj | None, dict[str, str]]:
        if original_schema["function"]["name"] != ReplaceInFileParser.tool_name:
            return None, {}
        block = extract_block_after_label(doc, "Parameters:")
        params = ReplaceInFileParser.search_patterns(block)
        if not params:
            return None, {}

        original_schema = copy.deepcopy(original_schema)
        if diff := original_schema["function"]["parameters"]["properties"].get(
            "diff", {}
        ):
            diff["type"] = "array"
            diff["items"] = {
                "type": "object",
                "properties": {
                    "SEARCH": {
                        "type": "string",
                        "description": params[0]["search"],
                    },
                    "REPLACE": {
                        "type": "string",
                        "description": params[0]["replace"],
                    },
                },
                "required": ["SEARCH", "REPLACE"],
            }
            return original_schema, {}
        else:
            return None, {}

    @staticmethod
    def postconvert_to_tool_call(
        tool_name: str, arguments: JsonObj
    ) -> tuple[str, JsonObj]:
        if tool_name != ReplaceInFileParser.tool_name:
            return tool_name, arguments
        diff = arguments.get("diff")
        if not isinstance(diff, str):
            # fallback
            return tool_name, arguments
        patterns = ReplaceInFileParser.search_patterns(diff)
        if not patterns:
            # fallback
            return tool_name, arguments
        arguments = copy.deepcopy(arguments)
        arguments["diff"] = patterns
        return tool_name, arguments

    @staticmethod
    def preconvert_to_xml(tool_name: str, arguments: JsonObj) -> tuple[str, JsonObj]:
        if (
            tool_name != ReplaceInFileParser.tool_name
            or "diff" not in arguments
            or isinstance(arguments["diff"], str)
        ):
            return tool_name, arguments
        elif not isinstance(arguments["diff"], list):
            org_diffs = [arguments["diff"]]
        else:
            org_diffs = arguments["diff"]

        diffs = []
        for diff in org_diffs:
            if isinstance(diff, dict):
                search = diff.get("SEARCH", "")
                replace = diff.get("REPLACE", "")
                diffs.append(
                    f"------- SEARCH\n{search}\n=======\n{replace}\n+++++++ REPLACE"
                )
        arguments = copy.deepcopy(arguments)
        arguments["diff"] = "\n".join(diffs)
        return tool_name, arguments


class ApplyDiffParser(ExtraParserIF):
    tool_name = "apply_diff"

    @staticmethod
    def search_patterns(text: str) -> list[dict[str, str]]:
        pattern = re.compile(
            r"<<<<<<< SEARCH\n"
            r":start_line:\s*(?P<start_line>.*?)\n"
            r"-------\n(?P<search>.*?)\n"
            r"=======\n(?P<replace>.*?)\n"
            r">>>>>>> REPLACE",
            re.DOTALL,
        )

        results = []
        for m in pattern.finditer(text):
            results.append(
                {
                    "matched": m.group(0),
                    "start_line": m.group("start_line"),
                    "search": m.group("search"),
                    "replace": m.group("replace"),
                }
            )
        return results

    @staticmethod
    def get_schema(
        doc: str, original_schema: JsonObj, system_prompt: str
    ) -> tuple[JsonObj | None | dict[str, str]]:
        if original_schema["function"]["name"] != ApplyDiffParser.tool_name:
            return None, {}
        block = extract_block_after_label(doc, "Diff format:")
        params = ApplyDiffParser.search_patterns(block)
        if not params:
            return None, {}

        original_schema = copy.deepcopy(original_schema)
        if diff := original_schema["function"]["parameters"]["properties"].get(
            "diff", {}
        ):
            diff["type"] = "array"
            diff["items"] = {
                "type": "object",
                "properties": {
                    "start_line": {
                        "type": "string",
                        "description": params[0]["start_line"],
                    },
                    "SEARCH": {
                        "type": "string",
                        "description": params[0]["search"],
                    },
                    "REPLACE": {
                        "type": "string",
                        "description": params[0]["replace"],
                    },
                },
                "required": ["start_line", "SEARCH", "REPLACE"],
            }
            return original_schema, {}
        else:
            return None, {}

    @staticmethod
    def postconvert_to_tool_call(
        tool_name: str, arguments: JsonObj
    ) -> tuple[str, JsonObj]:
        if tool_name != ApplyDiffParser.tool_name:
            return tool_name, arguments
        diff = arguments.get("diff")
        if not isinstance(diff, str):
            # fallback
            return tool_name, arguments
        patterns = ApplyDiffParser.search_patterns(diff)
        if not patterns:
            # fallback
            return tool_name, arguments
        arguments = copy.deepcopy(arguments)
        arguments["diff"] = patterns
        return tool_name, arguments

    @staticmethod
    def preconvert_to_xml(tool_name: str, arguments: JsonObj) -> tuple[str, JsonObj]:
        if (
            tool_name != ApplyDiffParser.tool_name
            or "diff" not in arguments
            or isinstance(arguments["diff"], str)
        ):
            return tool_name, arguments
        elif not isinstance(arguments["diff"], list):
            org_diffs = [arguments["diff"]]
        else:
            org_diffs = arguments["diff"]
        diffs = []
        for diff in org_diffs:
            if isinstance(diff, dict):
                search = re.sub(
                    r"^(<<<<<<< SEARCH|=======|>>>>>>> REPLACE)$",
                    r"\\\1",
                    diff.get("SEARCH", ""),
                    flags=re.MULTILINE,
                )
                replace = re.sub(
                    r"^(<<<<<<< SEARCH|=======|>>>>>>> REPLACE)$",
                    r"\\\1",
                    diff.get("REPLACE", ""),
                    flags=re.MULTILINE,
                )
                diffs.append(
                    f"<<<<<<< SEARCH\n"
                    f":start_line:{diff.get('start_line', 0)}\n"
                    f"-------\n{search}\n"
                    f"=======\n{replace}\n"
                    f">>>>>>> REPLACE"
                )
        arguments = copy.deepcopy(arguments)
        arguments["diff"] = "\n".join(diffs)
        return tool_name, arguments


class UpdateTodoListParser(ExtraParserIF):
    tool_name = "update_todo_list"

    @staticmethod
    def search_patterns(text: str) -> list[dict[str, str]]:
        pattern = re.compile(r"^\[(?P<status>[^\]]+)\]\s*(?P<todo>.+?)$", re.MULTILINE)

        results = []
        for m in pattern.finditer(text):
            results.append(
                {
                    "todo": m.group("todo"),
                    "status": m.group("status"),
                    # "matched": m.group(0),
                }
            )
        return results

    @staticmethod
    def get_schema(
        doc: str, original_schema: JsonObj, system_prompt: str
    ) -> tuple[JsonObj | None, dict[str, str]]:
        if original_schema["function"]["name"] != UpdateTodoListParser.tool_name:
            return None, {}
        for block_name in ("Usage Example:", "Usage:", "Example:"):
            block = extract_block_after_label(doc, block_name)
            params = UpdateTodoListParser.search_patterns(block)
            if params:
                break
        else:
            return None, {}

        original_schema = copy.deepcopy(original_schema)
        if todos := original_schema["function"]["parameters"]["properties"].get(
            "todos", {}
        ):
            todos["type"] = "array"
            todos["items"] = {
                "type": "object",
                "properties": {
                    "todo": {
                        "type": "string",
                        "description": params[0]["todo"],
                    },
                    "status": {
                        "type": "string",
                        "description": params[0]["status"],
                    },
                },
                "required": ["todo", "status"],
            }
            required = original_schema["function"]["parameters"].get("required") or []
            required.append("todos")
            original_schema["function"]["parameters"]["required"] = required
            return original_schema, {}
        else:
            return None, {}

    @staticmethod
    def postconvert_to_tool_call(
        tool_name: str, arguments: JsonObj
    ) -> tuple[str, JsonObj]:
        if tool_name != UpdateTodoListParser.tool_name:
            return tool_name, arguments
        todos = arguments.get("todos")
        if not isinstance(todos, str):
            # fallback
            return tool_name, arguments
        patterns = UpdateTodoListParser.search_patterns(todos)
        if not patterns:
            # fallback
            return tool_name, arguments
        arguments = copy.deepcopy(arguments)
        arguments["todos"] = patterns
        return tool_name, arguments

    @staticmethod
    def preconvert_to_xml(tool_name: str, arguments: JsonObj) -> tuple[str, JsonObj]:
        if (
            tool_name != UpdateTodoListParser.tool_name
            or "todos" not in arguments
            or isinstance(arguments["todos"], str)
        ):
            return tool_name, arguments
        elif not isinstance(arguments["todos"], list):
            org_todos = [arguments["todos"]]
        else:
            org_todos = arguments["todos"]
        todos = []
        for todo in org_todos:
            if isinstance(todo, dict):
                status = (
                    re.match(
                        r"^(\[)?(?P<status>.*?)(\])?$", todo.get("status", " ")
                    ).group("status")
                    or " "
                )
                todos.append(f"[{status}] {todo.get('todo', '').replace('\n', ' ')}")
        arguments = copy.deepcopy(arguments)
        arguments["todos"] = "\n".join(todos)
        return tool_name, arguments


class UseMcpToolParser(ExtraParserIF):
    tool_name = "use_mcp_tool"

    @staticmethod
    def search_patterns(text: str) -> list[dict[str, str]]:
        raise NotImplementedError

    @staticmethod
    def get_schema(
        doc: str, original_schema: JsonObj, system_prompt: str
    ) -> tuple[list[JsonObj] | None, dict[str, str]]:
        if original_schema["function"]["name"] != UseMcpToolParser.tool_name:
            return None, {}
        mcp_doc = extract_mcp_section(system_prompt)
        tool_docs, remove_pattern = parse_mcp_sections(mcp_doc)
        try:
            schemas = [build_mcp_tool_schema(tool_doc) for tool_doc in tool_docs]
            if schemas:
                return schemas, remove_pattern
        except Exception:
            pass
        return None, {}

    @staticmethod
    def postconvert_to_tool_call(
        tool_name: str, arguments: JsonObj
    ) -> tuple[str, JsonObj]:
        if tool_name != UseMcpToolParser.tool_name:
            return tool_name, arguments
        server_name = arguments.get("server_name")
        mcp_tool_name = arguments.get("tool_name")
        inner_arguments = arguments.get("arguments")
        if server_name is None or inner_arguments is None or mcp_tool_name is None:
            # fallback
            return tool_name, arguments
        try:
            inner_argument_obj = json.loads(inner_arguments.strip())
        except Exception:
            # fallback
            return tool_name, arguments
        return (
            f"{UseMcpToolParser.tool_name}.{server_name}.{mcp_tool_name}",
            inner_argument_obj,
        )

    @staticmethod
    def preconvert_to_xml(tool_name: str, arguments: JsonObj) -> tuple[str, JsonObj]:
        match = re.match(
            rf"^{UseMcpToolParser.tool_name}\.(?P<server_name>[^\.]+)\.(?P<tool_name>.+)$",
            tool_name,
        )
        if not match:
            return tool_name, arguments

        new_arguments = {
            "server_name": match.group("server_name"),
            "tool_name": match.group("tool_name"),
            "arguments": json.dumps(arguments, ensure_ascii=False),
        }
        return UseMcpToolParser.tool_name, new_arguments
