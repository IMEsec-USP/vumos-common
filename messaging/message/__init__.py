from enum import Enum
from typing import Any, List, TypedDict


class VumosMessageSource(Enum):
    service = 'service'
    manager = 'manager'


class VumosMessageMode(Enum):
    broadcast = 'broadcast'
    targeted = 'targeted'


class VumosMessageProcessed(TypedDict):
    module: str
    hash: str
    timestamp: str


class VumosMessage(TypedDict):
    id: str
    type: str
    source: VumosMessageSource
    mode: VumosMessageMode
    processed: List[VumosMessageProcessed]
    data: Any
