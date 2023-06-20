"""
Gets validator unjails for soft or hard slashing.
"""
import json
import os
import sys

current_dir = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current_dir)
sys.path.append(parent)

from base_script import current_dir, db, earliest_block, last_tx_saved, latest_block

from option_types import TxOptions

# unique_msgs = {}
unjails = []
for i in range(1, 1_000_000):
    tx = db.get_tx_by_id(
        i,
        options=[
            TxOptions.ID,
            TxOptions.HEIGHT,
            TxOptions.MSG_TYPES,
            TxOptions.TX_JSON,
        ],
    )
    if tx is None:
        continue

    if "slashing." not in tx.msg_types:
        continue

    tx_json = tx.tx_json
    for msg in tx_json["body"]["messages"]:
        if msg["@type"] != "/cosmos.slashing.v1beta1.MsgUnjail":
            continue

        val_addr = msg["validator_addr"]
        block = tx.height
        print(f"{val_addr} was unjailed at block {block}")
        unjails.append((val_addr, block))

print(len(unjails))

# {"body": {"messages": [{"@type": "/cosmos.slashing.v1beta1.MsgUnjail", "validator_addr": "junovaloper1mkwjmcya6329eyjkswlzeshaqsuc2m5q0mn04y"}], "memo": "", "timeout_height": "0", "extension_options": [], "non_critical_extension_options": []}, "auth_info": {"signer_infos": [{"public_key": {"@type": "/cosmos.crypto.secp256k1.PubKey", "key": "A3j3UeRAXrPYBw3tR1aJSDgKdK/eqx2CyYupKIUNEpkd"}, "mode_info": {"single": {"mode": "SIGN_MODE_LEGACY_AMINO_JSON"}}, "sequence": "12"}], "fee": {"amount": [{"denom": "ujuno", "amount": "5000"}], "gas_limit": "200000", "payer": "", "granter": ""}}, "signatures": ["zyhDeoEIUHFgxqM2Fgpx57gR2xr156UlTYa3uDmip6Fx8FKgH/PvOyth9k1Um55OAuPOdORk8mAnoHuIPHxJWg=="]}
