import time
import random
import json
import asyncio
import aiomqtt
from enum import Enum
import sys,os

student_id = "6310301011"

# State 
S_OFF       = 'OFF'
S_READY     = 'READY'
S_FAULT     = 'FAULT'
S_FILLWATER = 'FILLWATER'
S_HEATWATER = 'HEATWATER'
S_WASH      = 'WASH'
S_RINSE     = 'RINSE'
S_SPIN      = 'SPIN'
S_STOP      = 'STOP'

# Function
S_DOORCLOSED            = 'DOORCLOSE'
S_FULLLEVELDETECTED     = 'FULLLEVELDETECTED'
S_TEMPERATUREREACHED    = 'TEMPERATUREREACHED'
S_FUNCTIONCOMPLETED     = 'FUNCTIONCOMPLETED'
S_TIMEOUT               = 'TIMEOUT'
S_MOTORFAILURE          = 'MOTORFAILURE'
S_FAULTCLEARED          = 'FAULTCLEARED'

async def publish_message(w, client, app, action, name, value):
    await asyncio.sleep(1)
    payload = {
                "action"    : "get",
                "project"   : student_id,
                "model"     : "model-01",
                "serial"    : w.SERIAL,
                "name"      : name,
                "value"     : value
            }
    print(f"{time.ctime()} - PUB topic: v1cdti/{app}/{action}/{student_id}/model-01/{w.SERIAL} payload: {name}:{value}")
    await client.publish(f"v1cdti/{app}/{action}/{student_id}/model-01/{w.SERIAL}"
                        , payload=json.dumps(payload))

async def action(w, msg='', maxtime=100):
    print(f"{time.ctime()} - [{w.SERIAL}-{w.STATE}] Waiting for maxinum {maxtime} seconds")
    await asyncio.sleep(maxtime)

async def actionWithinTime(w, client, nextstate, msg='', defaulttime=10):
    # fill water untill full level detected within 10 seconds if not full then timeout 
    try:
        async with asyncio.timeout(defaulttime):
            await publish_message(w, client, "app", "get", "STATUS", w.STATE)
            w.Task = asyncio.create_task(action(w, msg=msg))
            await w.Task
    except TimeoutError:
        w.STATE = S_FAULT
        print(f"{time.ctime()} - [{w.SERIAL}-{w.STATE}] {msg} timeout...{defaulttime} seconds")
    except asyncio.CancelledError:
        print(f"{time.ctime()} - [{w.SERIAL}-{w.STATE}] {msg} finished...")
        w.STATE = nextstate

async def waiter(w, event):
    print(f"{time.ctime()} - [{w.SERIAL}-{w.STATE}] Waiting next state...")
    await event.wait()
    print(f"{time.ctime()} - [{w.SERIAL}-{w.STATE}] ... got it")


class MachineStatus(Enum):
    pressure = round(random.uniform(2000,3000), 2)
    temperature = round(random.uniform(25.0,40.0), 2)

class MachineMaintStatus(Enum):
    filter = random.choice(["clear", "clogged"])
    noise = random.choice(["quiet", "noisy"])

class WashingMachine:
    def __init__(self, serial):
        self.SERIAL = serial
        self.STATE = 'OFF'
        self.Task = None
        self.event = asyncio.Event()

async def CoroWashingMachine(w, client):

    while True:
        w.event = asyncio.Event()
        waiter_task = asyncio.create_task(waiter(w, w.event))
        await waiter_task
        
        if w.STATE == S_OFF:
            await publish_message(w, client, "app", "get", "STATUS", w.STATE)

        if w.STATE == S_FAULT:
            await publish_message(w, client, "app", "get", "STATUS", w.STATE)

        if w.STATE == S_READY:
            await publish_message(w, client, "app", "get", "STATUS", w.STATE)

            # door close
            await publish_message(w, client, "app", "get", "STATUS", S_DOORCLOSED)

            # fill water untill full level detected within 10 seconds if not full then timeout
            print(f"{time.ctime()} - [{w.SERIAL}-{w.STATE}] Filling water...")
            w.STATE = S_FILLWATER
            await actionWithinTime(w, client, nextstate=S_HEATWATER, msg='Filling water')
            
        
        # heat water until temperature reach 30 celcius within 10 seconds if not reach 30 celcius then timeout
        if w.STATE == S_HEATWATER:
            await publish_message(w, client, "app", "get", "STATUS", w.STATE)

            # heat water untill  detected within 10 seconds if not full then timeout
            print(f"{time.ctime()} - [{w.SERIAL}-{w.STATE}] Heating water...")
            await actionWithinTime(w, client, nextstate=S_WASH, msg='Heating water')

        # wash 10 seconds, if out of balance detected then fault

        # rinse 10 seconds, if motor failure detect then fault

        # spin 10 seconds, if motor failure detect then fault

        # When washing is in FAULT state, wait until get FAULTCLEARED

        wait_next = round(5*random.random(),2)
        print(f"sleep {wait_next} seconds")
        await asyncio.sleep(wait_next)
            

async def listen(client):
    async with client.messages() as messages:
        await client.subscribe(f"v1cdti/app/monitor/{student_id}/model-01/+")
        print(f"{time.ctime()} SUB topic: v1cdti/hw/set/{student_id}/model-01/+")
        
        await client.subscribe(f"v1cdti/app/get/{student_id}/model-01/+")
        print(f"{time.ctime()} SUB topic: v1cdti/app/get/{student_id}/model-01/+")

        async for message in messages:
            m_decode = json.loads(message.payload)

            if message.topic.matches(f"v1cdti/app/get/{student_id}/model-01/"):
                await publish_message(w, client, "app", "monitor", "STATUS", w.STATE)

            if message.topic.matches(f"v1cdti/hw/set/{student_id}/model-01/{w.SERIAL}"):
                # set washing machine status
                print(f"{time.ctime()} - MQTT [{m_decode['serial']}]:{m_decode['name']} => {m_decode['value']}")
                if (m_decode['name']=="STATUS" and m_decode['value']==S_READY):
                    w.STATE = S_READY
                elif (w.STATE==S_FILLWATER and m_decode['name']=="STATUS" and m_decode['value']==S_FULLLEVELDETECTED):
                    w.STATE = S_FULLLEVELDETECTED
                    if w.Task:
                        w.Task.cancel()
                elif (m_decode['name']=="STATUS" and m_decode['value']==S_FAULT):
                    w.STATE = S_FAULT
                elif (w.STATE==S_FAULT and m_decode['name']=="STATUS" and m_decode['value']==S_FAULTCLEARED):
                    w.STATE = S_FAULTCLEARED
                elif (m_decode['name']=="STATUS" and m_decode['value']==S_OFF):
                    w.STATE = "OFF"
                w.event.set()

async def main():
    machines = 10
    wl = [WashingMachine(serial=f'SN-00{n}') for n in range(1,machines+1)]
    async with aiomqtt.Client("broker.hivemq.com") as client:
        l = [listen(w, client) for w in wl]
        c = [CoroWashingMachine(w, client) for w in wl]

        await asyncio.gather(*l , *c)
# Change to the "Selector" event loop if platform is Windows
if sys.platform.lower() == "win32" or os.name.lower() == "nt":
    from asyncio import set_event_loop_policy, WindowsSelectorEventLoopPolicy
    set_event_loop_policy(WindowsSelectorEventLoopPolicy())
# Run your async application as usual
asyncio.run(main())