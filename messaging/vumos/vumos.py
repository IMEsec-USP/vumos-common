from __future__ import annotations
from array import array
import hashlib
import asyncio
from asyncio.events import AbstractEventLoop
from commons.messaging.message import VumosMessage, VumosMessageProcessed
from nats.aio.client import Client as NATS
import sched
import json
import time
from typing import Callable, List, TypedDict, Any
import socket
import uuid
from datetime import datetime
import os
from enum import Enum


broadcast_subject = "broadcast"


class VumosMessageType(Enum):
    REQUEST = "request"
    RESPONSE = "response"


class VumosServiceStatus:
    code: str
    message: str

    def __init__(self, code: str, message: str) -> None:
        self.code = code.lower()
        self.message = message


class VumosParameterValue(TypedDict):
    type: str
    default: Any


class VumosParameter(TypedDict):
    name: str
    description: str
    key: str
    value: VumosParameterValue


class VumosService:
    def __init__(self, name: str, description: str, parameters: List[VumosParameter] = [], nats_callback: Callable[[VumosService, VumosMessage], None] = None, status_expiry: float = 60) -> None:
        self.directed_queue = str(uuid.uuid4())
        self.id = os.environ.get('VUMOS_ID') or socket.gethostname()
        self.scheduler = sched.scheduler(time.time, time.sleep)
        self.running = True

        self.name = name
        self.description = description
        self.parameters = parameters
        self.status_expiry = status_expiry

        self.nats_callback = nats_callback

        self.set_status(VumosServiceStatus(
            "red", f"[ERROR] Service still has no status set"))

        # Initialize config from parameters
        config = {}

        for parameter in self.parameters:
            config[parameter["key"]] = parameter["value"]["default"]

        self.config = config

    def set_status(self, status: VumosServiceStatus):
        '''
        This function sets the current status for the service to send to managers.

        Parameters:
            status (VumosServiceStatus): The current status of this service
        '''
        self.status = status

    def get_config(self, key: str) -> Any:
        '''
        This function returns the current value of the configuration of a given key for this service.

        Parameters:
            key (str): The key of the configuration

        Returns:
            Any: The value set by the manager or default configuration
        '''
        return self.config[key]

    async def connect(self, loop: AbstractEventLoop, uri="nats://127.0.0.1:4222") -> None:
        '''
        This method connects the service to the NATS messaging service, sets up subscriptions, and sends the HELLO message.

        Parameters:
            loop (AbstractEventLoop): The asyncio event loop
        '''
        # Connection to Nats
        self.nats = NATS()
        await self.nats.connect(uri, loop=loop)

        # Listen for messages
        async def handler(msg):
            await self._message_callback(msg)

        await self.nats.subscribe(broadcast_subject, cb=handler)
        await self.nats.subscribe(self.directed_queue, cb=handler)

        # Send Hello
        await self._send_hello()

    async def loop(self) -> None:
        '''
        This method starts listening for messages and sending status updates to the backbone.
        '''
        tasks: List[asyncio.Task] = []

        # Status update loop
        async def status_update_loop():
            while self.running:
                await self._send_status()
                await asyncio.sleep(0.75 * self.status_expiry)

        tasks.append(asyncio.Task(status_update_loop()))

        # Wait for all threads
        for task in tasks:
            await task

    # Listen for message callbacks
    async def _message_callback(self, msg) -> None:
        '''
        This method handles an incoming message from the network.
        '''
        message: VumosMessage = json.loads(msg.data.decode('utf-8'))

        # Base message parameters
        m_id = message["id"]
        m_type = message["message"]
        m_source = message["source"]
        m_mode = message["mode"]
        m_processed = message["processed"]
        m_data = message["data"]

        # Skip message if is repeated
        hash = hashlib.md5(json.dumps(m_data).encode('utf-8')).hexdigest()
        for processed in m_processed:
            if processed["hash"] == hash and processed["module"] == self.id:
                return

        #print('recv:', message)

        if m_type == "hello":
            # On hello message
            #
            # broadcast: Reply directly
            # directed: Don't do anything
            #
            # always: Send current configuration to managers
            if m_mode == "broadcast":
                await self._send_hello(msg.reply)

            if m_source == "manager":
                await self._send_status(msg.reply)
                await self._send_cchanged(msg.reply)
        elif m_type == "configuration_change":
            # On change message
            #
            # broadcast: Reply directly
            # directed: Don't do anything
            #
            # always: Send current configuration to managers
            for config in m_data['configurations']:
                c_key = config['key']
                c_value = config['value']['current']

                if not c_key in self.config:
                    print(f'Ignoring unknown config {c_key}')
                    continue

                self.config[c_key] = c_value

            await self._send_cchanged()
        elif m_type == "status_update":
            # On status update, do nothing
            pass
        elif self.nats_callback:
            self.nats_callback(self, message)

    ###########################
    # Message sending methods #
    ###########################
    async def send_message(self, message: str, data: dict, to: str = None, type: VumosMessageType = VumosMessageType.REQUEST, processed: List[VumosMessageProcessed] = []) -> None:
        new_processed = list(processed)

        new_hash = hashlib.md5(json.dumps(data).encode('utf-8')).hexdigest()
        new_ts = datetime.utcnow().isoformat()

        found = False
        for module in new_processed:
            if module["module"] == self.id:
                module["hash"] = new_hash
                module["timestamp"] = new_ts
                found = True
                break

        if not found:
            new_processed.append({
                "module": self.id,
                "hash": new_hash,
                "timestamp": new_ts
            })

        message: VumosMessage = {
            "id": self.id,
            "message": message,
            "source": "service",
            "type": type.value,
            "mode": "broadcast" if to is None else "targeted",
            "processed": new_processed,
            "data": data
        }

        subject = to or broadcast_subject
        payload = json.dumps(message).encode('utf-8')

        await self.nats.publish(subject, payload=payload)

    async def send_target_data(self, ip_address: str, domains: array(str) = [], extra: Any = None, to: str = None) -> None:
        await self.send_message("data_target", {
            "ip_address": ip_address,
            "domains": domains,
            "extra": extra
        }, to=to)

    async def send_service_data(self, ip_address: str, port: int, name: str = None, protocol: str = None, version: str = None, extra: Any = None, to: str = None) -> None:
        data = {
            "ip_address": ip_address,
            "port": port,
        }

        if name:
            data['name'] = name
        if protocol:
            data['protocol'] = protocol
        if version:
            data['version'] = version
        if extra:
            data['extra'] = extra

        await self.send_message("data_service", data, to=to)

    async def send_target(self, to: str = None) -> None:
        await self.send_message("", {
            "name": self.name,
            "description": self.description,
            "status_expiry": self.status_expiry
        }, to=to)

    async def _send_hello(self, to: str = None) -> None:
        await self.send_message("hello", {
            "name": self.name,
            "description": self.description,
            "status_expiry": self.status_expiry
        }, to=to)

    async def _send_cchanged(self, to: str = None) -> None:
        def apply_current_value(p: VumosParameter):
            data = dict(p)
            data["value"]["current"] = self.get_config(p["key"])
            return data

        await self.send_message("configuration_changed", {
            "configurations": list(map(apply_current_value, self.parameters))
        }, to=to)

    async def _send_status(self, to: str = None) -> None:
        print('Sent status_update')
        await self.send_message("status_update", {
            "code": self.status.code,
            "message": self.status.message
        }, to=to)
