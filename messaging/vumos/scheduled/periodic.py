
import asyncio
from typing import Any, Callable, List
from ..vumos import VumosService, VumosServiceStatus, VumosParameter


class ScheduledVumosService(VumosService):
    def __init__(self, name: str, description: str, conditions: Callable[[VumosService], Any], task: Callable[[VumosService, Any], None], parameters: List[VumosParameter] = [], nats_callback: Callable = None, pool_interval=3600) -> None:
        super().__init__(name, description, parameters=parameters, nats_callback=nats_callback)

        self.conditions = conditions
        self.task = task
        self.pool_interval = pool_interval

        self.set_status(VumosServiceStatus(
            "idle", f"[IDLE] Service <{self.name}> is idle"))

    async def loop(self) -> None:
        async def run_scheduled():
            while self.running:
                condition = self.conditions(self)
                if not (condition is None):
                    self.set_status(VumosServiceStatus(
                        "running", f"[RUNNING] <{self.name}> service is running"))
                    try:
                        await self.task(self, condition)
                    except Exception as e:
                        print(e)

                    self.set_status(VumosServiceStatus(
                        "idle", f"[IDLE] Service <{self.name}> is idle"))

                # Check conditions every hour
                await asyncio.sleep(self.pool_interval)

        task = asyncio.Task(run_scheduled())

        await super().loop()

        await task
