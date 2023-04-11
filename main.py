"""
We subscribe to check when the latest block is updated, then we query it normally via the RPC & save it

Flow:
- Async save to JSON files (each are unique so its good)
- Then have every X blocks maybe, call an SQL method sync which takes all the saved JSON and loads it insert
- There is a LOT of disk IO with this approach. I just do not feel like making SQLite async right now
"""
# TODO: save Tx types to a table over time

import asyncio
import json
import multiprocessing
import os
import time

import httpx
import rel
import websocket

from SQL import Database
from util import (
    decode_txs,
    get_block_txs,
    get_latest_chain_height,
    get_sender,
    remove_useless_data,
)

# TODO: Save Txs & events to postgres?
# maybe a redis cache as well so other people can subscribe to redis for events?

# https://docs.tendermint.com/v0.34/rpc/
RPC_IP = "15.204.143.232:26657"  # if this is blank, we update every 6 seconds
RPC_URL = f"ws://{RPC_IP}/websocket"
RPC_ARCHIVE = "https://rpc-archive.junonetwork.io:443"

WALLET_PREFIX = "juno1"
VALOPER_PREFIX = "junovaloper1"
WALLET_LENGTH = 43
COSMOS_BINARY_FILE = "junod"

MINIMUM_DOWNLOAD_HEIGHT = 6000000  # set to -1 if you want to ignore

current_dir = os.path.dirname(os.path.realpath(__file__))

ignore = [
    "ibc.core.client.v1.MsgUpdateClient",
    "ibc.core.channel.v1.MsgAcknowledgement",
]

latest_height = -1

data_dir = os.path.join(current_dir, "data")
os.makedirs(data_dir, exist_ok=True)

blocks = os.path.join(data_dir, "blocks")
os.makedirs(blocks, exist_ok=True)

txs_dir = os.path.join(data_dir, "txs")
os.makedirs(txs_dir, exist_ok=True)

type_stats = os.path.join(data_dir, "type_stats")
os.makedirs(type_stats, exist_ok=True)

# We will just do this after we index every Tx
# users = os.path.join(data_dir, "users")
# os.makedirs(users, exist_ok=True)

errors = os.path.join(data_dir, "errors")
os.makedirs(errors, exist_ok=True)


def is_json_file(height: int) -> bool:
    return os.path.exists(os.path.join(blocks, f"{height}.json"))


import uuid

# This will be a unique number in the future in the .db itself. For now using UUIDs for async download
# unique_id = get_latest_tx_id()


def get_latest_json_height() -> int:
    files = os.listdir(blocks)

    if len(files) == 0:
        return 0

    files.sort()
    v = int(files[-1].split(".")[0])
    print(f"Latest JSON height: {v}")
    return v


def save_block_data_to_json(height: int, block_data: dict):
    # global unique_id
    # We save to JSON here so later we can move it into the .db

    # Gets unique addresses from events (users/contracts interacted with during this time frame)
    # Useful for cache solutions. So if a user does not have any changes here, then we can keep them cached longer
    # This only applies when we subscribe
    # block_events = get_block_events(block_data)
    # unique_event_addresses = get_unique_event_addresses(WALLET_PREFIX, block_events)
    # block_data["events"]["all_unique_event_addresses"] = list(unique_event_addresses)

    # Removes useless events we do not need to cache which take up lots of space
    # updated_data = remove_useless_data(block_data)

    decoded_txs = block_data["result"]["block"]["data"]["txs"]

    start_tx_id = -1

    # if unique_id == 0:
    #     # get latest unique id from the txs directory
    #     for file in os.listdir(txs_dir):
    #         if file.endswith(".json"):
    #             unique_id = int(file.split(".")[0])

    # print(unique_id)

    msg_types: dict[str, int] = {}
    tx: dict
    all_txs: list[int] = []  # ids
    for idx, tx in enumerate(decoded_txs):
        messages = tx.get("body", {}).get("messages", [])        

        for msg in messages:
            msg_type = msg.get("@type")
            if msg_type in msg_types.keys():
                msg_types[msg_type] += 1
            else:
                msg_types[msg_type] = 1

        # if ignore is in the string of the tx, continue
        if any(x in str(tx) for x in ignore):
            continue

        # unique_id = db.insert_tx(tx)

        unique_id = uuid.uuid4().int
        with open(os.path.join(txs_dir, f"{unique_id}.json"), "w") as f:
            f.write(json.dumps(tx))
            all_txs.append(unique_id)

        if start_tx_id == -1:
            start_tx_id = unique_id

        # Do this after we index everything later
        # sender = get_sender(height, messages[0], WALLET_PREFIX, VALOPER_PREFIX)
        # user_data: dict[int, int] = {}
        # if os.path.exists(os.path.join(users, f"{sender}.json")):
        #     with open(os.path.join(users, f"{sender}.json")) as f:
        #         user_data = json.load(f)
        # user_data[height] = unique_id
        # with open(os.path.join(users, f"{sender}.json"), "w") as f:
        #     json.dump(user_data, f)

    # for mtype, count in msg_types.items():
    # db.insert_type_count(mtype, count, height)
    with open(os.path.join(type_stats, f"{height}.json"), "w") as f:
        json.dump(msg_types, f)

    # count = db.get_type_count_at_height("/cosmwasm.wasm.v1.MsgExecuteContract", height)

    # db.insert_block(height, all_txs)

    with open(os.path.join(blocks, f"{height}.json"), "w") as f:
        json.dump(all_txs, f)

    # db.commit()

    print(f"Block {height}: {len(all_txs)} txs")


async def download_block(height: int):
    # Skip already downloaded height data

    # db.get_block_txs(height) != None
    if is_json_file(height):
        # if height % 100 == 0:
        print(f"Block {height} is already downloaded")
        return

    # block_data = (
    #     httpx.get(f"{RPC_ARCHIVE}/block?height={height}").json().get("result", {})
    # )

    
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{RPC_ARCHIVE}/block?height={height}")
        if r.status_code != 200:
            print(f"Error: {r.status_code} @ height {height}")
            with open(os.path.join(errors, f"{height}.json"), "w") as f:
                f.write(r.text)
            return

    # Gets block transactions, decodes them to JSON, and saves them to the block_data
    block_data: dict = r.json()
    block_txs = (
        block_data.get("result", {}).get("block", {}).get("data", {}).get("txs", [])
    )    

    decoded_txs: list[dict] = await decode_txs(COSMOS_BINARY_FILE, block_txs)

    # print(block_data)
    # exit(1)
    block_data["result"]["block"]["data"]["txs"] = decoded_txs

    save_block_data_to_json(height, block_data)
    return block_data


def on_message(ws, message):
    msg = dict(json.loads(message))

    if msg.get("result") == {}:
        print("Subscribed to New Block...")
        return

    msg_height = (
        msg.get("result", {})
        .get("data", {})
        .get("value", {})
        .get("block", {})
        .get("header", {})
        .get("height")
    )

    download_block(msg_height)


def on_error(ws, error):
    print("error", error)


def on_close(ws, close_status_code, close_msg):
    print("### closed ###")


def on_open(ws):
    print("Opened connection")
    ws.send(
        '{"jsonrpc": "2.0", "method": "subscribe", "params": ["tm.event=\'NewBlock\'"], "id": 1}'
    )
    print("Sent subscribe request")


def test_get_data():
    # tables = db.get_all_tables()
    # print(tables)
    # schema = db.get_table_schema("messages")
    # print(schema)

    # txs_in_block = db.get_block_txs(7781750)
    # print(txs_in_block)

    # tx = db.get_tx(txs_in_block[-1])
    # print(tx)

    # sender_txs = db.get_user_tx_ids("juno195mm9y35sekrjk73anw2az9lv9xs5mztvyvamt")
    # print(sender_txs)

    # sender_txs = db.get_user_txs("juno195mm9y35sekrjk73anw2az9lv9xs5mztvyvamt")
    # print(sender_txs)

    # # all_accs = db.get_all_accounts()
    # # print(all_accs)

    # count = db.get_type_count_at_height("/cosmwasm.wasm.v1.MsgExecuteContract", 7781750)
    # print(count)

    total = db.get_total_blocks()
    print("Total Blocks", total)

    init_height = 6_000_000
    end_height = 6079585

    range_count = db.get_type_count_over_range(
        "/cosmwasm.wasm.v1.MsgExecuteContract", init_height, end_height
    )
    all_range = db.get_all_count_over_range(init_height, end_height)
    print(sum(range_count))
    print(sum(all_range))

    # exit(1)
    pass


async def main():
    global latest_height

    if False and len(RPC_IP) > 0:
        websocket.enableTrace(False)  # toggle to show or hide output
        ws = websocket.WebSocketApp(
            f"{RPC_URL}",
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        ws.run_forever(
            dispatcher=rel, reconnect=5
        )  # Set dispatcher to automatic reconnection, 5 second reconnect delay if connection closed unexpectedly
        rel.signal(2, rel.abort)  # Keyboard Interrupt
        rel.dispatch()
    else:
        if False:
            test_get_data()

        # while loop, every 6 seconds query the RPC for latest and download. Try catch
        while True:
            # last_downloaded = db.get_latest_saved_block_height()

            # last_downloaded = get_latest_json_height()
            # latest_height = get_latest_chain_height(
            #     RPC_ARCHIVE=RPC_ARCHIVE, latest_saved_height=latest_height
            # )
            # block_diff = latest_height - last_downloaded

            # if block_diff > 0:
            #     print(
            #         f"Downloading blocks, latest height: {latest_height}. Behind by: {block_diff}"
            #     )

            #     if MINIMUM_DOWNLOAD_HEIGHT > 0:
            #         if last_downloaded < MINIMUM_DOWNLOAD_HEIGHT:
            #             last_downloaded = MINIMUM_DOWNLOAD_HEIGHT

            #     last_downloaded = 6_000_000
            #     latest_height = 6_000_100

            #     # pre define size since it could be >1_000_000
            #     # tasks = [None] * (block_diff + 1)
            #     tasks = []

            #     with multiprocessing.Pool(multiprocessing.cpu_count()) as pool:
            #         # for i in range(last_downloaded - 1, latest_height + 1):
            #         for i in range(last_downloaded - 1, latest_height + 1):
            #             tasks.append(asyncio.create_task(download_block(i)))

            #         print(f"Waiting to do task {len(tasks)}")
            #         await asyncio.gather(*tasks)

            start = 6_000_000
            end = 6_001_000

            grouping = 500

            # Runs through groups for downloading from the RPC
            for i in range((end - start) // grouping + 1):
                tasks = {}
                start_time = time.time()
                for j in range(grouping):
                    # block index from the grouping its in
                    block = start + i * grouping + j
                    tasks[block] = asyncio.create_task(download_block(block))                    
                
                print(f"Waiting to do # of task: {len(tasks)}")
                await asyncio.gather(*tasks.values())

                end_time = time.time()
                print(f"Finished #{len(tasks)} of tasks in {end_time - start_time} seconds")

            print("Finished")  # do a sleep here in the future
            exit(1)


# from websocket import create_connection
if __name__ == "__main__":
    # db = Database(os.path.join(current_dir, "data.db"))
    # # db.drop_all()
    # db.create_tables()

    # latest_height = db.get_latest_saved_block_height()
    latest_height = get_latest_json_height()
    print(f"Latest saved block height: {latest_height}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
    loop.close()
