# NativeToolCallAdapter
[日本語](README.ja-JP.md) | [English](README.md)


## Overview

- BEFORE (without this app)
```mermaid
flowchart LR
    A[cline, Roo-Code] --> |XML tool defs|C[LLM]
    C -.-> |XML tool calls
    <u>with a potentially incorrect signature</u>|A
```

- AFTER (with this app)
```mermaid
flowchart LR
    A[cline, Roo-Code] --> |XML tool defs|B[**This app**]
    B --> |native tool defs|C[LLM]
    C -.-> |native tool calls
    <u>with an accurate signature</u>|B
    B -.-> |XML tool calls
    <u>with an accurate signature</u>|A
```

With relatively small models, [cline](https://github.com/cline/cline) and [Roo-Code](https://github.com/RooCodeInc/Roo-Code) tool calls may not be handled properly.
This application parses XML-formatted tool calls from Cline and Roo-Code and converts them into a format compliant with OpenAI API's tool_calls.

Significant improvements in performance have been confirmed with [gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) and other models.
Even with large models, the reduced load of considering tool calls should lead to more accurate behavior.


## Notes
This is an experimental application.
Parsing depends on the content of Cline/Roo-Code prompts, so it may stop working if the prompt specifications change in the future.


## Execution Steps

1. `git clone https://github.com/irreg/native_tool_call_adapter.git
2. `uv sync`
3. `set TARGET_BASE_URL=actual LLM operating URL`  
   Example:
   - TARGET_BASE_URL: http://localhost:8080/v1
4. `uv run main.py`
5. The server will start on port 8000, so configure Cline and Roo-Code.  
   Example:
   - API Provider: OpenAI Compatible
   - Base URL: http://localhost:8000/v1
   - API Key: Setting the API key will automatically use it when communicating with TARGET_BASE_URL.


## Settings
The following settings can be configured as environment variables
- TARGET_BASE_URL: (default: https://api.openai.com/v1) URL hosting the LLM
- TOOL_CALL_ADAPTER_HOST: (default: 0.0.0.0) URL hosting this application
- TOOL_CALL_ADAPTER_PORT: (default: 8000) Port hosting this application
- MESSAGE_DUMP_PATH: (default: null) Dumps the message actually sent to the LLM to the specified path, allowing you to verify the converted content  

### setting.yaml
You can define additional replacement rules using regular expressions in setting.yaml.

#### Configuration File Structure
```yaml
additional_replacement:
  - name: Replacement rule name
    role: Target role
    pattern: Regular expression pattern
    replace: Replacement string
    trigger: Condition key to enable replacement
    ref: List of role names to reference
```
Description of Each Field
- name: (optional) Name of this replacement rule
- role: Role of the message this rule applies to
    - system: System prompt
    - user: User-entered message or response sent by cline/Roo-Code to the LLM (e.g., when a tool call fails)
    - tool: Past tool call result
    - assistant: Past LLM response outside of tool calls
    - completion: Newly generated response from the LLM (data returned to cline/Roo-Code, including tool calls)
pattern: Regular expression pattern to search for.
replace: (optional) Replacement string.
    If omitted, named capture groups within the pattern (e.g., `(?P<key>...)`) can be captured and used in subsequent pattern/replace processing.
ref: (optional) Uses a string captured from the message processed immediately before the specified role in pattern/replace. Replaces strings in pattern/replace matching the format `{key}` with the captured string.
trigger: (optional) Only performs replacement if the string captured from the immediately preceding pattern contains the named capture group key.

Example 1: Replace "XML tags" in cline responses to LLM with "tool calling"
```yaml
additional_replacement:
  - role: user
    pattern: XML tags
    replace: tool calling
```

Example 2: Extract user_id from user messages and use it to replace values in LLM output
```yaml
additional_replacement:
  - role: user
    pattern: ID:(?P<user_id>\d+)
  - role: completion
    trigger: user_id
    ref: [user]
    pattern: Hello
    replace: Hello #{user_id}!
```