"""Frozen recovery boundary. Updating this module or its trust key requires UF2."""
import json
import os
import sys

import ota_protocol as protocol

BASE = "/ota"
STATE = BASE + "/state.json"
state = None
slot = None
root_hash = None
script_hashes = None


def sync():
    if hasattr(os, "sync"):
        os.sync()


def write_state(value):
    with open(STATE + ".tmp", "w") as f:
        json.dump(value, f)
    sync()
    os.rename(STATE + ".tmp", STATE)
    sync()


def read_state():
    with open(STATE) as f:
        value = json.load(f)
    if value.get("active") not in ("a", "b"):
        raise ValueError("Invalid OTA state")
    if value.get("pending") not in (None, "a", "b"):
        raise ValueError("Invalid pending slot")
    if value.get("pending") == value["active"]:
        raise ValueError("Pending slot is active")
    return value


def verified_manifest(directory):
    import ota_verify
    with open(directory + "/manifest.json", "rb") as f:
        raw = f.read(protocol.MAX_MANIFEST + 1)
    with open(directory + "/manifest.sig", "rb") as f:
        signature = f.read(81)
    if len(raw) > protocol.MAX_MANIFEST or not ota_verify.verify(raw, signature):
        raise ValueError("Invalid package signature")
    manifest = json.loads(raw)
    hashes = protocol.validate_manifest(manifest)
    if (sys.implementation._mpy & 255) != manifest["mpy_version"]:
        raise ValueError("Incompatible bytecode runtime")
    return manifest, hashes


def select():
    global state, slot, root_hash, script_hashes
    state = read_state()
    pending = state.get("pending")
    if pending and state.get("attempted"):
        state["rejected"] = state.get("pending_root")
        state.pop("pending", None)
        state.pop("pending_root", None)
        state.pop("attempted", None)
        write_state(state)
        pending = None
    if pending:
        # Persist BEFORE importing anything from the trial package.
        state["attempted"] = True
        write_state(state)
    slot = pending or state["active"]
    manifest, script_hashes = verified_manifest(BASE + "/" + slot)
    root_hash = manifest["root"]
    # Metadata is derived from the signed manifest, never executed from network.
    with open(BASE + "/" + slot + "/hashes.py") as f:
        if f.read() != protocol.hashes_source(root_hash, script_hashes):
            raise ValueError("Invalid local hash metadata")
    directory = BASE + "/" + slot
    sys.path.insert(0, directory + "/lib")
    sys.path.insert(0, directory)
    return slot


def confirm():
    if state and state.get("pending") == slot and state.get("attempted"):
        state["active"] = slot
        state.pop("pending", None)
        state.pop("pending_root", None)
        state.pop("attempted", None)
        write_state(state)


def stage(target, root):
    value = dict(state)
    value["pending"] = target
    value["pending_root"] = root
    value.pop("attempted", None)
    write_state(value)
    state.update(value)


def reset_if_pending():
    # Battery sleep cuts power. On USB, sleep returns and needs a fresh VM.
    if state and state.get("pending"):
        import machine
        machine.reset()


def run():
    try:
        select()
        __import__("launcher")
    except Exception as error:
        print("Launcher failed:", error)
        if state and state.get("pending"):
            import machine
            machine.reset()
        raise
