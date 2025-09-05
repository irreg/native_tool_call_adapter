from typing import Union

JsonVal = Union[str, "JsonArray", "JsonObj"]
JsonArray = list[JsonVal]
JsonObj = dict[str, JsonVal]
