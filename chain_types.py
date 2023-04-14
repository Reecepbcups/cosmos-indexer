import json
from dataclasses import dataclass


@dataclass
class BlockData:
    height: int
    block_time: str
    encoded_txs: list[str]


@dataclass
class Block:
    height: int
    time: str
    tx_ids: list[int]

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

@dataclass
class Tx:
    id: int
    height: int
    tx_amino: str
    msg_types: list[str] # JSON.load
    tx_json: str

    def to_json(self) -> str:
        return json.dumps(self.__dict__)
