from enum import Enum, EnumMeta

from pydantic import BaseModel as _BaseModel
from pydantic.alias_generators import to_camel


class BaseModel(_BaseModel):
    model_config = {
        "str_strip_whitespace": True,
        "from_attributes": True,
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "protected_namespaces": (),
        "alias_generator": to_camel,
        "json_encoders": {
            Enum: lambda enum: enum.value if enum else None,
            EnumMeta: None,
        },
    }
