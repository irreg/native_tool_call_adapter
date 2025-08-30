import copy
import json
import os
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from parser_control import (
    Parser,
    build_tool_parser,
)

app = FastAPI(title="Native Tool Call Adapter for Cline/Roo-Code")

TARGET_BASE_URL = os.getenv("TARGET_BASE_URL", "https://api.openai.com/v1")


def process_request(request: dict[str, Any]) -> tuple[dict[str, Any], Parser]:
    request = copy.deepcopy(request)
    if request["messages"] and request["messages"][0]["role"] in ["system", "user"]:
        system_prompt = request["messages"][0]["content"]
        if isinstance(system_prompt, list):
            system_prompt = "\n".join(
                [
                    str(t["text"])
                    for t in system_prompt
                    if isinstance(t, dict) and "text" in t
                ]
            )
        parser, processed_system_prompt = build_tool_parser(system_prompt)
        request["messages"][0]["content"] = processed_system_prompt
        if parser.schemas:
            request["tools"] = parser.schemas

    request["messages"] = parser.modify_xml_messages_to_tool_calls(
        request["messages"], request.get("tools", [])
    )
    return request, parser


async def handle_stream(response: httpx.Response, parser: Parser) -> AsyncIterator[str]:
    if response.is_error:
        await response.aread()
        yield f"data: {response.text}\n\n"
        yield "data: [DONE]\n\n"
        return
    buffer = ""
    last_chunk = None
    role = None
    choice_index = 0
    tool_call_index = 0
    tool_call_id = ""
    tool_name = ""
    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue

        def create_tool_call():
            nonlocal buffer, tool_name, tool_call_id
            modified_data = parser.modify_tool_call_to_xml_message(
                tool_name, buffer, tool_call_id
            )
            last_chunk["choices"][0]["delta"]["content"] = modified_data
            buffer = ""
            tool_name = ""
            tool_call_id = ""
            return f"data: {json.dumps(last_chunk, ensure_ascii=False)}\n\n"

        if line.strip() == "data: [DONE]":
            if buffer:
                yield create_tool_call()
            yield line + "\n\n"
            continue
        data = json.loads(line[6:])
        choice = (data.get("choices") or [{}])[0]
        delta = choice.get("delta", {})
        if (
            not delta
            or not delta.get("tool_calls")
            or delta.get("role", role) != role
            or choice.get("index") != choice_index
        ) and buffer:
            yield create_tool_call()
        role = delta.get("role", role)
        choice_index = choice.get("index", choice_index)
        if role == "assistant":
            tool_call = (delta.get("tool_calls") or [{}])[0]
            if tool_call.get("index") != tool_call_index and buffer:
                yield create_tool_call()
            if tool_call:
                tool_name += tool_call.get("function").get("name", "")
                buffer += tool_call.get("function").get("arguments", "")
                tool_call_id += tool_call.get("id", "")
                tool_call_index = tool_call.get("index", tool_call_index)
                last_chunk = data
        if data.get("finish_reason") and buffer:
            yield create_tool_call()
        if data.get("finish_reason") == "tool_calls":
            data["finish_reason"] = "stop"
        yield "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


@app.post("/v1/chat/completions")
async def create_completion(request: Request):
    modified_request, parser = process_request(await request.json())

    headers = dict(request.headers)
    if "host" in headers:
        del headers["host"]
    if "content-length" in headers:
        del headers["content-length"]
    stream = modified_request.get("stream")
    if stream:

        async def event_stream() -> AsyncIterator[str]:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{TARGET_BASE_URL}/chat/completions",
                    json=modified_request,
                    headers=headers,
                    params=request.query_params,
                ) as r:
                    async for iter in handle_stream(r, parser):
                        yield iter

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    else:
        async with httpx.AsyncClient(timeout=None) as client:
            r = await client.post(
                f"{TARGET_BASE_URL}/chat/completions",
                json=modified_request,
                headers=headers,
                params=request.query_params,
            )
            if r.is_error:
                return JSONResponse(status_code=r.status_code, content=r.json())
            modified_response = parser.modify_tool_calls_to_xml_messages(r.json())
            return JSONResponse(status_code=r.status_code, content=modified_response)


@app.get("/v1/models")
async def get_models(request: Request):
    headers = dict(request.headers)
    if "host" in headers:
        del headers["host"]
    if "content-length" in headers:
        del headers["content-length"]
    async with httpx.AsyncClient(timeout=None) as client:
        r = await client.get(
            f"{TARGET_BASE_URL}/models", headers=headers, params=request.query_params
        )
        return JSONResponse(status_code=r.status_code, content=r.json())
