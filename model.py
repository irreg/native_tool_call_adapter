from typing import Union

JsonVal = Union[str, "JsonArray", "JsonObj"]
JsonArray = list[JsonVal]
JsonObj = dict[str, JsonVal]

AnyJsonVal = Union[str, float, bool, None, "AnyJsonArray", "AnyJsonObj"]
AnyJsonArray = list[AnyJsonVal]
AnyJsonObj = dict[str, AnyJsonVal]
