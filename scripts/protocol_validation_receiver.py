"""Independent loopback receivers for manual protocol acceptance tests.

This module is deliberately outside the application.  It never imports its wire
encoder or decoder, and importing/constructing a receiver opens no socket.  The
IEC dependency is optional: install pyiec61850 in ``.tmp/iec_runtime_deps`` or on
the test interpreter's path.  Only ``start``/entering a context opens a listener,
always on 127.0.0.1.  Feed expanded catalog dictionaries, not protocol profiles.
"""
from __future__ import annotations

from copy import deepcopy
import base64
import ctypes
import importlib
import math
from pathlib import Path
import socket
import socketserver
import struct
import sys
import threading
import time


def _port(value: int) -> int:
    if type(value) is not int or not 0 <= value <= 65535:
        raise ValueError("Invalid local validation port")
    return value


class _IndependentState:
    def __init__(self, devices: dict, protocol: str):
        self.devices = {key: deepcopy(device) for key, device in devices.items()
                        if device.get("protocol") == protocol}
        self.state = {key: {"state": deepcopy(d.get("state", d.get("initial_state", {}))),
                            "runtime_facts": {**deepcopy(d.get("initial_runtime_facts", {})),
                                              **deepcopy(d.get("runtime_facts", {}))}}
                      for key, d in self.devices.items()}
        self.events: list[dict] = []
        self.errors: list[str] = []
        self._lock = threading.RLock()
        for identifier in self.devices:
            self._sync_derived(identifier)

    def _field_value(self, identifier: str, field: str):
        value = self.state[identifier]
        for component in field.split("."):
            if not isinstance(value, dict) or component not in value:
                raise ValueError(f"Missing explicit simulated field: {identifier}/{field}")
            value = value[component]
        if value is None:
            raise ValueError(f"Null simulated field: {identifier}/{field}")
        return value

    @staticmethod
    def _encode_enum(value, encoding, label):
        if not encoding:
            return value
        for key in (str(value), str(value).lower()):
            if key in encoding:
                return encoding[key]
        raise ValueError(f"Missing explicit value_encoding for {label}: {value!r}")

    def _sync_derived(self, identifier: str):
        for target, spec in self.devices[identifier].get("derived_runtime_facts", {}).items():
            source = self._field_value(identifier, spec["field"])
            self.state[identifier]["runtime_facts"][target] = self._encode_enum(
                source, spec.get("value_encoding", {}), spec["field"])

    def _point_value(self, identifier: str, point: dict):
        value = self._field_value(identifier, point["field"])
        encoding = point.get("value_encoding", {})
        value = self._encode_enum(value, encoding, point["field"])
        if isinstance(value, str):
            raise ValueError(f"Missing explicit value_encoding for {point['field']}: {value!r}")
        return value

    def _point_wire_value(self, identifier: str, point: dict):
        value = self._point_value(identifier, point)
        if point["data_type"] == "bool":
            if point.get("scale", 1) != 1 or type(value) is not bool:
                raise ValueError(f"Invalid boolean readpoint: {point['field']}")
            return value
        raw = value * point.get("scale", 1)
        if not math.isfinite(raw):
            raise ValueError(f"Nonfinite simulated readpoint: {point['field']}")
        fmt = {"int16": "h", "uint16": "H", "int32": "i", "uint32": "I",
               "float32": "f", "float64": "d"}[point["data_type"]]
        if fmt not in {"f", "d"}:
            if raw != int(raw):
                raise ValueError(f"Readpoint scale loses integer precision: {point['field']}")
            raw = int(raw)
        return struct.unpack(">" + fmt, struct.pack(">" + fmt, raw))[0]

    @staticmethod
    def _choose(candidates: list[tuple[str, str, dict]], value):
        matches = [(identifier, name, action) for identifier, name, action in candidates
                   if "parameter" in action or action.get("value") == value]
        if len(matches) != 1:
            raise ValueError(f"Control value {value!r} matches {len(matches)} actions")
        return matches[0]

    def _apply(self, identifier: str, action: dict, value) -> None:
        state = self.state[identifier]
        for section, fields in action.get("simulation_effects", {}).items():
            target = state.setdefault(section, {})
            for field, effect in fields.items():
                if isinstance(effect, dict):
                    if "from_parameter" in effect:
                        effect = value
                    elif "increment" in effect:
                        if field not in target:
                            raise ValueError(f"Missing pre-effect state: {identifier}/{section}.{field}")
                        effect = target[field] + effect["increment"]
                    else:
                        raise ValueError(f"Unsupported simulation effect: {effect!r}")
                target[field] = deepcopy(effect)
        self._sync_derived(identifier)


class NativeIecReceiver(_IndependentState):
    """Real libiec61850 MMS server; native callbacks are the acceptance oracle.

    ``events`` contains accepted Operate callbacks, including the exact native
    ctlVal, test flag and ctlNum.  ``checks`` records Select/Operate checks.
    Feedback attributes are updated from a separate copy of device state, using
    only the declared simulation effects.  ``errors`` must remain empty.
    """

    host = "127.0.0.1"

    def __init__(self, devices: dict, port: int = 11020):
        super().__init__(devices, "IEC61850")
        self.port = _port(port)
        self.checks: list[dict] = []
        self._model = self._server = None
        self._callbacks = []
        self._attributes = []
        self._controls = {}
        self._running = False
        self._lib = self._constants = None

    def _load_native(self) -> None:
        try:
            constants = importlib.import_module("pyiec61850.pyiec61850")
        except ImportError:
            deps = Path(__file__).resolve().parents[1] / ".tmp" / "iec_runtime_deps"
            if not deps.is_dir():
                raise RuntimeError("Optional test dependency pyiec61850 is unavailable") from None
            sys.path.insert(0, str(deps))
            constants = importlib.import_module("pyiec61850.pyiec61850")
        dll = Path(constants.__file__).with_name("iec61850.dll")
        if not dll.is_file():
            raise RuntimeError(f"Native validation dependency is missing: {dll}")
        self._constants = constants
        self._lib = ctypes.CDLL(str(dll))
        p, integer, boolean = ctypes.c_void_p, ctypes.c_int, ctypes.c_bool
        self._ControlHandler = ctypes.CFUNCTYPE(integer, p, p, p, boolean)
        self._CheckHandler = ctypes.CFUNCTYPE(integer, p, p, p, boolean, boolean)
        signatures = {
            "IedModel_create": (p, [ctypes.c_char_p]),
            "IedModel_destroy": (None, [p]),
            "LogicalDevice_createEx": (p, [ctypes.c_char_p, p, ctypes.c_char_p]),
            "LogicalNode_create": (p, [ctypes.c_char_p, p]),
            "DataObject_create": (p, [ctypes.c_char_p, p, integer]),
            "DataAttribute_create": (p, [ctypes.c_char_p, p, integer, integer,
                                          ctypes.c_uint8, integer, ctypes.c_uint32]),
            "CDC_SPC_create": (p, [ctypes.c_char_p, p, ctypes.c_uint32, ctypes.c_uint32]),
            "CDC_INC_create": (p, [ctypes.c_char_p, p, ctypes.c_uint32, ctypes.c_uint32]),
            "CDC_APC_create": (p, [ctypes.c_char_p, p, ctypes.c_uint32,
                                    ctypes.c_uint32, boolean]),
            "IedServer_create": (p, [p]),
            "IedServer_destroy": (None, [p]),
            "IedServer_setLocalIpAddress": (None, [p, ctypes.c_char_p]),
            "IedServer_start": (None, [p, integer]),
            "IedServer_stop": (None, [p]),
            "IedServer_isRunning": (boolean, [p]),
            "IedServer_setControlHandler": (None, [p, p, self._ControlHandler, p]),
            "IedServer_setPerformCheckHandler": (None, [p, p, self._CheckHandler, p]),
            "IedServer_updateBooleanAttributeValue": (None, [p, p, boolean]),
            "IedServer_updateInt32AttributeValue": (None, [p, p, ctypes.c_int32]),
            "IedServer_updateFloatAttributeValue": (None, [p, p, ctypes.c_float]),
            "MmsValue_getType": (integer, [p]),
            "MmsValue_getArraySize": (integer, [p]),
            "MmsValue_getElement": (p, [p, integer]),
            "MmsValue_getBoolean": (boolean, [p]),
            "MmsValue_toInt32": (ctypes.c_int32, [p]),
            "MmsValue_toFloat": (ctypes.c_float, [p]),
            "ControlAction_getCtlNum": (integer, [p]),
            "ControlAction_isSelect": (boolean, [p]),
        }
        for name, (result, arguments) in signatures.items():
            fn = getattr(self._lib, name)
            fn.restype, fn.argtypes = result, arguments

    @staticmethod
    def _required(pointer, label):
        if not pointer:
            raise RuntimeError(f"Native model creation failed: {label}")
        return pointer

    def _build(self) -> None:
        self._load_native()
        lib, i = self._lib, self._constants
        self._model = self._required(lib.IedModel_create(b"SIM"), "IED")
        domains, nodes, objects = {}, {}, {}

        def logical_node(domain, name):
            if domain not in domains:
                inst = f"LD{len(domains)}".encode("ascii")
                domains[domain] = self._required(lib.LogicalDevice_createEx(
                    inst, self._model, domain.encode("ascii")), domain)
                # LLN0 is mandatory in an IEC logical device, even when no
                # report/control block is needed for these local tests.
                nodes[domain, "LLN0"] = self._required(
                    lib.LogicalNode_create(b"LLN0", domains[domain]), domain + "/LLN0")
            key = (domain, name)
            if key not in nodes:
                nodes[key] = self._required(lib.LogicalNode_create(
                    name.encode("ascii"), domains[domain]), str(key))
            return nodes[key]

        models = {"direct-with-normal-security": 1, "sbo-with-normal-security": 2,
                  "direct-with-enhanced-security": 3, "sbo-with-enhanced-security": 4}
        for identifier, device in self.devices.items():
            for name, action in device.get("actions", {}).items():
                m = {**device.get("mapping", {}), **action["mapping"]}
                domain, parts = m["domain_id"], m["item_id"].split("$")
                if len(parts) != 4 or parts[1] != "CO" or parts[3] != "Oper":
                    raise ValueError(f"Unsupported control item: {m['item_id']}")
                key = (domain, parts[0], parts[2])
                signature = tuple(m.get(k) for k in ("data_type", "control_model",
                    "value_shape", "include_ctl_num", "include_oper_time",
                    "control_cancel_supported"))
                if key in self._controls:
                    entry = self._controls[key]
                    if signature != entry["signature"]:
                        raise ValueError(f"Conflicting native control definitions: {key}")
                    entry["actions"].append((identifier, name, action))
                    continue
                options = models[m["control_model"]]
                if m.get("control_cancel_supported"):
                    options |= i.CDC_CTL_MODEL_HAS_CANCEL
                if m.get("include_oper_time"):
                    options |= i.CDC_CTL_MODEL_IS_TIME_ACTIVATED
                dtype = m["data_type"]
                parent, objname = logical_node(domain, parts[0]), parts[2].encode("ascii")
                if dtype == "bool":
                    obj = lib.CDC_SPC_create(objname, parent, 0, options)
                elif dtype == "int32" and m["value_shape"] == "primitive":
                    obj = lib.CDC_INC_create(objname, parent, 0, options)
                elif dtype == "float32" and m["value_shape"] == "analogue":
                    obj = lib.CDC_APC_create(objname, parent, 0, options, False)
                else:
                    raise ValueError(f"Unsupported native control shape: {signature}")
                obj = self._required(obj, str(key))
                objects[key] = obj
                self._controls[key] = {"object": obj, "mapping": m, "signature": signature,
                                       "actions": [(identifier, name, action)]}

        for identifier, device in self.devices.items():
            for point_name, m in device.get("points", {}).items():
                if m.get("direction") != "read":
                    continue
                domain, parts = m["domain_id"], m["item_id"].split("$")
                if len(parts) < 4 or parts[1] not in {"ST", "MX"}:
                    raise ValueError(f"Unsupported native read item: {m['item_id']}")
                key = (domain, parts[0], parts[2])
                if key in self._controls:
                    raise ValueError(f"Feedback must have its own object: {key}")
                parent = logical_node(domain, parts[0])
                if key not in objects:
                    objects[key] = self._required(lib.DataObject_create(
                        parts[2].encode("ascii"), parent, 0), str(key))
                parent, path = objects[key], key
                fc = i.IEC61850_FC_ST if parts[1] == "ST" else i.IEC61850_FC_MX
                types = {"bool": i.IEC61850_BOOLEAN, "int32": i.IEC61850_INT32,
                         "float32": i.IEC61850_FLOAT32}
                dtype = m["data_type"]
                for index, component in enumerate(parts[3:]):
                    path = (*path, component)
                    final = index == len(parts[3:]) - 1
                    if path not in objects:
                        objects[path] = self._required(lib.DataAttribute_create(
                            component.encode("ascii"), parent,
                            types[dtype] if final else i.IEC61850_CONSTRUCTED,
                            fc, 0, 0, 0), str(path))
                    parent = objects[path]
                self._attributes.append((identifier, point_name, m, parent))

        self._server = self._required(lib.IedServer_create(self._model), "server")
        # libiec61850 stores this address for its server socket.  No wildcard
        # address, caller-selected host, hostname resolution, or remote dispatch.
        self._bind_address = b"127.0.0.1"
        lib.IedServer_setLocalIpAddress(self._server, self._bind_address)
        for entry in self._controls.values():
            control = self._ControlHandler(self._make_control(entry))
            check = self._CheckHandler(self._make_check(entry))
            self._callbacks.extend((control, check))
            lib.IedServer_setControlHandler(self._server, entry["object"], control, None)
            lib.IedServer_setPerformCheckHandler(self._server, entry["object"], check, None)
        self._refresh()

    def _decode_native_value(self, pointer, dtype):
        lib, i = self._lib, self._constants
        if not pointer:
            raise ValueError("Native callback ctlVal is null")
        if lib.MmsValue_getType(pointer) == i.MMS_STRUCTURE:
            if lib.MmsValue_getArraySize(pointer) != 1:
                raise ValueError("AnalogueValue must contain exactly one primitive")
            pointer = lib.MmsValue_getElement(pointer, 0)
        kind = lib.MmsValue_getType(pointer)
        if dtype == "bool" and kind == i.MMS_BOOLEAN:
            return bool(lib.MmsValue_getBoolean(pointer))
        if dtype == "int32" and kind == i.MMS_INTEGER:
            return int(lib.MmsValue_toInt32(pointer))
        if dtype == "float32" and kind == i.MMS_FLOAT:
            value = float(lib.MmsValue_toFloat(pointer))
            if math.isfinite(value):
                return value
        raise ValueError(f"Native MMS type {kind} does not match {dtype}")

    def _make_check(self, entry):
        def check(control_action, parameter, ctl_value, test, interlock):
            try:
                selected = bool(self._lib.ControlAction_isSelect(control_action))
                # Normal-security Select is an SBO read and carries no ctlVal.
                # The later Operate check still validates its concrete value.
                value = None if selected and not ctl_value else self._decode_native_value(
                    ctl_value, entry["mapping"]["data_type"])
                if value is not None:
                    self._choose(entry["actions"], value)
                with self._lock:
                    self.checks.append({"object_reference": entry["mapping"]["object_reference"],
                        "value": value, "test": bool(test), "interlock": bool(interlock),
                        "select": selected})
                return -1  # CONTROL_ACCEPTED, not ControlHandlerResult.OK
            except Exception as exc:
                self.errors.append(str(exc))
                return 3  # CONTROL_OBJECT_ACCESS_DENIED
        return check

    def _make_control(self, entry):
        def control(control_action, parameter, ctl_value, test):
            try:
                value = self._decode_native_value(ctl_value, entry["mapping"]["data_type"])
                identifier, name, action = self._choose(entry["actions"], value)
                with self._lock:
                    # IEC Test controls are accepted and observable, while the
                    # simulated physical model remains at its previous value.
                    if not test:
                        self._apply(identifier, action, value)
                    self._refresh(identifier)
                    self.events.append({"device_id": identifier, "action": name,
                        "object_reference": entry["mapping"]["object_reference"],
                        "value": value, "test": bool(test),
                        "ctlNum": int(self._lib.ControlAction_getCtlNum(control_action))})
                return 1  # CONTROL_RESULT_OK; the native server emits termination.
            except Exception as exc:
                self.errors.append(str(exc))
                return 0
        return control

    def _refresh(self, identifier=None):
        setters = {"bool": self._lib.IedServer_updateBooleanAttributeValue,
                   "int32": self._lib.IedServer_updateInt32AttributeValue,
                   "float32": self._lib.IedServer_updateFloatAttributeValue}
        for device_id, _, point, attribute in self._attributes:
            if identifier is None or identifier == device_id:
                setters[point["data_type"]](self._server, attribute,
                                            self._point_wire_value(device_id, point))

    def start(self):
        if self._running:
            return self
        if self.port == 0:
            raise ValueError("Native IEC receiver requires an explicit local port")
        try:
            self._build()
            self._lib.IedServer_start(self._server, self.port)
            self._running = bool(self._lib.IedServer_isRunning(self._server))
            if not self._running:
                raise RuntimeError(f"Native validation server could not bind 127.0.0.1:{self.port}")
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._server:
            if self._running:
                self._lib.IedServer_stop(self._server)
            self._lib.IedServer_destroy(self._server)
            self._server = None
        self._running = False
        if self._model:
            self._lib.IedModel_destroy(self._model)
            self._model = None
        # Clear callbacks only after native server threads have stopped.
        self._callbacks.clear()
        self._attributes.clear()
        self._controls.clear()

    stop = close

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, traceback):
        self.close()


_REGISTER_FORMATS = {"uint16": "H", "int16": "h", "uint32": "I", "int32": "i",
                     "float32": "f", "float64": "d"}


def _register_data(data: bytes, mapping: dict) -> bytes:
    """Convert network register bytes to/from canonical big-endian bytes."""
    words = [data[index:index + 2] for index in range(0, len(data), 2)]
    if mapping["byte_order"] == "little":
        words = [word[::-1] for word in words]
    elif mapping["byte_order"] != "big":
        raise ValueError("Unsupported register byte order")
    if mapping["word_order"] == "little":
        words.reverse()
    elif mapping["word_order"] != "big":
        raise ValueError("Unsupported register word order")
    return b"".join(words)


class ModbusReceiver(_IndependentState):
    """Small independent Modbus TCP slave with actual MBAP/PDU validation."""

    host = "127.0.0.1"

    def __init__(self, devices: dict, port: int = 11021):
        super().__init__(devices, "Modbus")
        self.port = _port(port)
        self.requests: list[dict] = []
        self._commands, self._reads = {}, {}
        self._server = self._thread = None
        self._closed = threading.Event()
        for identifier, device in self.devices.items():
            for name, action in device.get("actions", {}).items():
                m = {**device.get("mapping", {}), **action["mapping"]}
                self._commands.setdefault((m["slave_id"], m["function_code"], m["address"]),
                                          []).append((identifier, name, action))
            for name, m in device.get("points", {}).items():
                if m.get("direction") == "read":
                    self._reads.setdefault(m["slave_id"], []).append((identifier, name, m))

    @staticmethod
    def _register_count(mapping):
        return struct.calcsize(">" + _REGISTER_FORMATS[mapping["data_type"]]) // 2

    def handle_pdu(self, slave: int, pdu: bytes) -> bytes:
        """Pure in-memory PDU handling, also useful for receiver unit checks."""
        function = pdu[0] if pdu else 0
        try:
            with self._lock:
                if function in {1, 3}:
                    if len(pdu) != 5:
                        return bytes((function | 0x80, 3))
                    address, count = struct.unpack(">HH", pdu[1:])
                    if not 1 <= count <= (2000 if function == 1 else 125):
                        return bytes((function | 0x80, 3))
                    memory = {}
                    for identifier, _, point in self._reads.get(slave, []):
                        if point["function_code"] != function:
                            continue
                        value = self._point_wire_value(identifier, point)
                        if function == 1:
                            memory[point["address"]] = bool(value)
                        else:
                            fmt = _REGISTER_FORMATS[point["data_type"]]
                            data = _register_data(struct.pack(">" + fmt, value), point)
                            memory.update({point["address"] + offset // 2: data[offset:offset + 2]
                                           for offset in range(0, len(data), 2)})
                    if any(index not in memory for index in range(address, address + count)):
                        return bytes((function | 0x80, 2))
                    if function == 1:
                        data = bytearray((count + 7) // 8)
                        for index in range(count):
                            data[index // 8] |= int(memory[address + index]) << (index % 8)
                        return bytes((function, len(data))) + data
                    data = b"".join(memory[index] for index in range(address, address + count))
                    return bytes((function, len(data))) + data

                if function not in {5, 6, 16}:
                    return bytes((function | 0x80, 1))
                if function in {5, 6}:
                    if len(pdu) != 5:
                        return bytes((function | 0x80, 3))
                    address, word = struct.unpack(">HH", pdu[1:])
                    if function == 5 and word not in {0, 0xFF00}:
                        return bytes((function | 0x80, 3))
                    data = pdu[3:]
                    count = 1
                else:
                    if len(pdu) < 6:
                        return bytes((function | 0x80, 3))
                    address, count, byte_count = struct.unpack(">HHB", pdu[1:6])
                    if not 1 <= count <= 123 or byte_count != count * 2 or len(pdu) != 6 + byte_count:
                        return bytes((function | 0x80, 3))
                    data = pdu[6:]
                candidates = self._commands.get((slave, function, address), [])
                if not candidates:
                    return bytes((function | 0x80, 2))
                mapping = {**self.devices[candidates[0][0]].get("mapping", {}),
                           **candidates[0][2]["mapping"]}
                if function == 5:
                    value = word == 0xFF00
                else:
                    if count != self._register_count(mapping):
                        return bytes((function | 0x80, 3))
                    value = struct.unpack(">" + _REGISTER_FORMATS[mapping["data_type"]],
                                          _register_data(data, mapping))[0] / mapping["scale"]
                    if not math.isfinite(value):
                        return bytes((function | 0x80, 3))
                identifier, name, action = self._choose(candidates, value)
                self._apply(identifier, action, value)
                self.events.append({"device_id": identifier, "action": name, "value": value,
                                    "slave_id": slave, "address": address,
                                    "function_code": function})
                return pdu if function in {5, 6} else pdu[:5]
        except (ValueError, KeyError, struct.error) as exc:
            self.errors.append(str(exc))
            return bytes((function | 0x80, 3))

    def start(self):
        if self._server:
            return self
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(0.2)

                def exact(size):
                    result = bytearray()
                    while len(result) < size and not owner._closed.is_set():
                        try:
                            block = self.request.recv(size - len(result))
                        except socket.timeout:
                            continue
                        if not block:
                            return None
                        result.extend(block)
                    return bytes(result) if len(result) == size else None

                while not owner._closed.is_set():
                    try:
                        header = exact(7)
                        if header is None:
                            break
                        transaction, protocol, length, slave = struct.unpack(">HHHB", header)
                        if protocol != 0 or not 2 <= length <= 254:
                            break
                        pdu = exact(length - 1)
                        if pdu is None:
                            break
                        response = owner.handle_pdu(slave, pdu)
                        with owner._lock:
                            owner.requests.append({"transaction_id": transaction, "slave_id": slave,
                                                   "request": pdu.hex(), "response": response.hex()})
                        self.request.sendall(struct.pack(">HHHB", transaction, 0,
                                                         len(response) + 1, slave) + response)
                    except OSError:
                        break

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._closed.clear()
        self._server = Server(("127.0.0.1", self.port), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever,
                                         kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        return self

    def close(self):
        self._closed.set()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    stop = close

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, traceback):
        self.close()


class PacketValidationError(ValueError):
    """An independently decoded peer response did not satisfy a stage gate."""


def _require(condition, message):
    if not condition:
        raise PacketValidationError(message)


class _Ber:
    def __init__(self, tag, value, children):
        self.tag, self.value, self.children = tag, value, children


def _ber(data: bytes) -> list[_Ber]:
    """Strict, definite-length BER reader, independent of the application."""
    result, offset = [], 0
    while offset < len(data):
        start = offset
        tag = data[offset]
        offset += 1
        _require(tag & 31 != 31, "High-tag-number BER is unsupported by this validation fixture")
        _require(offset < len(data), "Truncated BER length")
        length = data[offset]
        offset += 1
        if length & 128:
            count = length & 127
            _require(0 < count <= 4 and offset + count <= len(data), "Invalid BER long length")
            length = int.from_bytes(data[offset:offset + count], "big")
            offset += count
        _require(offset + length <= len(data), "Truncated BER value")
        value = data[offset:offset + length]
        offset += length
        node = _Ber(tag, value, _ber(value) if tag & 32 else [])
        node.encoded_length = offset - start
        result.append(node)
    return result


def _one(nodes, tag):
    selected = [node for node in nodes if node.tag == tag]
    _require(len(selected) == 1, f"Expected exactly one BER tag {tag:#x}, got {len(selected)}")
    return selected[0]


def _number(node):
    _require(bool(node.value), "Empty BER integer")
    return int.from_bytes(node.value, "big", signed=True)


def _data_value(node):
    if node.tag == 0x83:
        _require(len(node.value) == 1, "Invalid MMS boolean")
        return node.value != b"\x00"
    if node.tag in {0x85, 0x86}:
        _require(bool(node.value), "Empty MMS integer")
        return int.from_bytes(node.value, "big", signed=node.tag == 0x85)
    if node.tag == 0x87:
        _require(len(node.value) == 5 and node.value[0] == 8, "Expected MMS IEEE754 float32")
        value = struct.unpack(">f", node.value[1:])[0]
        _require(math.isfinite(value), "Nonfinite MMS float")
        return value
    if node.tag == 0x8A:
        return node.value.decode("ascii")
    if node.tag == 0xA2 and len(node.children) == 1:
        return _data_value(node.children[0])
    raise PacketValidationError(f"Unsupported MMS data tag {node.tag:#x}")


def _typed_data_value(node, data_type):
    tags = {"bool": 0x83, "int16": 0x85, "int32": 0x85,
            "uint16": 0x86, "uint32": 0x86, "float32": 0x87}
    _require(data_type in tags and node.tag == tags[data_type],
             f"MMS readback type {node.tag:#x} does not match {data_type}")
    return _data_value(node)


def _equal(actual, expected):
    if type(expected) is bool:
        return type(actual) is bool and actual == expected
    if type(actual) in {int, float} and type(expected) in {int, float}:
        return math.isclose(actual, expected, rel_tol=2e-6, abs_tol=1e-5)
    return actual == expected


def _within_tolerance(actual, expected, tolerance):
    if type(expected) is bool:
        return type(actual) is bool and actual == expected
    if type(actual) in {int, float} and type(expected) in {int, float}:
        return math.isfinite(actual) and math.isfinite(expected) and abs(actual - expected) <= tolerance
    return actual == expected


def _check_readback(message, receiver, actual_wire, before):
    """Cross-check peer bytes, independent model, and exported engineering goal."""
    mapping, expectation = message["feedback_mapping"], message["readback_expectation"]
    tolerance = expectation["tolerance"]
    identifier = message["device_id"]
    actual_state = receiver._field_value(identifier, mapping["field"])
    state_wire = receiver._point_wire_value(identifier, mapping)
    _require(_within_tolerance(actual_wire, state_wire, tolerance),
             f"Readback disagrees with independent state: {actual_wire!r} != {state_wire!r}")
    test = message["protocol"] == "IEC61850" and message["parameters"]["test"]
    if test:
        # The exported physical-action expectation can still describe the
        # command's target.  Test=true must read the unchanged original state.
        expected_state, expected_wire = before, state_wire
        _require(_within_tolerance(actual_state, before, tolerance),
                 "IEC Test control changed the simulated physical state")
    else:
        expected_state, expected_wire = expectation["expected"], expectation["expected_wire_value"]
        _require(_within_tolerance(actual_state, expected_state, tolerance),
                 f"Independent resulting state disagrees with exported engineering expectation: "
                 f"{actual_state!r} != {expected_state!r}")
    _require(_within_tolerance(actual_wire, expected_wire, tolerance),
             f"Wire readback disagrees with exported expectation: {actual_wire!r} != {expected_wire!r}")
    return {"actual": actual_wire, "expected": expected_wire, "field": mapping["field"],
            "engineering_actual": actual_state, "engineering_expected": expected_state,
            "independent_wire_value": state_wire, "tolerance": tolerance,
            "physical_effects_applied": not test}


def _session_parameters(data, expected_type):
    _require(data and data[0] == expected_type, f"Expected Session SPDU {expected_type:#x}")

    def length_at(offset):
        _require(offset < len(data), "Truncated session length")
        length = data[offset]
        offset += 1
        if length == 255:
            _require(offset + 2 <= len(data), "Truncated extended session length")
            length = int.from_bytes(data[offset:offset + 2], "big")
            offset += 2
        return length, offset

    size, offset = length_at(1)
    _require(offset + size == len(data), "Session SPDU length mismatch")
    parameters = {}
    while offset < len(data):
        code = data[offset]
        size, offset = length_at(offset + 1)
        _require(offset + size <= len(data) and code not in parameters,
                 "Invalid or duplicate Session parameter")
        parameters[code] = data[offset:offset + size]
        offset += size
    return parameters


def _presentation_pdu(data, context):
    user = _one(_ber(data), 0x61)
    sequence = _one(user.children, 0x30)
    _require(_number(_one(sequence.children, 0x02)) == context,
             "Peer used a different Presentation context")
    values = _one(sequence.children, 0xA0).children
    _require(len(values) == 1, "Expected one PDU per Presentation data value")
    return values[0]


def _validate_association(tsdu, message):
    expected = next(row["expected_response"] for row in message["requests"]
                    if row["id"] == "association")
    profile = message["connection_profile"]
    parameters = _session_parameters(tsdu, 0x0E)
    _require(0xC1 in parameters, "Session ACCEPT omitted Presentation CPA")
    cpa = _one(_ber(parameters[0xC1]), 0x31)
    mode = _one(cpa.children, 0xA0)
    _require(_number(_one(mode.children, 0x80)) == 1, "Presentation normal mode was rejected")
    normal = _one(cpa.children, 0xA2)
    results = _one(normal.children, 0xA5).children
    contexts = expected["presentation_context_results"]
    _require(len(results) == len(contexts), "CPA did not return all proposed contexts")
    accepted_contexts = []
    for result, context in zip(results, contexts):
        _require(result.tag == 0x30 and _number(_one(result.children, 0x80)) == 0,
                 "Presentation context was rejected")
        _require(_one(result.children, 0x81).value == bytes.fromhex("5101"),
                 "Presentation transfer syntax is not BER")
        accepted_contexts.append(context["context_id"])
    presentation = _one(normal.children, 0x61)
    sequence = _one(presentation.children, 0x30)
    _require(_number(_one(sequence.children, 0x02)) == profile["acse_context_id"],
             "AARE arrived in the wrong Presentation context")
    aare = _one(_one(sequence.children, 0xA0).children, 0x61)
    _require(_one(_one(aare.children, 0xA1).children, 0x06).value == bytes.fromhex("28ca220203"),
             "AARE application context differs from MMS")
    _require(_number(_one(_one(aare.children, 0xA2).children, 0x02)) == 0,
             "ACSE association was rejected")
    external = _one(_one(aare.children, 0xBE).children, 0x28)
    _require(_number(_one(external.children, 0x02)) == profile["mms_context_id"],
             "MMS InitiateResponse used the wrong indirect-reference")
    initiate = _one(_one(external.children, 0xA0).children, 0xA9)
    negotiated = {}
    for key, tag in (("max_mms_pdu", 0x80), ("outstanding_calling", 0x81),
                     ("outstanding_called", 0x82), ("nesting", 0x83)):
        value = _number(_one(initiate.children, tag))
        _require(value > 0, f"Invalid negotiated {key}")
        _require(value <= profile[key], f"Peer {key} exceeds proposal; regenerate requests")
        negotiated[key] = value
    detail = _one(initiate.children, 0xA4)
    _require(_number(_one(detail.children, 0x80)) == 1, "MMS version was not accepted")
    services = _one(detail.children, 0x82).value
    _require(len(services) > 1 and services[0] <= 7, "Invalid servicesSupported bit string")
    bits = [4, 5]
    if message["parameters"]["control_model"].endswith("enhanced-security"):
        bits.append(79)
    for bit in bits:
        _require(len(services) > 1 + bit // 8 and services[1 + bit // 8] & (128 >> (bit % 8)),
                 "Peer does not support required MMS Read/Write service")
    return {**negotiated, "accepted_contexts": accepted_contexts, "aare_result": 0,
            "mms_version": 1, "read_write_supported": True}


def _cotp_parameters(tpdu):
    _require(len(tpdu) >= 7 and tpdu[0] + 1 == len(tpdu), "Invalid COTP connection TPDU length")
    params, offset = {}, 7
    while offset < len(tpdu):
        _require(offset + 2 <= len(tpdu), "Truncated COTP parameter")
        code, count = tpdu[offset:offset + 2]
        offset += 2
        _require(offset + count <= len(tpdu) and code not in params, "Invalid COTP parameter")
        params[code] = tpdu[offset:offset + count]
        offset += count
    return params


def _validate_cc(tpdu, request):
    _require(tpdu[1] == 0xD0 and tpdu[2:4] == request[4:6] and tpdu[6] == 0,
             "COTP connection was not accepted for this source reference/class")
    params, proposed = _cotp_parameters(tpdu), _cotp_parameters(request)
    for selector in (0xC1, 0xC2):
        _require(params.get(selector) == proposed.get(selector), "COTP selector mismatch")
    size = params.get(0xC0, b"")
    _require(len(size) == 1 and 7 <= size[0] <= proposed[0xC0][0], "Invalid negotiated COTP TPDU size")
    return {"destination_reference": int.from_bytes(tpdu[2:4], "big"),
            "max_tpdu_size": 1 << size[0], "selectors_matched": True}


def _termination(pdu, message):
    _require(pdu.tag == 0xA3, "Expected unconfirmed MMS InformationReport")
    report = _one(pdu.children, 0xA0)
    _require(len(report.children) == 2 and all(n.tag == 0xA0 for n in report.children),
             "Unexpected InformationReport structure")
    variables, values = report.children
    _require(len(variables.children) == len(values.children) == 1,
             "Expected exactly one CommandTermination variable/value")
    variable = _one(_one(variables.children[0].children, 0xA0).children, 0xA1)
    names = variable.children
    _require(len(names) == 2 and all(n.tag == 0x1A for n in names),
             "Termination variable is not domain-specific")
    domain, item = (node.value.decode("ascii") for node in names)
    params = message["parameters"]
    _require(domain == params["domain_id"] and item == params["item_id"],
             f"Unexpected or negative InformationReport: {domain}/{item}")
    oper = values.children[0]
    _require(oper.tag == 0xA2, "Termination access result failed")
    fields = oper.children
    offset = 2 if params["include_oper_time"] else 1
    _require(len(fields) == offset + 5, "Termination Oper structure has unexpected fields")
    value = _data_value(fields[0])
    _require(_equal(value, message["engineering_value"]), "Termination ctlVal mismatch")
    origin = fields[offset]
    _require(origin.tag == 0xA2 and len(origin.children) == 2, "Invalid termination origin")
    category = _data_value(_one(origin.children, 0x85))
    ident = _one(origin.children, 0x89).value
    _require(category == params["origin_category"] and ident == params["origin_ident"].encode("utf-8"),
             "Termination origin mismatch")
    ctl_num = _data_value(fields[offset + 1])
    _require(fields[offset + 1].tag == 0x86 and ctl_num == params["ctl_num"],
             "Termination ctlNum mismatch")
    test = _data_value(fields[offset + 3])
    _require(test == params["test"], "Termination test flag mismatch")
    return {"positive": True, "domain_id": domain, "item_id": item,
            "value": value, "origin_category": category,
            "origin_ident": ident.decode("utf-8"), "ctlNum": ctl_num, "test": test}


def _request_bytes(request):
    if isinstance(request.get("bytes"), bytes):
        return request["bytes"]
    return base64.b64decode(request["base64"], validate=True)


def _outgoing_tsdu(raw, maximum):
    """Reassemble actual archived request bytes, checking negotiated TPDU size."""
    offset, data, ended = 0, bytearray(), False
    while offset < len(raw):
        _require(not ended and offset + 7 <= len(raw), "Invalid outgoing TPKT segmentation")
        header = raw[offset:offset + 4]
        size = int.from_bytes(header[2:4], "big")
        _require(header[:2] == b"\x03\x00" and size >= 7 and offset + size <= len(raw),
                 "Invalid outgoing TPKT frame length")
        tpdu = raw[offset + 4:offset + size]
        _require(len(tpdu) <= maximum and tpdu[:2] == b"\x02\xf0"
                 and tpdu[2] & 0x7F == 0, "Outgoing TPDU exceeds negotiation or is not COTP data")
        data.extend(tpdu[3:])
        ended = bool(tpdu[2] & 0x80)
        offset += size
    _require(ended, "Outgoing segmented TSDU lacks the final EOT flag")
    return bytes(data)


def _reset_snapshot(receiver, snapshot, identifier):
    if snapshot is None:
        return
    rows = snapshot.get("devices", [])
    indexed = rows if isinstance(rows, dict) else {row["device_id"]: row for row in rows}
    _require(identifier in indexed, "Snapshot does not contain the message target")
    with receiver._lock:
        for device_id, row in indexed.items():
            if device_id in receiver.state:
                receiver.state[device_id] = {"state": deepcopy(row["state"]),
                    "runtime_facts": {**deepcopy(receiver.devices[device_id].get("initial_runtime_facts", {})),
                                      **deepcopy(row.get("runtime_facts", {}))}}
                receiver._sync_derived(device_id)
        if isinstance(receiver, NativeIecReceiver):
            _require(receiver._server is not None, "Native receiver is not started")
            receiver._refresh()


def validate_packet_bundle(message: dict, receiver, snapshot=None, *, test_branch="main",
                           timeout=5.0) -> dict:
    """Send an archived API bundle only to the supplied local test receiver.

    No application encoder/decoder is used.  Every stage advances only after an
    independently parsed positive peer response.  Enhanced controls also wait
    for matching positive CommandTermination, regardless of response order.
    The returned JSON-compatible evidence includes all actual wire frames;
    failures have ``accepted=False`` and an explicit ``failure``.  ``cancel``
    tests selection then cancellation without Operate; ``release`` additionally
    exercises the optional release plan after normal control/readback.
    """
    result = {"accepted": False, "protocol": message.get("protocol"),
              "device_id": message.get("device_id"), "action": message.get("action"),
              "branch": test_branch, "checks": [], "packets": [], "events": [], "notes": []}
    event_start, error_start = len(receiver.events), len(receiver.errors)
    current_stage = "preflight"
    try:
        _require(test_branch in {"main", "cancel", "release"}, "Unsupported validation branch")
        _require(receiver.host == "127.0.0.1" and 0 < receiver.port <= 65535,
                 "Validation receiver must listen on an explicit IPv4 loopback port")
        identifier = message["device_id"]
        _require(identifier in receiver.devices, "Target does not exist in independent receiver")
        _require(message["protocol"] in {"IEC61850", "Modbus"}, "Unsupported bundle protocol")
        iec = message["protocol"] == "IEC61850"
        _require(iec or test_branch == "main", "Optional cancel/release stages are IEC-only")
        _require(isinstance(receiver, NativeIecReceiver if iec else ModbusReceiver),
                 "Protocol does not match the supplied independent receiver")
        _reset_snapshot(receiver, snapshot, identifier)
        before_state = deepcopy(receiver.state[identifier])
        before_field = receiver._field_value(identifier, message["feedback_mapping"]["field"])
        if test_branch != "cancel":
            expectation = message.get("readback_expectation")
            _require(isinstance(expectation, dict), "Bundle lacks explicit readback_expectation")
            _require({"field", "before", "expected", "expected_wire_value", "data_type", "tolerance"}
                     <= expectation.keys(), "Exported readback expectation is incomplete")
            _require(expectation["field"] == message["feedback_mapping"]["field"]
                     and expectation["data_type"] == message["feedback_mapping"]["data_type"],
                     "Readback expectation refers to a different field or type")
            tolerance = expectation["tolerance"]
            _require(type(tolerance) in {int, float} and math.isfinite(tolerance) and tolerance >= 0,
                     "Readback tolerance must be an explicit finite nonnegative number")
            _require(_within_tolerance(before_field, expectation["before"], tolerance),
                     "Exported feedback original value disagrees with independent snapshot")
        if test_branch == "cancel":
            _require(iec and message["parameters"]["control_model"].startswith("sbo-"),
                     "Cancel validation requires a pending SBO selection")
            stages = [r for r in message["requests"] if r["id"] in
                      {"cotp_connect", "association", "select", "cancel"}]
            _require([r["id"] for r in stages] == ["cotp_connect", "association", "select", "cancel"],
                     "Bundle lacks the complete selection/cancel branch")
        else:
            stages = [r for r in message["requests"] if r["branch"] == "main"
                      or (test_branch == "release" and r["branch"] == "release")]
        completed = {"tcp_connected"}
        termination = None
        negotiated = None
        with socket.create_connection(("127.0.0.1", receiver.port), timeout=timeout) as sock:
            _require(sock.getpeername()[0] == "127.0.0.1", "Connected peer is not IPv4 loopback")

            def exact(count):
                data = bytearray()
                while len(data) < count:
                    block = sock.recv(count - len(data))
                    if not block:
                        if data:
                            raise PacketValidationError("Peer closed a truncated frame")
                        raise EOFError("Peer closed transport")
                    data.extend(block)
                return bytes(data)

            def receive_tsdu():
                data = bytearray()
                while True:
                    header = exact(4)
                    size = int.from_bytes(header[2:4], "big")
                    _require(header[:2] == b"\x03\x00" and 7 <= size <= 65535, "Invalid peer TPKT header")
                    raw = header + exact(size - 4)
                    result["packets"].append({"direction": "receive", "stage": current_stage,
                                               "hex": raw.hex(" "), "byte_length": len(raw)})
                    tpdu = raw[4:]
                    if tpdu[1] != 0xF0:
                        _require(not data, "Non-data COTP TPDU interrupted segmentation")
                        return tpdu
                    _require(tpdu[0] == 2 and tpdu[2] & 0x7F == 0, "Invalid COTP data TPDU")
                    data.extend(tpdu[3:])
                    if tpdu[2] & 0x80:
                        return bytes(data)

            for request in stages:
                current_stage = request["id"]
                required = set(request.get("requires", []))
                _require(required <= completed, f"Unsatisfied response gates for {current_stage}: {required-completed}")
                raw = _request_bytes(request)
                result["packets"].append({"direction": "send", "stage": current_stage,
                                           "hex": raw.hex(" "), "byte_length": len(raw)})
                if iec and current_stage != "cotp_connect":
                    tsdu = _outgoing_tsdu(raw, result["cotp"]["max_tpdu_size"])
                    if negotiated and current_stage != "association_release":
                        _require(tsdu.startswith(b"\x01\x00\x01\x00"),
                                 "Outgoing MMS request lacks Session DATA TRANSFER")
                        pdu = _presentation_pdu(tsdu[4:], message["parameters"]["presentation_context_id"])
                        _require(pdu.encoded_length <= negotiated["max_mms_pdu"],
                                 "Actual request bytes exceed negotiated MMS PDU limit")
                try:
                    sock.sendall(raw)
                except (ConnectionResetError, BrokenPipeError):
                    if current_stage == "association_release" and "mms_conclude" in completed:
                        result["notes"].append("Native peer already closed transport after accepted MMS Conclude")
                        break
                    raise
                if not iec:
                    header = exact(7)
                    transaction, protocol, size, unit = struct.unpack(">HHHB", header)
                    _require(protocol == 0 and 2 <= size <= 254, "Invalid peer Modbus MBAP")
                    pdu = exact(size - 1)
                    result["packets"].append({"direction": "receive", "stage": current_stage,
                        "hex": (header + pdu).hex(" "), "byte_length": 7 + len(pdu)})
                    expected = request["expected_response"]
                    _require(transaction == expected["transaction_id"] and unit == expected["unit_id"],
                             "Modbus transaction/unit mismatch")
                    _require(pdu[0] == expected["function_code"], "Modbus function mismatch or exception")
                    if current_stage == "operate":
                        _require(pdu == raw[7:] if pdu[0] in {5, 6} else pdu == raw[7:12],
                                 "Modbus write acknowledgement does not echo address/value/count")
                    elif current_stage == "readback":
                        _require(len(pdu) >= 3 and len(pdu) == pdu[1] + 2,
                                 "Modbus read response byte count mismatch")
                        mapping = message["feedback_mapping"]
                        if pdu[0] == 1:
                            _require(len(pdu) == 3, "Expected exactly one feedback coil byte")
                            actual_wire = bool(pdu[2] & 1)
                        else:
                            fmt = _REGISTER_FORMATS[mapping["data_type"]]
                            _require(len(pdu[2:]) == struct.calcsize(">" + fmt), "Modbus feedback register count mismatch")
                            actual_wire = struct.unpack(">" + fmt, _register_data(pdu[2:], mapping))[0]
                        result["readback"] = _check_readback(message, receiver, actual_wire, before_field)
                elif current_stage == "cotp_connect":
                    result["cotp"] = _validate_cc(receive_tsdu(), raw[4:])
                elif current_stage == "association":
                    negotiated = _validate_association(receive_tsdu(), message)
                    result["association"] = negotiated
                elif current_stage in {"select", "operate", "readback", "cancel"}:
                    expected = request["expected_response"]
                    need_termination = bool(expected.get("require_command_termination"))
                    confirmed, deadline = None, time.monotonic() + timeout
                    while confirmed is None or (need_termination and termination is None):
                        remaining = deadline - time.monotonic()
                        _require(remaining > 0, "Timed out waiting for matching MMS response/termination")
                        sock.settimeout(remaining)
                        tsdu = receive_tsdu()
                        _require(tsdu.startswith(b"\x01\x00\x01\x00"), "Expected Session DATA TRANSFER")
                        pdu = _presentation_pdu(tsdu[4:], message["parameters"]["presentation_context_id"])
                        if pdu.tag == 0xA3:
                            _require(current_stage == "operate" and need_termination,
                                     "Unexpected InformationReport outside enhanced Operate")
                            termination = _termination(pdu, message)
                            result["command_termination"] = termination
                            continue
                        _require(pdu.tag == 0xA1, f"MMS confirmed error/reject or unexpected PDU {pdu.tag:#x}")
                        invoke = _number(_one(pdu.children, 0x02))
                        _require(invoke == expected["invoke_id"], "MMS invoke ID mismatch; response cannot advance this stage")
                        _require(confirmed is None, "Duplicate confirmed MMS response")
                        service_tag = 0xA4 if expected["service"] == "MMS ReadResponse" else 0xA5
                        service = _one(pdu.children, service_tag)
                        if service_tag == 0xA5:
                            _require(len(service.children) == 1 and service.children[0].tag == 0x81
                                     and not service.children[0].value, "MMS Write access result failed")
                            confirmed = {"invoke_id": invoke, "write_success": True}
                        else:
                            values = _one(service.children, 0xA1).children
                            _require(len(values) == 1, "Expected one MMS read access result")
                            if current_stage == "select":
                                actual = _data_value(values[0])
                                _require(type(actual) is str and bool(actual), "Normal-security SBO returned an empty selection")
                                confirmed = {"invoke_id": invoke, "selection": actual}
                            else:
                                mapping = message["feedback_mapping"]
                                actual = _typed_data_value(values[0], mapping["data_type"])
                                result["readback"] = _check_readback(message, receiver, actual, before_field)
                                confirmed = {"invoke_id": invoke, "read_success": True}
                    sock.settimeout(timeout)
                    result["checks"].append({"stage": current_stage, **confirmed})
                elif current_stage == "mms_conclude":
                    try:
                        tsdu = receive_tsdu()
                    except (EOFError, ConnectionResetError):
                        result["notes"].append("Native peer closed transport after MMS Conclude")
                        completed.add(current_stage)
                        break
                    _require(tsdu.startswith(b"\x01\x00\x01\x00"), "Expected Session DATA for ConcludeResponse")
                    pdu = _presentation_pdu(tsdu[4:], message["parameters"]["presentation_context_id"])
                    _require(pdu.tag == 0x8C and not pdu.value, "MMS Conclude was rejected")
                elif current_stage == "association_release":
                    try:
                        tsdu = receive_tsdu()
                    except (EOFError, ConnectionResetError):
                        result["notes"].append("Native peer closed transport after accepted MMS Conclude")
                        completed.add(current_stage)
                        break
                    release = _session_parameters(tsdu, 0x0A)
                    _require(0xC1 in release and _presentation_pdu(release[0xC1],
                        message["connection_profile"]["acse_context_id"]).tag == 0x63,
                        "Peer omitted normal ACSE release response")
                else:
                    raise PacketValidationError(f"Unknown bundle stage {current_stage}")
                completed.add(current_stage)
                if current_stage == "operate":
                    completed.add("operate_response_success")
                if current_stage in {"cotp_connect", "association", "mms_conclude", "association_release"}:
                    result["checks"].append({"stage": current_stage, "accepted": True})
        result["events"] = deepcopy(receiver.events[event_start:])
        _require(not receiver.errors[error_start:], f"Receiver errors: {receiver.errors[error_start:]}")
        if test_branch == "cancel":
            _require("cancel" in completed and not result["events"], "Cancel executed a control or lacked a positive acknowledgement")
        else:
            _require("readback" in completed, "Bundle did not complete feedback readback")
            _require(len(result["events"]) == 1, "Expected exactly one native accepted-control event")
            event = result["events"][0]
            _require(event["device_id"] == identifier and event["action"] == message["action"]
                     and _equal(event["value"], message["engineering_value"]),
                     "Receiver accepted a different target/action/control value")
            if iec:
                _require(event["test"] == message["parameters"]["test"]
                         and event["ctlNum"] == message["parameters"]["ctl_num"],
                         "Native callback test/ctlNum mismatch")
                if message["parameters"]["test"]:
                    _require(receiver.state[identifier] == before_state,
                             "IEC Test control changed independent simulated state")
        result["accepted"] = True
    except Exception as exc:
        result["failure"] = f"{current_stage}: {exc}"
        result["error_type"] = type(exc).__name__
        result["events"] = deepcopy(receiver.events[event_start:])
    return result
