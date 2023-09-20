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

# Wed Sep 20 14:33:00 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 20 14:33:00 2023 - PUBLISH - [SN-002] - STATUS > OFF
# Wed Sep 20 14:33:00 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 20 14:33:00 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 20 14:33:00 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 20 14:33:00 2023 - [SN-001-OFF] Waiting to start...
# Wed Sep 20 14:33:00 2023 - [SN-002-OFF] Waiting to start...
# Wed Sep 20 14:33:00 2023 - [SN-003-OFF] Waiting to start...
# Wed Sep 20 14:33:00 2023 - [SN-004-OFF] Waiting to start...
# Wed Sep 20 14:33:00 2023 - [SN-005-OFF] Waiting to start...
# Wed Sep 20 14:33:01 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 20 14:33:01 2023 - PUBLISH - [SN-002] - STATUS > OFF
# Wed Sep 20 14:33:01 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 20 14:33:01 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 20 14:33:01 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 20 14:33:03 2023 - MQTT - [SN-001]:STATUS => READY
# Wed Sep 20 14:33:03 2023 - PUBLISH - [SN-001] - STATUS > READY
# Wed Sep 20 14:33:03 2023 - PUBLISH - [SN-001] - LID > CLOSE
# Wed Sep 20 14:33:03 2023 - PUBLISH - [SN-001] - STATUS > FILLWATER
# Wed Sep 20 14:33:03 2023 - [SN-001-FILLWATER] START
# Wed Sep 20 14:33:05 2023 - MQTT - [SN-002]:STATUS => READY
# Wed Sep 20 14:33:05 2023 - PUBLISH - [SN-002] - STATUS > READY
# Wed Sep 20 14:33:05 2023 - PUBLISH - [SN-002] - LID > CLOSE
# Wed Sep 20 14:33:05 2023 - PUBLISH - [SN-002] - STATUS > FILLWATER
# Wed Sep 20 14:33:05 2023 - [SN-002-FILLWATER] START
# Wed Sep 20 14:33:07 2023 - MQTT - [SN-003]:STATUS => READY
# Wed Sep 20 14:33:07 2023 - PUBLISH - [SN-003] - STATUS > READY
# Wed Sep 20 14:33:07 2023 - PUBLISH - [SN-003] - LID > CLOSE
# Wed Sep 20 14:33:07 2023 - PUBLISH - [SN-003] - STATUS > FILLWATER
# Wed Sep 20 14:33:07 2023 - [SN-003-FILLWATER] START
# Wed Sep 20 14:33:09 2023 - MQTT - [SN-004]:STATUS => READY
# Wed Sep 20 14:33:09 2023 - PUBLISH - [SN-004] - STATUS > READY
# Wed Sep 20 14:33:09 2023 - PUBLISH - [SN-004] - LID > CLOSE
# Wed Sep 20 14:33:09 2023 - PUBLISH - [SN-004] - STATUS > FILLWATER
# Wed Sep 20 14:33:09 2023 - [SN-004-FILLWATER] START
# Wed Sep 20 14:33:11 2023 - MQTT - [SN-005]:STATUS => READY
# Wed Sep 20 14:33:11 2023 - PUBLISH - [SN-005] - STATUS > READY
# Wed Sep 20 14:33:11 2023 - PUBLISH - [SN-005] - LID > CLOSE
# Wed Sep 20 14:33:11 2023 - PUBLISH - [SN-005] - STATUS > FILLWATER
# Wed Sep 20 14:33:11 2023 - [SN-005-FILLWATER] START
# Wed Sep 20 14:33:11 2023 - PUBLISH - [SN-001] - STATUS > FILLWATER
# Wed Sep 20 14:33:11 2023 - PUBLISH - [SN-002] - STATUS > FILLWATER
# Wed Sep 20 14:33:11 2023 - PUBLISH - [SN-003] - STATUS > FILLWATER
# Wed Sep 20 14:33:11 2023 - PUBLISH - [SN-004] - STATUS > FILLWATER
# Wed Sep 20 14:33:11 2023 - PUBLISH - [SN-005] - STATUS > FILLWATER
# Wed Sep 20 14:33:13 2023 - MQTT - [SN-001]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:33:13 2023 - [SN-001] Cancelled
# Wed Sep 20 14:33:13 2023 - PUBLISH - [SN-001] - STATUS > HEATWATER
# Wed Sep 20 14:33:13 2023 - [SN-001-HEATWATER] START
# Wed Sep 20 14:33:15 2023 - MQTT - [SN-002]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:33:15 2023 - [SN-002] Cancelled
# Wed Sep 20 14:33:15 2023 - PUBLISH - [SN-002] - STATUS > HEATWATER
# Wed Sep 20 14:33:15 2023 - [SN-002-HEATWATER] START
# Wed Sep 20 14:33:17 2023 - MQTT - [SN-003]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:33:17 2023 - [SN-003] Cancelled
# Wed Sep 20 14:33:17 2023 - PUBLISH - [SN-003] - STATUS > HEATWATER
# Wed Sep 20 14:33:17 2023 - [SN-003-HEATWATER] START
# Wed Sep 20 14:33:19 2023 - MQTT - [SN-004]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:33:19 2023 - [SN-004] Cancelled
# Wed Sep 20 14:33:19 2023 - PUBLISH - [SN-004] - STATUS > HEATWATER
# Wed Sep 20 14:33:19 2023 - [SN-004-HEATWATER] START
# Wed Sep 20 14:33:21 2023 - MQTT - [SN-005]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:33:21 2023 - [SN-005] Cancelled
# Wed Sep 20 14:33:21 2023 - PUBLISH - [SN-005] - STATUS > HEATWATER
# Wed Sep 20 14:33:21 2023 - [SN-005-HEATWATER] START
# Wed Sep 20 14:33:21 2023 - PUBLISH - [SN-001] - STATUS > HEATWATER
# Wed Sep 20 14:33:21 2023 - PUBLISH - [SN-002] - STATUS > HEATWATER
# Wed Sep 20 14:33:21 2023 - PUBLISH - [SN-003] - STATUS > HEATWATER
# Wed Sep 20 14:33:21 2023 - PUBLISH - [SN-004] - STATUS > HEATWATER
# Wed Sep 20 14:33:21 2023 - PUBLISH - [SN-005] - STATUS > HEATWATER
# Wed Sep 20 14:33:23 2023 - MQTT - [SN-001]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:33:23 2023 - [SN-001] Cancelled
# Wed Sep 20 14:33:23 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:33:23 2023 - [SN-001-WASH] START
# Wed Sep 20 14:33:25 2023 - MQTT - [SN-002]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:33:25 2023 - [SN-002] Cancelled
# Wed Sep 20 14:33:25 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:33:25 2023 - [SN-002-WASH] START
# Wed Sep 20 14:33:27 2023 - MQTT - [SN-003]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:33:27 2023 - [SN-003] Cancelled
# Wed Sep 20 14:33:27 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:33:27 2023 - [SN-003-WASH] START
# Wed Sep 20 14:33:29 2023 - MQTT - [SN-004]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:33:29 2023 - [SN-004] Cancelled
# Wed Sep 20 14:33:29 2023 - PUBLISH - [SN-004] - STATUS > WASH
# Wed Sep 20 14:33:29 2023 - [SN-004-WASH] START
# Wed Sep 20 14:33:31 2023 - MQTT - [SN-005]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:33:31 2023 - [SN-005] Cancelled
# Wed Sep 20 14:33:31 2023 - PUBLISH - [SN-005] - STATUS > WASH
# Wed Sep 20 14:33:31 2023 - [SN-005-WASH] START
# Wed Sep 20 14:33:31 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:33:31 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:33:31 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:33:31 2023 - PUBLISH - [SN-004] - STATUS > WASH
# Wed Sep 20 14:33:31 2023 - PUBLISH - [SN-005] - STATUS > WASH
# Wed Sep 20 14:33:41 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:33:41 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:33:41 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:33:41 2023 - PUBLISH - [SN-004] - STATUS > WASH
# Wed Sep 20 14:33:41 2023 - PUBLISH - [SN-005] - STATUS > WASH
# Wed Sep 20 14:33:43 2023 - [SN-001-WASH] Timeout
# Wed Sep 20 14:33:43 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:33:43 2023 - [SN-001-RINSE] START
# Wed Sep 20 14:33:45 2023 - [SN-002-WASH] Timeout
# Wed Sep 20 14:33:45 2023 - PUBLISH - [SN-002] - STATUS > RINSE
# Wed Sep 20 14:33:45 2023 - [SN-002-RINSE] START
# Wed Sep 20 14:33:47 2023 - [SN-003-WASH] Timeout
# Wed Sep 20 14:33:47 2023 - PUBLISH - [SN-003] - STATUS > RINSE
# Wed Sep 20 14:33:47 2023 - [SN-003-RINSE] START
# Wed Sep 20 14:33:49 2023 - [SN-004-WASH] Timeout
# Wed Sep 20 14:33:49 2023 - PUBLISH - [SN-004] - STATUS > RINSE
# Wed Sep 20 14:33:49 2023 - [SN-004-RINSE] START
# Wed Sep 20 14:33:51 2023 - [SN-005-WASH] Timeout
# Wed Sep 20 14:33:51 2023 - PUBLISH - [SN-005] - STATUS > RINSE
# Wed Sep 20 14:33:51 2023 - [SN-005-RINSE] START
# Wed Sep 20 14:33:52 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:33:52 2023 - PUBLISH - [SN-002] - STATUS > RINSE
# Wed Sep 20 14:33:52 2023 - PUBLISH - [SN-003] - STATUS > RINSE
# Wed Sep 20 14:33:52 2023 - PUBLISH - [SN-004] - STATUS > RINSE
# Wed Sep 20 14:33:52 2023 - PUBLISH - [SN-005] - STATUS > RINSE
# Wed Sep 20 14:34:01 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:34:01 2023 - PUBLISH - [SN-002] - STATUS > RINSE
# Wed Sep 20 14:34:01 2023 - PUBLISH - [SN-003] - STATUS > RINSE
# Wed Sep 20 14:34:01 2023 - PUBLISH - [SN-004] - STATUS > RINSE
# Wed Sep 20 14:34:01 2023 - PUBLISH - [SN-005] - STATUS > RINSE
# Wed Sep 20 14:34:03 2023 - [SN-001-RINSE] Timeout
# Wed Sep 20 14:34:03 2023 - PUBLISH - [SN-001] - STATUS > SPIN
# Wed Sep 20 14:34:03 2023 - [SN-001-SPIN] START
# Wed Sep 20 14:34:05 2023 - [SN-002-RINSE] Timeout
# Wed Sep 20 14:34:05 2023 - PUBLISH - [SN-002] - STATUS > SPIN
# Wed Sep 20 14:34:05 2023 - [SN-002-SPIN] START
# Wed Sep 20 14:34:07 2023 - [SN-003-RINSE] Timeout
# Wed Sep 20 14:34:07 2023 - PUBLISH - [SN-003] - STATUS > SPIN
# Wed Sep 20 14:34:07 2023 - [SN-003-SPIN] START
# Wed Sep 20 14:34:09 2023 - [SN-004-RINSE] Timeout
# Wed Sep 20 14:34:09 2023 - PUBLISH - [SN-004] - STATUS > SPIN
# Wed Sep 20 14:34:09 2023 - [SN-004-SPIN] START
# Wed Sep 20 14:34:11 2023 - [SN-005-RINSE] Timeout
# Wed Sep 20 14:34:11 2023 - PUBLISH - [SN-005] - STATUS > SPIN
# Wed Sep 20 14:34:11 2023 - [SN-005-SPIN] START
# Wed Sep 20 14:34:12 2023 - PUBLISH - [SN-001] - STATUS > SPIN
# Wed Sep 20 14:34:12 2023 - PUBLISH - [SN-002] - STATUS > SPIN
# Wed Sep 20 14:34:12 2023 - PUBLISH - [SN-003] - STATUS > SPIN
# Wed Sep 20 14:34:12 2023 - PUBLISH - [SN-004] - STATUS > SPIN
# Wed Sep 20 14:34:12 2023 - PUBLISH - [SN-005] - STATUS > SPIN
# Wed Sep 20 14:34:21 2023 - PUBLISH - [SN-001] - STATUS > SPIN
# Wed Sep 20 14:34:21 2023 - PUBLISH - [SN-002] - STATUS > SPIN
# Wed Sep 20 14:34:21 2023 - PUBLISH - [SN-003] - STATUS > SPIN
# Wed Sep 20 14:34:21 2023 - PUBLISH - [SN-004] - STATUS > SPIN
# Wed Sep 20 14:34:21 2023 - PUBLISH - [SN-005] - STATUS > SPIN
# Wed Sep 20 14:34:23 2023 - [SN-001-SPIN] Timeout
# Wed Sep 20 14:34:23 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 20 14:34:23 2023 - [SN-001-OFF] Waiting to start...
# Wed Sep 20 14:34:25 2023 - [SN-002-SPIN] Timeout
# Wed Sep 20 14:34:25 2023 - PUBLISH - [SN-002] - STATUS > OFF
# Wed Sep 20 14:34:25 2023 - [SN-002-OFF] Waiting to start...
# Wed Sep 20 14:34:26 2023 - MQTT - [SN-001]:STATUS => READY
# Wed Sep 20 14:34:26 2023 - PUBLISH - [SN-001] - STATUS > READY
# Wed Sep 20 14:34:26 2023 - PUBLISH - [SN-001] - LID > CLOSE
# Wed Sep 20 14:34:26 2023 - PUBLISH - [SN-001] - STATUS > FILLWATER
# Wed Sep 20 14:34:26 2023 - [SN-001-FILLWATER] START
# Wed Sep 20 14:34:27 2023 - [SN-003-SPIN] Timeout
# Wed Sep 20 14:34:27 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 20 14:34:27 2023 - [SN-003-OFF] Waiting to start...
# Wed Sep 20 14:34:28 2023 - MQTT - [SN-002]:STATUS => READY
# Wed Sep 20 14:34:28 2023 - PUBLISH - [SN-002] - STATUS > READY
# Wed Sep 20 14:34:28 2023 - PUBLISH - [SN-002] - LID > CLOSE
# Wed Sep 20 14:34:28 2023 - PUBLISH - [SN-002] - STATUS > FILLWATER
# Wed Sep 20 14:34:28 2023 - [SN-002-FILLWATER] START
# Wed Sep 20 14:34:29 2023 - [SN-004-SPIN] Timeout
# Wed Sep 20 14:34:29 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 20 14:34:29 2023 - [SN-004-OFF] Waiting to start...
# Wed Sep 20 14:34:30 2023 - MQTT - [SN-001]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:34:30 2023 - [SN-001] Cancelled
# Wed Sep 20 14:34:30 2023 - PUBLISH - [SN-001] - STATUS > HEATWATER
# Wed Sep 20 14:34:30 2023 - [SN-001-HEATWATER] START
# Wed Sep 20 14:34:31 2023 - [SN-005-SPIN] Timeout
# Wed Sep 20 14:34:31 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 20 14:34:31 2023 - [SN-005-OFF] Waiting to start...
# Wed Sep 20 14:34:31 2023 - PUBLISH - [SN-001] - STATUS > HEATWATER
# Wed Sep 20 14:34:31 2023 - PUBLISH - [SN-002] - STATUS > FILLWATER
# Wed Sep 20 14:34:31 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 20 14:34:31 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 20 14:34:31 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 20 14:34:32 2023 - MQTT - [SN-003]:STATUS => READY
# Wed Sep 20 14:34:32 2023 - PUBLISH - [SN-003] - STATUS > READY
# Wed Sep 20 14:34:32 2023 - PUBLISH - [SN-003] - LID > CLOSE
# Wed Sep 20 14:34:32 2023 - PUBLISH - [SN-003] - STATUS > FILLWATER
# Wed Sep 20 14:34:32 2023 - [SN-003-FILLWATER] START
# Wed Sep 20 14:34:34 2023 - MQTT - [SN-002]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:34:34 2023 - [SN-002] Cancelled
# Wed Sep 20 14:34:34 2023 - PUBLISH - [SN-002] - STATUS > HEATWATER
# Wed Sep 20 14:34:34 2023 - [SN-002-HEATWATER] START
# Wed Sep 20 14:34:36 2023 - MQTT - [SN-004]:STATUS => READY
# Wed Sep 20 14:34:36 2023 - PUBLISH - [SN-004] - STATUS > READY
# Wed Sep 20 14:34:36 2023 - PUBLISH - [SN-004] - LID > CLOSE
# Wed Sep 20 14:34:36 2023 - PUBLISH - [SN-004] - STATUS > FILLWATER
# Wed Sep 20 14:34:36 2023 - [SN-004-FILLWATER] START
# Wed Sep 20 14:34:38 2023 - MQTT - [SN-001]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:34:38 2023 - [SN-001] Cancelled
# Wed Sep 20 14:34:38 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:34:38 2023 - [SN-001-WASH] START
# Wed Sep 20 14:34:40 2023 - MQTT - [SN-005]:STATUS => READY
# Wed Sep 20 14:34:40 2023 - PUBLISH - [SN-005] - STATUS > READY
# Wed Sep 20 14:34:40 2023 - PUBLISH - [SN-005] - LID > CLOSE
# Wed Sep 20 14:34:40 2023 - PUBLISH - [SN-005] - STATUS > FILLWATER
# Wed Sep 20 14:34:40 2023 - [SN-005-FILLWATER] START
# Wed Sep 20 14:34:41 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:34:41 2023 - PUBLISH - [SN-002] - STATUS > HEATWATER
# Wed Sep 20 14:34:41 2023 - PUBLISH - [SN-003] - STATUS > FILLWATER
# Wed Sep 20 14:34:41 2023 - PUBLISH - [SN-004] - STATUS > FILLWATER
# Wed Sep 20 14:34:41 2023 - PUBLISH - [SN-005] - STATUS > FILLWATER
# Wed Sep 20 14:34:42 2023 - MQTT - [SN-003]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:34:42 2023 - [SN-003] Cancelled
# Wed Sep 20 14:34:42 2023 - PUBLISH - [SN-003] - STATUS > HEATWATER
# Wed Sep 20 14:34:42 2023 - [SN-003-HEATWATER] START
# Wed Sep 20 14:34:44 2023 - MQTT - [SN-002]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:34:44 2023 - [SN-002] Cancelled
# Wed Sep 20 14:34:44 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:34:44 2023 - [SN-002-WASH] START
# Wed Sep 20 14:34:46 2023 - MQTT - [SN-004]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:34:46 2023 - [SN-004] Cancelled
# Wed Sep 20 14:34:46 2023 - PUBLISH - [SN-004] - STATUS > HEATWATER
# Wed Sep 20 14:34:46 2023 - [SN-004-HEATWATER] START
# Wed Sep 20 14:34:48 2023 - MQTT - [SN-005]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:34:48 2023 - [SN-005] Cancelled
# Wed Sep 20 14:34:48 2023 - PUBLISH - [SN-005] - STATUS > HEATWATER
# Wed Sep 20 14:34:48 2023 - [SN-005-HEATWATER] START
# Wed Sep 20 14:34:50 2023 - MQTT - [SN-003]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:34:50 2023 - [SN-003] Cancelled
# Wed Sep 20 14:34:50 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:34:50 2023 - [SN-003-WASH] START
# Wed Sep 20 14:34:51 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:34:51 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:34:51 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:34:51 2023 - PUBLISH - [SN-004] - STATUS > HEATWATER
# Wed Sep 20 14:34:51 2023 - PUBLISH - [SN-005] - STATUS > HEATWATER
# Wed Sep 20 14:34:52 2023 - MQTT - [SN-004]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:34:52 2023 - [SN-004] Cancelled
# Wed Sep 20 14:34:52 2023 - PUBLISH - [SN-004] - STATUS > WASH
# Wed Sep 20 14:34:52 2023 - [SN-004-WASH] START
# Wed Sep 20 14:34:54 2023 - MQTT - [SN-005]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:34:54 2023 - [SN-005] Cancelled
# Wed Sep 20 14:34:54 2023 - PUBLISH - [SN-005] - STATUS > WASH
# Wed Sep 20 14:34:54 2023 - [SN-005-WASH] START
# Wed Sep 20 14:34:58 2023 - [SN-001-WASH] Timeout
# Wed Sep 20 14:34:58 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:34:58 2023 - [SN-001-RINSE] START
# Wed Sep 20 14:35:01 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:35:01 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:35:01 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:35:01 2023 - PUBLISH - [SN-004] - STATUS > WASH
# Wed Sep 20 14:35:01 2023 - PUBLISH - [SN-005] - STATUS > WASH
# Wed Sep 20 14:35:04 2023 - [SN-002-WASH] Timeout
# Wed Sep 20 14:35:04 2023 - PUBLISH - [SN-002] - STATUS > RINSE
# Wed Sep 20 14:35:04 2023 - [SN-002-RINSE] START
# Wed Sep 20 14:35:10 2023 - [SN-003-WASH] Timeout
# Wed Sep 20 14:35:10 2023 - PUBLISH - [SN-003] - STATUS > RINSE
# Wed Sep 20 14:35:10 2023 - [SN-003-RINSE] START
# Wed Sep 20 14:35:11 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:35:11 2023 - PUBLISH - [SN-002] - STATUS > RINSE
# Wed Sep 20 14:35:11 2023 - PUBLISH - [SN-003] - STATUS > RINSE
# Wed Sep 20 14:35:11 2023 - PUBLISH - [SN-004] - STATUS > WASH
# Wed Sep 20 14:35:11 2023 - PUBLISH - [SN-005] - STATUS > WASH
# Wed Sep 20 14:35:12 2023 - [SN-004-WASH] Timeout
# Wed Sep 20 14:35:12 2023 - PUBLISH - [SN-004] - STATUS > RINSE
# Wed Sep 20 14:35:12 2023 - [SN-004-RINSE] START
# Wed Sep 20 14:35:14 2023 - [SN-005-WASH] Timeout
# Wed Sep 20 14:35:14 2023 - PUBLISH - [SN-005] - STATUS > RINSE
# Wed Sep 20 14:35:14 2023 - [SN-005-RINSE] START
# Wed Sep 20 14:35:18 2023 - [SN-001-RINSE] Timeout
# Wed Sep 20 14:35:18 2023 - PUBLISH - [SN-001] - STATUS > SPIN
# Wed Sep 20 14:35:18 2023 - [SN-001-SPIN] START
# Wed Sep 20 14:35:21 2023 - PUBLISH - [SN-001] - STATUS > SPIN
# Wed Sep 20 14:35:21 2023 - PUBLISH - [SN-002] - STATUS > RINSE
# Wed Sep 20 14:35:21 2023 - PUBLISH - [SN-003] - STATUS > RINSE
# Wed Sep 20 14:35:21 2023 - PUBLISH - [SN-004] - STATUS > RINSE
# Wed Sep 20 14:35:21 2023 - PUBLISH - [SN-005] - STATUS > RINSE
# Wed Sep 20 14:35:24 2023 - [SN-002-RINSE] Timeout
# Wed Sep 20 14:35:24 2023 - PUBLISH - [SN-002] - STATUS > SPIN
# Wed Sep 20 14:35:24 2023 - [SN-002-SPIN] START
# Wed Sep 20 14:35:30 2023 - [SN-003-RINSE] Timeout
# Wed Sep 20 14:35:30 2023 - PUBLISH - [SN-003] - STATUS > SPIN
# Wed Sep 20 14:35:30 2023 - [SN-003-SPIN] START
# Wed Sep 20 14:35:31 2023 - PUBLISH - [SN-001] - STATUS > SPIN
# Wed Sep 20 14:35:31 2023 - PUBLISH - [SN-002] - STATUS > SPIN
# Wed Sep 20 14:35:31 2023 - PUBLISH - [SN-003] - STATUS > SPIN
# Wed Sep 20 14:35:31 2023 - PUBLISH - [SN-004] - STATUS > RINSE
# Wed Sep 20 14:35:31 2023 - PUBLISH - [SN-005] - STATUS > RINSE
# Wed Sep 20 14:35:32 2023 - [SN-004-RINSE] Timeout
# Wed Sep 20 14:35:32 2023 - PUBLISH - [SN-004] - STATUS > SPIN
# Wed Sep 20 14:35:32 2023 - [SN-004-SPIN] START
# Wed Sep 20 14:35:34 2023 - [SN-005-RINSE] Timeout
# Wed Sep 20 14:35:34 2023 - PUBLISH - [SN-005] - STATUS > SPIN
# Wed Sep 20 14:35:34 2023 - [SN-005-SPIN] START
# Wed Sep 20 14:35:38 2023 - [SN-001-SPIN] Timeout
# Wed Sep 20 14:35:38 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 20 14:35:38 2023 - [SN-001-OFF] Waiting to start...
# Wed Sep 20 14:35:40 2023 - MQTT - [SN-001]:STATUS => READY
# Wed Sep 20 14:35:40 2023 - PUBLISH - [SN-001] - STATUS > READY
# Wed Sep 20 14:35:40 2023 - PUBLISH - [SN-001] - LID > CLOSE
# Wed Sep 20 14:35:40 2023 - PUBLISH - [SN-001] - STATUS > FILLWATER
# Wed Sep 20 14:35:40 2023 - [SN-001-FILLWATER] START
# Wed Sep 20 14:35:41 2023 - PUBLISH - [SN-001] - STATUS > FILLWATER
# Wed Sep 20 14:35:41 2023 - PUBLISH - [SN-002] - STATUS > SPIN
# Wed Sep 20 14:35:41 2023 - PUBLISH - [SN-003] - STATUS > SPIN
# Wed Sep 20 14:35:41 2023 - PUBLISH - [SN-004] - STATUS > SPIN
# Wed Sep 20 14:35:41 2023 - PUBLISH - [SN-005] - STATUS > SPIN
# Wed Sep 20 14:35:43 2023 - MQTT - [SN-001]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:35:43 2023 - [SN-001] Cancelled
# Wed Sep 20 14:35:43 2023 - PUBLISH - [SN-001] - STATUS > HEATWATER
# Wed Sep 20 14:35:43 2023 - [SN-001-HEATWATER] START
# Wed Sep 20 14:35:44 2023 - [SN-002-SPIN] Timeout
# Wed Sep 20 14:35:44 2023 - PUBLISH - [SN-002] - STATUS > OFF
# Wed Sep 20 14:35:44 2023 - [SN-002-OFF] Waiting to start...
# Wed Sep 20 14:35:45 2023 - MQTT - [SN-001]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:35:45 2023 - [SN-001] Cancelled
# Wed Sep 20 14:35:45 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:35:45 2023 - [SN-001-WASH] START
# Wed Sep 20 14:35:47 2023 - MQTT - [SN-002]:STATUS => READY
# Wed Sep 20 14:35:47 2023 - PUBLISH - [SN-002] - STATUS > READY
# Wed Sep 20 14:35:47 2023 - PUBLISH - [SN-002] - LID > CLOSE
# Wed Sep 20 14:35:47 2023 - PUBLISH - [SN-002] - STATUS > FILLWATER
# Wed Sep 20 14:35:47 2023 - [SN-002-FILLWATER] START
# Wed Sep 20 14:35:50 2023 - [SN-003-SPIN] Timeout
# Wed Sep 20 14:35:50 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 20 14:35:50 2023 - [SN-003-OFF] Waiting to start...
# Wed Sep 20 14:35:50 2023 - MQTT - [SN-002]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:35:50 2023 - [SN-002] Cancelled
# Wed Sep 20 14:35:50 2023 - PUBLISH - [SN-002] - STATUS > HEATWATER
# Wed Sep 20 14:35:50 2023 - [SN-002-HEATWATER] START
# Wed Sep 20 14:35:52 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:35:52 2023 - PUBLISH - [SN-002] - STATUS > HEATWATER
# Wed Sep 20 14:35:52 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 20 14:35:52 2023 - PUBLISH - [SN-004] - STATUS > SPIN
# Wed Sep 20 14:35:52 2023 - PUBLISH - [SN-005] - STATUS > SPIN
# Wed Sep 20 14:35:52 2023 - [SN-004-SPIN] Timeout
# Wed Sep 20 14:35:52 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 20 14:35:52 2023 - [SN-004-OFF] Waiting to start...
# Wed Sep 20 14:35:52 2023 - MQTT - [SN-003]:STATUS => READY
# Wed Sep 20 14:35:52 2023 - PUBLISH - [SN-003] - STATUS > READY
# Wed Sep 20 14:35:52 2023 - PUBLISH - [SN-003] - LID > CLOSE
# Wed Sep 20 14:35:52 2023 - PUBLISH - [SN-003] - STATUS > FILLWATER
# Wed Sep 20 14:35:52 2023 - [SN-003-FILLWATER] START
# Wed Sep 20 14:35:54 2023 - [SN-005-SPIN] Timeout
# Wed Sep 20 14:35:54 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 20 14:35:54 2023 - [SN-005-OFF] Waiting to start...
# Wed Sep 20 14:35:54 2023 - MQTT - [SN-002]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:35:54 2023 - [SN-002] Cancelled
# Wed Sep 20 14:35:54 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:35:54 2023 - [SN-002-WASH] START
# Wed Sep 20 14:35:56 2023 - MQTT - [SN-004]:STATUS => READY
# Wed Sep 20 14:35:56 2023 - PUBLISH - [SN-004] - STATUS > READY
# Wed Sep 20 14:35:56 2023 - PUBLISH - [SN-004] - LID > CLOSE
# Wed Sep 20 14:35:56 2023 - PUBLISH - [SN-004] - STATUS > FILLWATER
# Wed Sep 20 14:35:56 2023 - [SN-004-FILLWATER] START
# Wed Sep 20 14:35:58 2023 - MQTT - [SN-003]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:35:58 2023 - [SN-003] Cancelled
# Wed Sep 20 14:35:58 2023 - PUBLISH - [SN-003] - STATUS > HEATWATER
# Wed Sep 20 14:35:58 2023 - [SN-003-HEATWATER] START
# Wed Sep 20 14:36:00 2023 - MQTT - [SN-005]:STATUS => READY
# Wed Sep 20 14:36:00 2023 - PUBLISH - [SN-005] - STATUS > READY
# Wed Sep 20 14:36:00 2023 - PUBLISH - [SN-005] - LID > CLOSE
# Wed Sep 20 14:36:00 2023 - PUBLISH - [SN-005] - STATUS > FILLWATER
# Wed Sep 20 14:36:00 2023 - [SN-005-FILLWATER] START
# Wed Sep 20 14:36:02 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:36:02 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:36:02 2023 - PUBLISH - [SN-003] - STATUS > HEATWATER
# Wed Sep 20 14:36:02 2023 - PUBLISH - [SN-004] - STATUS > FILLWATER
# Wed Sep 20 14:36:02 2023 - PUBLISH - [SN-005] - STATUS > FILLWATER
# Wed Sep 20 14:36:02 2023 - MQTT - [SN-004]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:36:02 2023 - [SN-004] Cancelled
# Wed Sep 20 14:36:02 2023 - PUBLISH - [SN-004] - STATUS > HEATWATER
# Wed Sep 20 14:36:02 2023 - [SN-004-HEATWATER] START
# Wed Sep 20 14:36:04 2023 - MQTT - [SN-003]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:36:04 2023 - [SN-003] Cancelled
# Wed Sep 20 14:36:04 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:36:04 2023 - [SN-003-WASH] START
# Wed Sep 20 14:36:05 2023 - [SN-001-WASH] Timeout
# Wed Sep 20 14:36:05 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:36:05 2023 - [SN-001-RINSE] START
# Wed Sep 20 14:36:06 2023 - MQTT - [SN-005]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:36:06 2023 - [SN-005] Cancelled
# Wed Sep 20 14:36:06 2023 - PUBLISH - [SN-005] - STATUS > HEATWATER
# Wed Sep 20 14:36:06 2023 - [SN-005-HEATWATER] START
# Wed Sep 20 14:36:08 2023 - MQTT - [SN-004]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:36:08 2023 - [SN-004] Cancelled
# Wed Sep 20 14:36:08 2023 - PUBLISH - [SN-004] - STATUS > WASH
# Wed Sep 20 14:36:08 2023 - [SN-004-WASH] START
# Wed Sep 20 14:36:10 2023 - MQTT - [SN-005]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:36:10 2023 - [SN-005] Cancelled
# Wed Sep 20 14:36:10 2023 - PUBLISH - [SN-005] - STATUS > WASH
# Wed Sep 20 14:36:10 2023 - [SN-005-WASH] START
# Wed Sep 20 14:36:12 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:36:12 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:36:12 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:36:12 2023 - PUBLISH - [SN-004] - STATUS > WASH
# Wed Sep 20 14:36:12 2023 - PUBLISH - [SN-005] - STATUS > WASH
# Wed Sep 20 14:36:14 2023 - [SN-002-WASH] Timeout
# Wed Sep 20 14:36:14 2023 - PUBLISH - [SN-002] - STATUS > RINSE
# Wed Sep 20 14:36:14 2023 - [SN-002-RINSE] START
# Wed Sep 20 14:36:22 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:36:22 2023 - PUBLISH - [SN-002] - STATUS > RINSE
# Wed Sep 20 14:36:22 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:36:22 2023 - PUBLISH - [SN-004] - STATUS > WASH
# Wed Sep 20 14:36:22 2023 - PUBLISH - [SN-005] - STATUS > WASH
# Wed Sep 20 14:36:24 2023 - [SN-003-WASH] Timeout
# Wed Sep 20 14:36:24 2023 - PUBLISH - [SN-003] - STATUS > RINSE
# Wed Sep 20 14:36:24 2023 - [SN-003-RINSE] START
# Wed Sep 20 14:36:25 2023 - [SN-001-RINSE] Timeout
# Wed Sep 20 14:36:25 2023 - PUBLISH - [SN-001] - STATUS > SPIN
# Wed Sep 20 14:36:25 2023 - [SN-001-SPIN] START
# Wed Sep 20 14:36:28 2023 - [SN-004-WASH] Timeout
# Wed Sep 20 14:36:28 2023 - PUBLISH - [SN-004] - STATUS > RINSE
# Wed Sep 20 14:36:28 2023 - [SN-004-RINSE] START
# Wed Sep 20 14:36:30 2023 - [SN-005-WASH] Timeout
# Wed Sep 20 14:36:30 2023 - PUBLISH - [SN-005] - STATUS > RINSE
# Wed Sep 20 14:36:30 2023 - [SN-005-RINSE] START
# Wed Sep 20 14:36:32 2023 - PUBLISH - [SN-001] - STATUS > SPIN
# Wed Sep 20 14:36:32 2023 - PUBLISH - [SN-002] - STATUS > RINSE
# Wed Sep 20 14:36:32 2023 - PUBLISH - [SN-003] - STATUS > RINSE
# Wed Sep 20 14:36:32 2023 - PUBLISH - [SN-004] - STATUS > RINSE
# Wed Sep 20 14:36:32 2023 - PUBLISH - [SN-005] - STATUS > RINSE
# Wed Sep 20 14:36:34 2023 - [SN-002-RINSE] Timeout
# Wed Sep 20 14:36:34 2023 - PUBLISH - [SN-002] - STATUS > SPIN
# Wed Sep 20 14:36:34 2023 - [SN-002-SPIN] START
# Wed Sep 20 14:36:42 2023 - PUBLISH - [SN-001] - STATUS > SPIN
# Wed Sep 20 14:36:42 2023 - PUBLISH - [SN-002] - STATUS > SPIN
# Wed Sep 20 14:36:42 2023 - PUBLISH - [SN-003] - STATUS > RINSE
# Wed Sep 20 14:36:42 2023 - PUBLISH - [SN-004] - STATUS > RINSE
# Wed Sep 20 14:36:42 2023 - PUBLISH - [SN-005] - STATUS > RINSE
# Wed Sep 20 14:36:44 2023 - [SN-003-RINSE] Timeout
# Wed Sep 20 14:36:44 2023 - PUBLISH - [SN-003] - STATUS > SPIN
# Wed Sep 20 14:36:44 2023 - [SN-003-SPIN] START
# Wed Sep 20 14:36:45 2023 - [SN-001-SPIN] Timeout
# Wed Sep 20 14:36:45 2023 - PUBLISH - [SN-001] - STATUS > OFF
# Wed Sep 20 14:36:45 2023 - [SN-001-OFF] Waiting to start...
# Wed Sep 20 14:36:48 2023 - MQTT - [SN-001]:STATUS => READY
# Wed Sep 20 14:36:48 2023 - PUBLISH - [SN-001] - STATUS > READY
# Wed Sep 20 14:36:48 2023 - PUBLISH - [SN-001] - LID > CLOSE
# Wed Sep 20 14:36:48 2023 - PUBLISH - [SN-001] - STATUS > FILLWATER
# Wed Sep 20 14:36:48 2023 - [SN-001-FILLWATER] START
# Wed Sep 20 14:36:48 2023 - [SN-004-RINSE] Timeout
# Wed Sep 20 14:36:48 2023 - PUBLISH - [SN-004] - STATUS > SPIN
# Wed Sep 20 14:36:48 2023 - [SN-004-SPIN] START
# Wed Sep 20 14:36:50 2023 - MQTT - [SN-001]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:36:50 2023 - [SN-001] Cancelled
# Wed Sep 20 14:36:50 2023 - PUBLISH - [SN-001] - STATUS > HEATWATER
# Wed Sep 20 14:36:50 2023 - [SN-001-HEATWATER] START
# Wed Sep 20 14:36:50 2023 - [SN-005-RINSE] Timeout
# Wed Sep 20 14:36:50 2023 - PUBLISH - [SN-005] - STATUS > SPIN
# Wed Sep 20 14:36:50 2023 - [SN-005-SPIN] START
# Wed Sep 20 14:36:52 2023 - PUBLISH - [SN-001] - STATUS > HEATWATER
# Wed Sep 20 14:36:52 2023 - PUBLISH - [SN-002] - STATUS > SPIN
# Wed Sep 20 14:36:52 2023 - PUBLISH - [SN-003] - STATUS > SPIN
# Wed Sep 20 14:36:52 2023 - PUBLISH - [SN-004] - STATUS > SPIN
# Wed Sep 20 14:36:52 2023 - PUBLISH - [SN-005] - STATUS > SPIN
# Wed Sep 20 14:36:53 2023 - MQTT - [SN-001]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:36:53 2023 - [SN-001] Cancelled
# Wed Sep 20 14:36:53 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:36:53 2023 - [SN-001-WASH] START
# Wed Sep 20 14:36:54 2023 - [SN-002-SPIN] Timeout
# Wed Sep 20 14:36:54 2023 - PUBLISH - [SN-002] - STATUS > OFF
# Wed Sep 20 14:36:54 2023 - [SN-002-OFF] Waiting to start...
# Wed Sep 20 14:36:57 2023 - MQTT - [SN-002]:STATUS => READY
# Wed Sep 20 14:36:57 2023 - PUBLISH - [SN-002] - STATUS > READY
# Wed Sep 20 14:36:57 2023 - PUBLISH - [SN-002] - LID > CLOSE
# Wed Sep 20 14:36:57 2023 - PUBLISH - [SN-002] - STATUS > FILLWATER
# Wed Sep 20 14:36:57 2023 - [SN-002-FILLWATER] START
# Wed Sep 20 14:36:59 2023 - MQTT - [SN-002]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:36:59 2023 - [SN-002] Cancelled
# Wed Sep 20 14:36:59 2023 - PUBLISH - [SN-002] - STATUS > HEATWATER
# Wed Sep 20 14:36:59 2023 - [SN-002-HEATWATER] START
# Wed Sep 20 14:37:02 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:37:02 2023 - PUBLISH - [SN-002] - STATUS > HEATWATER
# Wed Sep 20 14:37:02 2023 - PUBLISH - [SN-003] - STATUS > SPIN
# Wed Sep 20 14:37:02 2023 - PUBLISH - [SN-004] - STATUS > SPIN
# Wed Sep 20 14:37:02 2023 - PUBLISH - [SN-005] - STATUS > SPIN
# Wed Sep 20 14:37:02 2023 - MQTT - [SN-002]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:37:02 2023 - [SN-002] Cancelled
# Wed Sep 20 14:37:02 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:37:02 2023 - [SN-002-WASH] START
# Wed Sep 20 14:37:04 2023 - [SN-003-SPIN] Timeout
# Wed Sep 20 14:37:04 2023 - PUBLISH - [SN-003] - STATUS > OFF
# Wed Sep 20 14:37:04 2023 - [SN-003-OFF] Waiting to start...
# Wed Sep 20 14:37:07 2023 - MQTT - [SN-003]:STATUS => READY
# Wed Sep 20 14:37:07 2023 - PUBLISH - [SN-003] - STATUS > READY
# Wed Sep 20 14:37:07 2023 - PUBLISH - [SN-003] - LID > CLOSE
# Wed Sep 20 14:37:07 2023 - PUBLISH - [SN-003] - STATUS > FILLWATER
# Wed Sep 20 14:37:07 2023 - [SN-003-FILLWATER] START
# Wed Sep 20 14:37:08 2023 - [SN-004-SPIN] Timeout
# Wed Sep 20 14:37:08 2023 - PUBLISH - [SN-004] - STATUS > OFF
# Wed Sep 20 14:37:08 2023 - [SN-004-OFF] Waiting to start...
# Wed Sep 20 14:37:09 2023 - MQTT - [SN-003]:WATERFULLLEVEL => FULL
# Wed Sep 20 14:37:09 2023 - [SN-003] Cancelled
# Wed Sep 20 14:37:09 2023 - PUBLISH - [SN-003] - STATUS > HEATWATER
# Wed Sep 20 14:37:09 2023 - [SN-003-HEATWATER] START
# Wed Sep 20 14:37:10 2023 - [SN-005-SPIN] Timeout
# Wed Sep 20 14:37:10 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 20 14:37:10 2023 - [SN-005-OFF] Waiting to start...
# Wed Sep 20 14:37:11 2023 - MQTT - [SN-004]:STATUS => READY
# Wed Sep 20 14:37:11 2023 - PUBLISH - [SN-004] - STATUS > READY
# Wed Sep 20 14:37:11 2023 - PUBLISH - [SN-004] - LID > CLOSE
# Wed Sep 20 14:37:11 2023 - PUBLISH - [SN-004] - STATUS > FILLWATER
# Wed Sep 20 14:37:11 2023 - [SN-004-FILLWATER] START
# Wed Sep 20 14:37:12 2023 - PUBLISH - [SN-001] - STATUS > WASH
# Wed Sep 20 14:37:12 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:37:12 2023 - PUBLISH - [SN-003] - STATUS > HEATWATER
# Wed Sep 20 14:37:12 2023 - PUBLISH - [SN-004] - STATUS > FILLWATER
# Wed Sep 20 14:37:12 2023 - PUBLISH - [SN-005] - STATUS > OFF
# Wed Sep 20 14:37:13 2023 - [SN-001-WASH] Timeout
# Wed Sep 20 14:37:13 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:37:13 2023 - [SN-001-RINSE] START
# Wed Sep 20 14:37:13 2023 - MQTT - [SN-003]:TEMPERATUREREACHED => REACHED
# Wed Sep 20 14:37:13 2023 - [SN-003] Cancelled
# Wed Sep 20 14:37:13 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:37:13 2023 - [SN-003-WASH] START
# Wed Sep 20 14:37:21 2023 - [SN-003] Cancelled
# Wed Sep 20 14:37:21 2023 - PUBLISH - [SN-003] - STATUS > WASH
# Wed Sep 20 14:37:21 2023 - [SN-002] Cancelled
# Wed Sep 20 14:37:21 2023 - PUBLISH - [SN-002] - STATUS > WASH
# Wed Sep 20 14:37:21 2023 - [SN-001] Cancelled
# Wed Sep 20 14:37:21 2023 - PUBLISH - [SN-001] - STATUS > RINSE
# Wed Sep 20 14:37:21 2023 - [SN-004] Cancelled
