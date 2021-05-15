

import json
from typing import Dict, List
from common.messaging.vumos.vumos import VumosService


class VumosDataEntryType:
    host = "host"
    machine = "machine"
    vulnerability = "vulnerability"
    path = "path"


class VumosSimpleDatabase:
    def __init__(self, service: VumosService) -> None:
        self.service = service

    async def connect(self) -> None:
        # Listen for messages
        async def handler(msg):
            message = json.loads(msg.data.decode('utf-8'))

            # Base message parameters
            m_id = message["id"]
            m_type = message["message"]
            m_source = message["source"]
            m_mode = message["mode"]
            m_data = message["data"]

            if m_type == 'data.result':
                pass

        await self.service.nats.subscribe(self.service.directed_queue, cb=handler)

    async def put(self, type: VumosDataEntryType, data: Dict, id=None, filter=None):
        pass

    async def del(self, type: VumosDataEntryType, id=None, filter=None):
        pass

    async def get(self, type: VumosDataEntryType, fields: List(str), id=None, filter=None):
        pass
