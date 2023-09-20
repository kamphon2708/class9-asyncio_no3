import time
import random
import json
import asyncio
import aiomqtt
from enum import Enum
import sys
import time
student_id = "6310301011"


class MachineStatus(Enum):
    pressure = round(random.uniform(2000, 3000), 2)
    temperature = round(random.uniform(25.0, 40.0), 2)


class MachineMaintStatus(Enum):
    filter = random.choice(["clear", "clogged"])
    noise = random.choice(["quiet", "noisy"])


class WashingMachine:
    def __init__(self, serial):
        self.SERIAL = serial
        self.Task = None

        self.MACHINE_STATUS = 'OFF'
        """START | READY | FILLWATER | HEATWATER | WASH | RINSE | SPIN | FAULT"""

        self.FAULT = None
        """TIMEOUT | OUTOFBALANCE | FAULTCLEARED | FAULTCLEARED | None"""

        self.OPERATION = None
        """DOORCLOSE | WATERFULLLEVEL | TEMPERATUREREACHED | COMPLETED"""

        self.OPERATION_value = None
        """" FULL """

    async def Running(self):
        print(
            f"{time.ctime()} - [{self.SERIAL}-{self.MACHINE_STATUS}] START")
        await asyncio.sleep(3600)

    def nextState(self):
        if self.MACHINE_STATUS == 'WASH':
            self.MACHINE_STATUS = 'RINSE'
        elif self.MACHINE_STATUS == 'RINSE':
            self.MACHINE_STATUS = 'SPIN'
        elif self.MACHINE_STATUS == 'SPIN':
            self.MACHINE_STATUS = 'OFF'

    async def Running_Task(self, client: aiomqtt.Client, invert: bool):
        self.Task = asyncio.create_task(self.Running())
        wait_coro = asyncio.wait_for(self.Task, timeout=20)
        try:
            await wait_coro
        except asyncio.TimeoutError:
            print(
                f"{time.ctime()} - [{self.SERIAL}-{self.MACHINE_STATUS}] Timeout")
            if not invert:
                self.MACHINE_STATUS = 'FAULT'
                self.FAULT = 'TIMEOUT'
                await publish_message(self, client, "hw", "get", "STATUS", self.MACHINE_STATUS)
                await publish_message(self, client, "hw", "get", "FAULT", self.FAULT)
            else:
                self.nextState()

        except asyncio.CancelledError:
            print(
                f"{time.ctime()} - [{self.SERIAL}] Cancelled")

    async def Cancel_Task(self):
        self.Task.cancel()


async def publish_message(w, client, app, action, name, value):
    payload = {
        "action": "get",
        "project": student_id,
        "model": "model-01",
        "serial": w.SERIAL,
        "name": name,
        "value": value
    }
    print(
        f"{time.ctime()} - PUBLISH - [{w.SERIAL}] - {payload['name']} > {payload['value']}")
    await client.publish(f"v1cdti/{app}/{action}/{student_id}/model-01/{w.SERIAL}", payload=json.dumps(payload))


async def CoroWashingMachine(w: WashingMachine, client: aiomqtt.Client, event: asyncio.Event):
    while True:
        # wait_next = round(10*random.random(), 2)
        # print(
        #     f"{time.ctime()} - [{w.SERIAL}-{w.MACHINE_STATUS}] Waiting to start... {wait_next} seconds.")
        # await asyncio.sleep(wait_next)

        if w.MACHINE_STATUS == 'OFF':
            await publish_message(w, client, "app", "get", "STATUS", w.MACHINE_STATUS)

            print(
                f"{time.ctime()} - [{w.SERIAL}-{w.MACHINE_STATUS}] Waiting to start...")
            await event.wait()
            event.clear()

        if w.MACHINE_STATUS == 'READY':
            await publish_message(w, client, "app", "get", "STATUS", "READY")
            await publish_message(w, client, 'app', 'get', 'LID', 'CLOSE')
            w.MACHINE_STATUS = 'FILLWATER'
            await publish_message(w, client, "app", "get", "STATUS", "FILLWATER")
            await w.Running_Task(client, invert=False)

        if w.MACHINE_STATUS == 'HEATWATER':
            await publish_message(w, client, "app", "get", "STATUS", "HEATWATER")
            await w.Running_Task(client, invert=False)

        if w.MACHINE_STATUS in ['WASH', 'RINSE', 'SPIN']:
            await publish_message(w, client, "app", "get", "STATUS", w.MACHINE_STATUS)
            await w.Running_Task(client, invert=True)

        if w.MACHINE_STATUS == 'FAULT':
            print(
                f"{time.ctime()} - [{w.SERIAL}-{w.MACHINE_STATUS}-{w.FAULT}] Waiting to clear fault...")
            await event.wait()
            event.clear()

            # fill water untill full level detected within 10 seconds if not full then timeout

            # heat water until temperature reach 30 celcius within 10 seconds if not reach 30 celcius then timeout

            # wash 10 seconds, if out of balance detected then fault

            # rinse 10 seconds, if motor failure detect then fault

            # spin 10 seconds, if motor failure detect then fault

            # ready state set

            # When washing is in FAULT state, wait until get FAULTCLEARED


async def listen(w: WashingMachine, client: aiomqtt.Client, event: asyncio.Event):
    async with client.messages() as messages:
        await client.subscribe(f"v1cdti/hw/set/{student_id}/model-01/{w.SERIAL}")
        await client.subscribe(f"v1cdti/hw/get/{student_id}/model-01/")
        async for message in messages:
            m_decode = json.loads(message.payload)
            if message.topic.matches(f"v1cdti/hw/set/{student_id}/model-01/{w.SERIAL}"):
                # set washing machine status
                print(
                    f"{time.ctime()} - MQTT - [{m_decode['serial']}]:{m_decode['name']} => {m_decode['value']}")

                match m_decode['name']:
                    case "STATUS":
                        w.MACHINE_STATUS = m_decode['value']
                        if m_decode['value'] == 'READY':
                            if not event.is_set():
                                event.set()
                    case "FAULT":
                        if m_decode['value'] == "FAULTCLEARED":
                            w.MACHINE_STATUS = 'OFF'
                            if not event.is_set():
                                event.set()
                        elif m_decode['value'] == "OUTOFBALANCE" and w.MACHINE_STATUS == 'WASH':
                            w.MACHINE_STATUS = "FAULT"
                            w.FAULT = 'OUTOFBALANCE'
                        elif m_decode['value'] == "MOTORFAILURE" and w.MACHINE_STATUS in ['RINSE', 'SPIN']:
                            w.MACHINE_STATUS = "FAULT"
                            w.FAULT = 'MOTORFAILURE'
                    case "WATERFULLLEVEL":
                        if w.MACHINE_STATUS == 'FILLWATER' and m_decode['value'] == "FULL":
                            await w.Cancel_Task()
                            w.MACHINE_STATUS = "HEATWATER"
                    case "TEMPERATUREREACHED":
                        if w.MACHINE_STATUS == 'HEATWATER' and m_decode['value'] == "REACHED":
                            await w.Cancel_Task()
                            w.MACHINE_STATUS = "WASH"
            elif message.topic.matches(f"v1cdti/hw/get/{student_id}/model-01/"):
                await publish_message(w, client, "app", "monitor", "STATUS", w.MACHINE_STATUS)


async def main():
    n = 5
    W = [WashingMachine(serial=f'SN-00{i+1}') for i in range(n)]
    Events = [asyncio.Event() for i in range(n)]
    async with aiomqtt.Client("broker.hivemq.com") as client:
        listenTask = []
        CoroWashingMachineTask = []
        for w, event in zip(W, Events):
            listenTask.append(listen(w, client, event))
            CoroWashingMachineTask.append(CoroWashingMachine(w, client, event))
        await asyncio.gather(*listenTask, *CoroWashingMachineTask)

# Change to the "Selector" event loop if platform is Windows
if sys.platform.lower() == "win32" or os.name.lower() == "nt":
    from asyncio import set_event_loop_policy, WindowsSelectorEventLoopPolicy
    set_event_loop_policy(WindowsSelectorEventLoopPolicy())
# Run your async application as usual
asyncio.run(main())


# Wed Sep 13 14:31:56 2023 - [SN-001-OFF] Waiting to start...
# Wed Sep 13 14:31:56 2023 - [SN-002-OFF] Waiting to start...
# Wed Sep 13 14:31:56 2023 - [SN-003-OFF] Waiting to start...
# Wed Sep 13 14:31:56 2023 - [SN-004-OFF] Waiting to start...
# Wed Sep 13 14:31:56 2023 - [SN-005-OFF] Waiting to start...
# Wed Sep 13 14:31:56 2023 - [SN-006-OFF] Waiting to start...
# Wed Sep 13 14:31:56 2023 - [SN-007-OFF] Waiting to start...
# Wed Sep 13 14:31:56 2023 - [SN-008-OFF] Waiting to start...
# Wed Sep 13 14:31:56 2023 - [SN-009-OFF] Waiting to start...
# Wed Sep 13 14:31:56 2023 - [SN-0010-OFF] Waiting to start...
# Wed Sep 13 14:32:08 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:32:08 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:32:08 2023 - [SN-002] STATUS:OFF
# Wed Sep 13 14:32:08 2023 - PUBLISH - [SN-002] - STATUS > OFF
# Wed Sep 13 14:32:08 2023 - [SN-003] STATUS:OFF
# Wed Sep 13 14:32:08 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 13 14:32:08 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:32:08 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:32:08 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:32:08 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:32:08 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:32:08 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:32:08 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:32:08 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:32:08 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:32:08 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:32:08 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:32:08 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:32:08 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:32:08 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:32:41 2023 - MQTT - [sn-02]:STATUS => READY
# Wed Sep 13 14:32:41 2023 - [SN-002] STATUS:READY
# Wed Sep 13 14:32:41 2023 - PUBLISH - [SN-002] - STATUS > READY
# Wed Sep 13 14:32:41 2023 - [SN-002] LID:CLOSE
# Wed Sep 13 14:32:41 2023 - PUBLISH - [SN-002] - LID > CLOSE
# Wed Sep 13 14:32:41 2023 - [SN-002] STATUS:FILLWATER
# Wed Sep 13 14:32:41 2023 - PUBLISH - [SN-002] - STATUS > FILLWATER
# Wed Sep 13 14:32:41 2023 - [SN-002-FILLWATER] START
# Wed Sep 13 14:32:51 2023 - [SN-002-FILLWATER] Timeout
# Wed Sep 13 14:32:51 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:32:51 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:32:51 2023 - [SN-002] FAULT:TIMEOUT
# Wed Sep 13 14:32:51 2023 - PUBLISH - [SN-002] - FAULT > TIMEOUT
# Wed Sep 13 14:32:51 2023 - [SN-002-FAULT-TIMEOUT] Waiting to clear fault...
# Wed Sep 13 14:34:34 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:34:34 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:34:34 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:34:34 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:34:34 2023 - [SN-003] STATUS:OFF
# Wed Sep 13 14:34:34 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 13 14:34:34 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:34:34 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:34:34 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:34:34 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:34:34 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:34:34 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:34:34 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:34:34 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:34:34 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:34:34 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:34:34 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:34:34 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:34:34 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:34:34 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:36:20 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:36:20 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:36:20 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:36:20 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:36:20 2023 - [SN-003] STATUS:OFF
# Wed Sep 13 14:36:20 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 13 14:36:20 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:36:20 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:36:20 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:36:20 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:36:20 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:36:20 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:36:20 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:36:20 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:36:20 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:36:20 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:36:20 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:36:20 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:36:20 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:36:20 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:37:01 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:37:01 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:37:01 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:37:01 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:37:01 2023 - [SN-003] STATUS:OFF
# Wed Sep 13 14:37:01 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 13 14:37:01 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:37:01 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:37:01 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:37:01 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:37:01 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:37:01 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:37:01 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:37:01 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:37:01 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:37:01 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:37:01 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:37:01 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:37:01 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:37:01 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:37:44 2023 - MQTT - [sn-03]:STATUS => READY
# Wed Sep 13 14:37:44 2023 - [SN-003] STATUS:READY
# Wed Sep 13 14:37:44 2023 - PUBLISH - [SN-003] - STATUS > READY
# Wed Sep 13 14:37:44 2023 - [SN-003] LID:CLOSE
# Wed Sep 13 14:37:44 2023 - PUBLISH - [SN-003] - LID > CLOSE
# Wed Sep 13 14:37:44 2023 - [SN-003] STATUS:FILLWATER
# Wed Sep 13 14:37:44 2023 - PUBLISH - [SN-003] - STATUS > FILLWATER
# Wed Sep 13 14:37:44 2023 - [SN-003-FILLWATER] START
# Wed Sep 13 14:37:48 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:37:48 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:37:48 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:37:48 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:37:48 2023 - [SN-003] STATUS:FILLWATER
# Wed Sep 13 14:37:48 2023 - PUBLISH - [SN-003] - STATUS > FILLWATER
# Wed Sep 13 14:37:48 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:37:48 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:37:48 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:37:48 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:37:48 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:37:48 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:37:48 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:37:48 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:37:48 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:37:48 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:37:48 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:37:48 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:37:48 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:37:48 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:37:54 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:37:54 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:37:54 2023 - [SN-003] STATUS:FILLWATER
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-003] - STATUS > FILLWATER
# Wed Sep 13 14:37:54 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:37:54 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:37:54 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:37:54 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:37:54 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:37:54 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:37:54 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:37:54 2023 - [SN-003-FILLWATER] Timeout
# Wed Sep 13 14:37:54 2023 - [SN-003] STATUS:FAULT
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-003] - STATUS > FAULT
# Wed Sep 13 14:37:54 2023 - [SN-003] FAULT:TIMEOUT
# Wed Sep 13 14:37:54 2023 - PUBLISH - [SN-003] - FAULT > TIMEOUT
# Wed Sep 13 14:37:54 2023 - [SN-003-FAULT-TIMEOUT] Waiting to clear fault...
# Wed Sep 13 14:38:01 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:38:01 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:38:01 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:38:01 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:38:01 2023 - [SN-003] STATUS:FAULT
# Wed Sep 13 14:38:01 2023 - PUBLISH - [SN-003] - STATUS > FAULT
# Wed Sep 13 14:38:01 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:38:01 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:38:01 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:38:01 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:38:01 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:38:01 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:38:01 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:38:01 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:38:01 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:38:01 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:38:01 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:38:01 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:38:01 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:38:01 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:49:45 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:49:45 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:49:45 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:49:45 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:49:45 2023 - [SN-003] STATUS:FAULT
# Wed Sep 13 14:49:45 2023 - PUBLISH - [SN-003] - STATUS > FAULT
# Wed Sep 13 14:49:45 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:49:45 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:49:45 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:49:45 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:49:45 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:49:45 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:49:45 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:49:45 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:49:45 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:49:45 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:49:45 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:49:45 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:49:45 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:49:45 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:50:51 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:50:51 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:50:51 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:50:51 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:50:51 2023 - [SN-003] STATUS:FAULT
# Wed Sep 13 14:50:51 2023 - PUBLISH - [SN-003] - STATUS > FAULT
# Wed Sep 13 14:50:51 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:50:51 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:50:51 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:50:51 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:50:51 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:50:51 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:50:51 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:50:51 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:50:51 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:50:51 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:50:51 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:50:51 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:50:51 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:50:51 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:51:10 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:51:10 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:51:10 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:51:10 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:51:10 2023 - [SN-003] STATUS:FAULT
# Wed Sep 13 14:51:10 2023 - PUBLISH - [SN-003] - STATUS > FAULT
# Wed Sep 13 14:51:10 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:51:10 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:51:10 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:51:10 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:51:10 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:51:10 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:51:10 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:51:10 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:51:10 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:51:10 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:51:10 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:51:10 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:51:10 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:51:10 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:51:14 2023 - [SN-001] STATUS:OFF
# Wed Sep 13 14:51:14 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 13 14:51:14 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:51:14 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:51:14 2023 - [SN-003] STATUS:FAULT
# Wed Sep 13 14:51:14 2023 - PUBLISH - [SN-003] - STATUS > FAULT
# Wed Sep 13 14:51:14 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:51:14 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:51:14 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:51:14 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:51:14 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:51:14 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:51:14 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:51:14 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:51:14 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:51:14 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:51:14 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:51:14 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:51:14 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:51:14 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:51:19 2023 - MQTT - [sn-01]:STATUS => READY
# Wed Sep 13 14:51:19 2023 - [SN-001] STATUS:READY
# Wed Sep 13 14:51:19 2023 - PUBLISH - [SN-001] - STATUS > READY
# Wed Sep 13 14:51:19 2023 - [SN-001] LID:CLOSE
# Wed Sep 13 14:51:19 2023 - PUBLISH - [SN-001] - LID > CLOSE
# Wed Sep 13 14:51:19 2023 - [SN-001] STATUS:FILLWATER
# Wed Sep 13 14:51:19 2023 - PUBLISH - [SN-001] - STATUS > FILLWATER
# Wed Sep 13 14:51:19 2023 - [SN-001-FILLWATER] START
# Wed Sep 13 14:51:21 2023 - [SN-001] STATUS:FILLWATER
# Wed Sep 13 14:51:21 2023 - PUBLISH - [SN-001] - STATUS > FILLWATER
# Wed Sep 13 14:51:21 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:51:21 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:51:21 2023 - [SN-003] STATUS:FAULT
# Wed Sep 13 14:51:21 2023 - PUBLISH - [SN-003] - STATUS > FAULT
# Wed Sep 13 14:51:21 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:51:21 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:51:21 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:51:21 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:51:21 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:51:21 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:51:21 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:51:21 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:51:21 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:51:21 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:51:21 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:51:21 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:51:21 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:51:21 2023 - PUBLISH - [SN-0010] - STATUS > OFF
# Wed Sep 13 14:51:29 2023 - [SN-001-FILLWATER] Timeout
# Wed Sep 13 14:51:29 2023 - [SN-001] STATUS:FAULT
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-001] - STATUS > FAULT
# Wed Sep 13 14:51:29 2023 - [SN-001] FAULT:TIMEOUT
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-001] - FAULT > TIMEOUT
# Wed Sep 13 14:51:29 2023 - [SN-001-FAULT-TIMEOUT] Waiting to clear fault...
# Wed Sep 13 14:51:29 2023 - [SN-001] STATUS:FAULT
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-001] - STATUS > FAULT
# Wed Sep 13 14:51:29 2023 - [SN-002] STATUS:FAULT
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-002] - STATUS > FAULT
# Wed Sep 13 14:51:29 2023 - [SN-003] STATUS:FAULT
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-003] - STATUS > FAULT
# Wed Sep 13 14:51:29 2023 - [SN-004] STATUS:OFF
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 13 14:51:29 2023 - [SN-005] STATUS:OFF
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 13 14:51:29 2023 - [SN-006] STATUS:OFF
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-006] - STATUS > OFF
# Wed Sep 13 14:51:29 2023 - [SN-007] STATUS:OFF
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-007] - STATUS > OFF
# Wed Sep 13 14:51:29 2023 - [SN-008] STATUS:OFF
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-008] - STATUS > OFF
# Wed Sep 13 14:51:29 2023 - [SN-009] STATUS:OFF
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-009] - STATUS > OFF
# Wed Sep 13 14:51:29 2023 - [SN-0010] STATUS:OFF
# Wed Sep 13 14:51:29 2023 - PUBLISH - [SN-0010] - STATUS > OFF
