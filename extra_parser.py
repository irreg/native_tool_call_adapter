import copy
import re
from abc import ABC, abstractmethod

from parser import JsonObj, extract_block_after_label


class ExtraParserIF(ABC):
    tool_name: str

    @staticmethod
    @abstractmethod
    def search_patterns(text: str) -> list[dict]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def get_schema(doc: str, original_schema: dict[str, str]) -> dict | None:
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
    def search_patterns(text: str) -> list[dict]:
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
    def get_schema(doc: str, original_schema: dict[str, str]) -> dict | None:
        if original_schema["function"]["name"] != ReplaceInFileParser.tool_name:
            return None
        block = extract_block_after_label(doc, "Parameters:")
        params = ReplaceInFileParser.search_patterns(block)
        if not params:
            return None

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
            return original_schema
        else:
            return None

    @staticmethod
    def postconvert_to_tool_call(
        tool_name: str, arguments: JsonObj
    ) -> tuple[str, JsonObj]:
        if tool_name != ReplaceInFileParser.tool_name:
            return tool_name, arguments
        patterns = ReplaceInFileParser.search_patterns(arguments["diff"])
        if not patterns:
            return tool_name, arguments
        arguments = copy.deepcopy(arguments)
        arguments["diff"] = patterns
        return tool_name, arguments

    @staticmethod
    def preconvert_to_xml(tool_name: str, arguments: JsonObj) -> tuple[str, JsonObj]:
        if (
            tool_name != ReplaceInFileParser.tool_name
            or "diff" not in arguments
            or not isinstance(arguments["diff"], list)
        ):
            return tool_name, arguments
        diffs = []
        for diff in arguments["diff"]:
            if isinstance(diff, dict) and "SEARCH" in diff and "REPLACE" in diff:
                diffs.append(
                    f"------- SEARCH\n{diff['SEARCH']}\n"
                    f"=======\n{diff['REPLACE']}\n"
                    f"+++++++ REPLACE"
                )
            else:
                # fallback
                return tool_name, arguments
        arguments = copy.deepcopy(arguments)
        arguments["diff"] = "\n".join(diffs)
        return tool_name, arguments


class ApplyDiffParser(ExtraParserIF):
    tool_name = "apply_diff"

    @staticmethod
    def search_patterns(text: str) -> list[dict]:
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
    def get_schema(doc: str, original_schema: dict[str, str]) -> dict | None:
        if original_schema["function"]["name"] != ApplyDiffParser.tool_name:
            return None
        block = extract_block_after_label(doc, "Diff format:")
        params = ApplyDiffParser.search_patterns(block)
        if not params:
            return None

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
            return original_schema
        else:
            return None

    @staticmethod
    def postconvert_to_tool_call(
        tool_name: str, arguments: JsonObj
    ) -> tuple[str, JsonObj]:
        if tool_name != ApplyDiffParser.tool_name:
            return tool_name, arguments
        patterns = ApplyDiffParser.search_patterns(arguments["diff"])
        if not patterns:
            return tool_name, arguments
        arguments = copy.deepcopy(arguments)
        arguments["diff"] = patterns
        return tool_name, arguments

    @staticmethod
    def preconvert_to_xml(tool_name: str, arguments: JsonObj) -> tuple[str, JsonObj]:
        if (
            tool_name != ApplyDiffParser.tool_name
            or "diff" not in arguments
            or not isinstance(arguments["diff"], list)
        ):
            return tool_name, arguments

        diffs = []
        for diff in arguments["diff"]:
            if (
                isinstance(diff, dict)
                and "start_line" in diff
                and "SEARCH" in diff
                and "REPLACE" in diff
            ):
                diffs.append(
                    f"<<<<<<< SEARCH\n"
                    f":start_line:{diff['start_line']}\n"
                    f"-------\n{diff['SEARCH']}\n"
                    f"=======\n{diff['REPLACE']}\n"
                    f">>>>>>> REPLACE"
                )
            else:
                # fallback
                return tool_name, arguments
        arguments = copy.deepcopy(arguments)
        arguments["diff"] = "\n".join(diffs)
        return tool_name, arguments


class UpdateTodoListParser(ExtraParserIF):
    tool_name = "update_todo_list"

    @staticmethod
    def search_patterns(text: str) -> list[dict]:
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
    def get_schema(doc: str, original_schema: dict[str, str]) -> dict | None:
        if original_schema["function"]["name"] != UpdateTodoListParser.tool_name:
            return None
        for block_name in ("Usage Example:", "Usage:", "Example:"):
            block = extract_block_after_label(doc, block_name)
            params = UpdateTodoListParser.search_patterns(block)
            if params:
                break
        else:
            return None

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
            return original_schema
        else:
            return None

    @staticmethod
    def postconvert_to_tool_call(
        tool_name: str, arguments: JsonObj
    ) -> tuple[str, JsonObj]:
        if tool_name != UpdateTodoListParser.tool_name:
            return tool_name, arguments
        patterns = UpdateTodoListParser.search_patterns(arguments["todos"])
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
            or not isinstance(arguments["todos"], list)
        ):
            return tool_name, arguments

        diffs = []
        for diff in arguments["todos"]:
            if isinstance(diff, dict) and "todo" in diff and "status" in diff:
                status = (
                    re.match(r"^(\[)?(?P<status>.*?)(\])?$", diff["status"]).group(
                        "status"
                    )
                    or " "
                )
                diffs.append(f"[{status}] {diff['todo'].replace('\n', ' ')}")
            else:
                # fallback
                return tool_name, arguments
        arguments = copy.deepcopy(arguments)
        arguments["todos"] = "\n".join(diffs)
        return tool_name, arguments
