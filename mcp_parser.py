import json
import re

from parser import JsonObj, ToolDoc


def extract_mcp_section(doc: str) -> str:
    section_name = "Connected MCP Servers"
    m = re.search(rf"^#\s+{re.escape(section_name)}\n", doc, flags=re.MULTILINE)
    if not m:
        return ""
    start = m.start()
    end_markers = (
        r"## Creating an MCP Server",
        r"\n====\n\n[A-Z][A-Z ]+[A-Z]\n",
    )
    for end_marker in end_markers:
        m2 = re.search(rf"^{end_marker}\n", doc[m.end() :], flags=re.MULTILINE)
        if m2:
            break
    end = len(doc) if not m2 else m.end() + m2.start()
    return doc[start:end]


def parse_mcp_sections(mcp_md: str) -> tuple[list[ToolDoc], dict[str, str]]:
    # split by "## <server_name> (`<uri>`)"
    chunks = re.split(
        r"^##\s+(?P<name>[^\(]+?)(?:\s+\(`(?P<uri>.+?)`\))?\n",
        mcp_md,
        flags=re.MULTILINE,
    )
    # re.split keeps the delimiters: [..., name1, uri1, desc1, name2, uri2, desc2, ...]
    tools: list[ToolDoc] = []
    remove_patterns = {}
    for i in range(1, len(chunks), 3):
        server_name = chunks[i].strip()
        server_uri = chunks[i + 1].strip()
        m = None
        start_pos = 0
        available_tools_md = ""
        while True:
            section_name = "### Available Tools"
            m = re.search(
                rf"^{re.escape(section_name)}\n",
                chunks[i + 2][start_pos:],
                flags=re.MULTILINE,
            )
            if m:
                start_pos += m.end()
                available_tools_md = chunks[i + 2][start_pos:]
            else:
                break

        end_markers = (
            r"### Resource Templates",
            r"### Direct Resources",
        )
        for end_marker in end_markers:
            m = re.search(
                rf"^{re.escape(end_marker)}\n",
                available_tools_md,
                flags=re.MULTILINE,
            )
            if m:
                available_tools_md = available_tools_md[: m.start()]
                break

        tools_chunks = re.split(
            r"^-\s+(?P<name>[^:]+):\s+(?P<desc>[\s\S]+?)\n\s+Input Schema:\n(?=\s*{)",
            available_tools_md,
            flags=re.MULTILINE,
        )
        for j in range(1, len(tools_chunks), 3):
            tool_name = tools_chunks[j].strip()
            tool_desc = tools_chunks[j + 1]
            schema = tools_chunks[j + 2]
            tools.append(
                ToolDoc(
                    name=f"use_mcp_tool.{server_name}.{tool_name}",
                    description=tool_desc,
                    parameters_markdown=schema,
                    xml_samples=[],
                )
            )
        remove_patterns[available_tools_md] = ""
    return tools, remove_patterns


def build_mcp_tool_schema(tool: ToolDoc) -> JsonObj:
    # Use JSONDecoder to read only the first valid JSON portion
    decoder = json.JSONDecoder()
    obj, _index = decoder.raw_decode(tool.parameters_markdown.strip())
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": obj,
        },
    }
