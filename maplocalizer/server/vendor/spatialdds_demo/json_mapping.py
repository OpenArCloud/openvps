"""
Typed SpatialDDS samples <-> JSON dicts.

This is the seam the envelope used to occupy. The envelope put JSON on the bus;
this puts JSON only where JSON is actually needed — the web bridge's WebSocket
clients, MQTT payloads, MCAP records, the HTTP discovery surface — while the
bus carries real types.

Rules, so a browser sees the same JSON it always did:

* **Enums are identifier strings** (§2.8), not integers: ``"VPS"``, ``"ENU"``.
* **Fields use their IDL names.** idlc renames fields that collide with Python
  keywords (``global`` -> ``_global``, ``from`` -> ``_from``); the generated
  ``_field_aliases`` map puts the spec's name back.
* **Bytes are base64**, since JSON has no byte string.
* Presence-flagged optionals stay as-is: the spec models them with an explicit
  ``has_x`` boolean beside a value, so the value is never null and is emitted
  whatever the flag says. Consumers read the flag, exactly as on the wire.
"""

from __future__ import annotations

import base64
import dataclasses
import enum
from typing import Any, Dict, Type, TypeVar, get_args, get_origin

from spatialdds_idl._field_aliases import FIELD_ALIASES

T = TypeVar("T")


def _typename(obj_or_cls: Any) -> str:
    cls = obj_or_cls if isinstance(obj_or_cls, type) else type(obj_or_cls)
    idl = getattr(cls, "__idl__", None)
    name = getattr(idl, "idl_transformed_typename", None)
    if name:
        return name.replace("::", ".")
    return f"{cls.__module__}.{cls.__qualname__}"


def _wire_name(typename: str, attr: str) -> str:
    return FIELD_ALIASES.get(typename, {}).get(attr, attr)


def _python_name(typename: str, wire: str) -> str:
    for py, name in FIELD_ALIASES.get(typename, {}).items():
        if name == wire:
            return py
    return wire


def to_json(value: Any) -> Any:
    """One typed sample (or any nested value) as JSON-safe data."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.name                      # §2.8: identifiers, not ints
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items()}
    if dataclasses.is_dataclass(value):
        typename = _typename(value)
        out: Dict[str, Any] = {}
        for field in dataclasses.fields(value):
            out[_wire_name(typename, field.name)] = to_json(getattr(value, field.name))
        return out
    if _is_union(value):
        # A union is one active case. Emit the discriminator by name and the
        # active member under its own name, so the JSON says which case it is
        # rather than leaking cyclonedds' private __active bookkeeping.
        active = getattr(value, "_IdlUnion__active", None)
        return {
            "discriminator": to_json(value.discriminator),
            **({active: to_json(value.value)} if active else {}),
        }
    if hasattr(value, "__dict__"):
        return {k: to_json(v) for k, v in vars(value).items() if not k.startswith("_")}
    return value


def _is_union(value: Any) -> bool:
    try:
        import cyclonedds.idl as idl
        return isinstance(value, idl.IdlUnion)
    except Exception:
        return False


def _unwrap(target: Any) -> Any:
    """
    Strip cyclonedds' ``typedef`` wrappers.

    The generator emits IDL typedefs as ``typedef[alias, real_type]``, so a
    field declared ``Aabb3 aabb`` resolves to a typedef whose ``.subtype`` is
    the dataclass. Sequences likewise wrap their element type.
    """
    seen = 0
    while hasattr(target, "subtype") and seen < 8:
        target = target.subtype
        seen += 1
    return target


def _coerce(target: Any, raw: Any) -> Any:
    """Build ``raw`` into ``target``, following the generated type hints."""
    if target is None or raw is None:
        return raw

    target = _unwrap(target)
    if isinstance(raw, list) and not isinstance(target, type):
        # sequence[X] / array[X, n]: element type is the unwrapped subtype.
        return [_coerce(target, item) for item in raw]

    origin = get_origin(target)
    if origin in (list, tuple):
        args = get_args(target) or ()
        item_type = args[0] if args else None
        return [_coerce(item_type, item) for item in raw]

    if isinstance(raw, list):
        return [_coerce(target, item) for item in raw]

    if isinstance(target, type):
        if issubclass(target, enum.Enum):
            # Accept the identifier the spec puts on the wire, and tolerate the
            # integer a hand-rolled client might send.
            if isinstance(raw, str):
                return target[raw]
            return target(raw)
        if issubclass(target, (bytes, bytearray)) and isinstance(raw, str):
            return base64.b64decode(raw)
        if dataclasses.is_dataclass(target) and isinstance(raw, dict):
            return from_json(target, raw)
        if isinstance(raw, dict) and _is_union_type(target):
            return _union_from_json(target, raw)
        if isinstance(raw, str) and _is_union_type(target):
            # Shorthand: just the discriminator, e.g. "COV_NONE". The Cesium
            # client and the demo's own builders have always written covariance
            # this way, and it is unambiguous — the discriminator selects the
            # case, and an empty case has nothing else to carry. Accepted at
            # the edge; to_json always emits the explicit form.
            return _union_from_discriminator(target, raw)
    return raw


def _union_from_discriminator(cls: Type[T], label: str) -> T:
    """Build a union from a bare discriminator name, defaulting the payload."""
    for member, hint in _resolved_hints(cls).items():
        labels = getattr(hint, "labels", None) or []
        if any(getattr(v, "name", None) == label for v in labels):
            subtype = _unwrap(getattr(hint, "subtype", None))
            default = 0 if subtype in (int, float) else 0
            return cls(**{member: default})
    raise ValueError(
        f"{_typename(cls)}: {label!r} is not one of its discriminator labels"
    )


def _is_union_type(target: Any) -> bool:
    try:
        import cyclonedds.idl as idl
        return isinstance(target, type) and issubclass(target, idl.IdlUnion)
    except Exception:
        return False


def _union_from_json(cls: Type[T], data: Dict[str, Any]) -> T:
    """
    Rebuild a union from ``{"discriminator": name, "<case>": value}``.

    An unrecognised case name is refused. cyclonedds accepts one silently and
    yields a union with no active case, which serialises to
    ``{"discriminator": None}`` — a sample that is not valid and that nothing
    downstream can tell from a legitimately-empty one. That cost a real bug:
    the ROS 2 bridge wrote a covariance under an invented case name and the
    value simply disappeared.
    """
    hints = _resolved_hints(cls)
    case = next((k for k in data if k != "discriminator"), None)
    if case is None:
        # Discriminator alone: an empty case (COV_NONE and friends) is a
        # legitimate way to write one.
        label = data.get("discriminator")
        if isinstance(label, str):
            return _union_from_discriminator(cls, label)
        raise ValueError(f"{_typename(cls)}: union JSON names no active case")
    if case not in hints:
        raise ValueError(
            f"{_typename(cls)}: {case!r} is not one of its cases "
            f"({', '.join(sorted(hints))})"
        )
    return cls(**{case: _coerce(_case_type(hints.get(case)), data[case])})


def _case_type(hint: Any) -> Any:
    """types.case[[labels], X] carries the member type as its subtype."""
    return _unwrap(hint)


def from_json(cls: Type[T], data: Dict[str, Any]) -> T:
    """
    Rebuild a typed sample from JSON.

    Missing fields raise rather than defaulting: a partially-populated struct
    on the bus is worse than a clear failure at the edge, and the spec's
    presence-flag pattern means "unused" fields still carry a value.
    """
    if not isinstance(data, dict):
        raise TypeError(f"{cls.__name__} expects an object, got {type(data).__name__}")
    if _is_union_type(cls):
        # A union is not a dataclass, so it cannot go through the field walk
        # below. Handling it here means a caller need not know which of the
        # two a given generated class is.
        return _union_from_json(cls, data)

    typename = _typename(cls)
    hints = getattr(cls, "__annotations__", {}) or {}
    resolved = _resolved_hints(cls)
    kwargs: Dict[str, Any] = {}
    missing = []
    for field in dataclasses.fields(cls):
        wire = _wire_name(typename, field.name)
        if wire in data:
            raw = data[wire]
        elif field.name in data:                # tolerate the python-side name
            raw = data[field.name]
        else:
            missing.append(wire)
            continue
        kwargs[field.name] = _coerce(resolved.get(field.name, hints.get(field.name)), raw)
    if missing:
        raise ValueError(f"{typename}: missing field(s) {', '.join(sorted(missing))}")
    return cls(**kwargs)


def _resolved_hints(cls: Type) -> Dict[str, Any]:
    """
    Real classes for each field, resolving the generated quoted forward refs.

    cyclonedds already resolves these to build its serializer, so we reuse that
    rather than re-implementing string resolution.
    """
    try:
        from cyclonedds.idl._type_normalize import get_extended_type_hints
        return dict(get_extended_type_hints(cls))
    except Exception:
        return {}
