import copy
import re
from functools import cache
from typing import Annotated, Any, Callable

import yaml
from pydantic import BaseModel, Field


class ReplacementItem(BaseModel):
    name: str | None = None
    role: str
    trigger: str | None = None
    pattern: str
    replace: str | None = None
    ref: Annotated[list[str], Field(default_factory=list)]


class _SettingJson(BaseModel):
    additional_replacement: dict[str, dict[str, str]] = {}


class Setting(BaseModel):
    additional_replacement: list[ReplacementItem] = []

    def from_json_setting(json_setting: _SettingJson) -> "Setting":
        additional_replacement = []
        for role, role_replacement in json_setting.additional_replacement.items():
            additional_replacement.extend(
                ReplacementItem(role=role, pattern=search, replace=replace)
                for search, replace in role_replacement.items()
            )
        yaml_setting = Setting(additional_replacement=additional_replacement)
        return yaml_setting


@cache
def get_additional_replacement() -> list[ReplacementItem]:
    try:
        with open("setting.yaml", encoding="utf-8") as f:
            return Setting.model_validate(yaml.safe_load(f))
    except Exception:
        pass

    try:
        with open("setting.json", encoding="utf-8") as f:
            return Setting.from_json_setting(_SettingJson.model_validate_json(f.read()))
    except Exception:
        return {}


def apply_replacement(
    text: str,
    replacement_setting: Setting,
    captured_values: dict[str, dict[str, str]],
    role: str,
):
    for item in replacement_setting.additional_replacement:
        if item.trigger:
            value_map = {}
            for prev in captured_values.values():
                value_map.update(prev)
            if item.trigger not in value_map:
                continue

        if item.role != role:
            continue

        replace_map = {}
        if item.ref:
            for ref in item.ref:
                replace_map.update(
                    {k: re.escape(v) for k, v in captured_values.get(ref, {}).items()}
                )
        if item.ref and not replace_map:
            continue
        pattern = item.pattern.format_map(replace_map) if item.ref else item.pattern
        if item.replace is not None:
            replace = item.replace.format_map(replace_map) if item.ref else item.replace
            text = re.sub(pattern, replace, text)
        else:
            match = re.search(pattern, text)
            target_dict: dict = captured_values.setdefault(item.role, {})
            if match:
                target_dict.update(
                    {k: v for k, v in match.groupdict().items() if v is not None}
                )
    return text


def apply_replacement_to_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], Callable[[str], str]]:
    replacements = get_additional_replacement()
    captured_values = {}
    messages = copy.deepcopy(messages)
    for message in messages:
        role = message["role"]
        if role in captured_values:
            del captured_values[role]
        content = message["content"]

        if isinstance(content, list):
            for content_part in content:
                if text := content_part.get("text"):
                    content_part["text"] = apply_replacement(
                        text, replacements, captured_values, role
                    )
        elif isinstance(content, str):
            message["content"] = apply_replacement(
                content, replacements, captured_values, role
            )

    def apply_replacement_to_completion(completion: str) -> str:
        return apply_replacement(
            completion, replacements, captured_values, "completion"
        )

    return messages, apply_replacement_to_completion


def apply_replacement_to_prompt(prompt: str) -> tuple[str, Callable[[str], str]]:
    replacements = get_additional_replacement()
    captured_values = {}

    prompt = apply_replacement(prompt, replacements, captured_values, "prompt")

    def apply_replacement_to_completion(completion: str) -> str:
        return apply_replacement(
            completion, replacements, captured_values, "completion"
        )

    return prompt, apply_replacement_to_completion
