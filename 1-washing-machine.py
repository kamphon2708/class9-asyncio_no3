import time
import random
import json
import asyncio
import aiomqtt
from enum import Enum
import sys
import os

student_id = "6310301011"


class MachineStatus(Enum):
    pressure = round(random.uniform(2000, 3000), 2)
    temperature = round(random.uniform(25.0, 40.0), 2)
    speed = round(random.uniform(25.0, 40.0), 2)
    #
    # add more machine status
    #


class MachineMaintStatus(Enum):
    filter = random.choice(["clear", "clogged"])
    noise = random.choice(["quiet", "noisy"])
    #
    # add more maintenance status
    #


class WashingMachine:
    def __init__(self, serial):
        self.MACHINE_STATUS = 'OFF'
        self.SERIAL = serial


async def publish_message(w, client, app, action, name, value):
    print(f"{time.ctime()} - [{w.SERIAL}] {name}:{value}")
    await asyncio.sleep(2)
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


async def CoroWashingMachine(w, client):
    # washing coroutine
    while True:
        wait_next = round(10*random.random(), 2)
        print(
            f"{time.ctime()} - [{w.SERIAL}] Waiting to start... {wait_next} seconds.")
        await asyncio.sleep(wait_next)
        if w.MACHINE_STATUS == 'OFF':
            continue
        else:
            await publish_message(w, client, 'hw', 'set', 'STATUS', 'START')
            await publish_message(w, client, 'hw', 'set', 'LID', 'OPEN')
            await publish_message(w, client, 'hw', 'set', 'LID', 'CLOSE')

            status = random.choice(list(MachineStatus))
            await publish_message(w, client, 'app', 'get', status.name, status.value)
            await publish_message(w, client, 'app', 'get', "STATUS", "FINISHED")

            maint = random.choice(list(MachineMaintStatus))
            await publish_message(w, client, 'app', 'get', maint.name, maint.value)

            sensor = random.choice(list(MachineStatus))

            await publish_message(w, client, 'app', 'get', 'SPEED', '100')

            if maint.name == 'noise' and maint.value == 'noisy':
                w.MACHINE_STATUS = 'OFF'
                continue

            w.MACHINE_STATUS = 'OFF'


async def listen(w, client):
    async with client.messages() as messages:
        await client.subscribe(f"v1cdti/hw/set/{student_id}/model-01/{w.SERIAL}")
        async for message in messages:
            m_decode = json.loads(message.payload)
            if message.topic.matches(f"v1cdti/hw/set/{student_id}/model-01/{w.SERIAL}"):
                print(
                    f"{time.ctime()} - MQTT - [{m_decode['serial']}]:{m_decode['name']} => {m_decode['value']}")
                w.MACHINE_STATUS = 'ON'


async def main():
    w1 = WashingMachine(serial='SN-001')
    async with aiomqtt.Client("test.mosquitto.org") as client:
        print(client)
        await asyncio.gather(listen(w1, client), CoroWashingMachine(w1, client))
        # await listen(client)


# Change to the "Selector" event loop if platform is Windows
if sys.platform.lower() == "win32" or os.name.lower() == "nt":
    from asyncio import set_event_loop_policy, WindowsSelectorEventLoopPolicy
    set_event_loop_policy(WindowsSelectorEventLoopPolicy())
# Run your async application as usual
asyncio.run(main())


# Wed Aug 30 14:29:55 2023 - [SN-001] Waiting to start... 3.81 seconds.
# Wed Aug 30 14:29:59 2023 - [SN-001] Waiting to start... 5.84 seconds.
# Wed Aug 30 14:30:05 2023 - [SN-001] Waiting to start... 9.0 seconds.
# Wed Aug 30 14:30:07 2023 - MQTT - [SN-001]:POWER => ON
# Wed Aug 30 14:30:14 2023 - [SN-001] STATUS:START
# Wed Aug 30 14:30:16 2023 - PUBLISH - [SN-001] - STATUS > START
# Wed Aug 30 14:30:16 2023 - [SN-001] LID:OPEN
# Wed Aug 30 14:30:17 2023 - MQTT - [SN-001]:STATUS => START
# Wed Aug 30 14:30:18 2023 - PUBLISH - [SN-001] - LID > OPEN
# Wed Aug 30 14:30:18 2023 - [SN-001] LID:CLOSE
# Wed Aug 30 14:30:18 2023 - MQTT - [SN-001]:LID => OPEN
# Wed Aug 30 14:30:20 2023 - PUBLISH - [SN-001] - LID > CLOSE
# Wed Aug 30 14:30:20 2023 - [SN-001] pressure:2302.94
# Wed Aug 30 14:30:20 2023 - MQTT - [SN-001]:LID => CLOSE
# Wed Aug 30 14:30:22 2023 - PUBLISH - [SN-001] - pressure > 2302.94
# Wed Aug 30 14:30:22 2023 - [SN-001] STATUS:FINISHED
# Wed Aug 30 14:30:24 2023 - PUBLISH - [SN-001] - STATUS > FINISHED
# Wed Aug 30 14:30:24 2023 - [SN-001] noise:quiet
# Wed Aug 30 14:30:26 2023 - PUBLISH - [SN-001] - noise > quiet
# Wed Aug 30 14:30:26 2023 - [SN-001] SPEED:100
# Wed Aug 30 14:30:28 2023 - PUBLISH - [SN-001] - SPEED > 100
# Wed Aug 30 14:30:28 2023 - [SN-001] Waiting to start... 2.45 seconds.
# Wed Aug 30 14:30:31 2023 - [SN-001] Waiting to start... 9.94 seconds.
# Wed Aug 30 14:30:41 2023 - [SN-001] Waiting to start... 0.41 seconds.
# Wed Aug 30 14:30:41 2023 - [SN-001] Waiting to start... 7.6 seconds.
# Wed Aug 30 14:30:49 2023 - [SN-001] Waiting to start... 0.84 seconds.
# Wed Aug 30 14:30:49 2023 - [SN-001] Waiting to start... 2.19 seconds.
# Wed Aug 30 14:30:52 2023 - [SN-001] Waiting to start... 7.64 seconds.