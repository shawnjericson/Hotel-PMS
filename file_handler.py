"""JSON persistence for rooms, active rentals, and revenue history."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from models import (
    Customer,
    RentalRecord,
    RevenueRecord,
    Room,
    RoomChargeLine,
    RoomPriceSnapshot,
    RoomStatus,
    RoomTransferRecord,
    StandardRoom,
    VIPRoom,
)


DATA_FILE = Path(__file__).with_name("khachsan_data.json")
SCHEMA_VERSION = 2


class DataFileError(Exception):
    """Raised when persisted hotel data cannot be read or validated."""


def save_data(
    rooms: Iterable[Room],
    rentals: Iterable[RentalRecord],
    revenue_history: Iterable[RevenueRecord] = (),
    file_path: str | Path = DATA_FILE,
) -> None:
    """Save all application state atomically to a UTF-8 JSON file."""

    destination = Path(file_path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "rooms": [room.to_dict() for room in rooms],
        "active_rentals": [rental.to_dict() for rental in rentals],
        "revenue_history": [record.to_dict() for record in revenue_history],
    }

    temporary_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        temporary_path.replace(destination)
    except OSError as error:
        raise DataFileError(f"Unable to save data to {destination}: {error}") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                # Cleanup must not replace the original, controlled save error.
                pass


def load_data(
    file_path: str | Path = DATA_FILE,
) -> tuple[list[Room], list[RentalRecord], list[RevenueRecord]]:
    """Load saved state, returning empty lists when the file does not exist."""

    source = Path(file_path)
    if not source.exists():
        return [], [], []

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("The JSON root must be an object.")
        schema_version = _schema_version(payload)
        room_items = _object_list(payload.get("rooms", []), "Rooms")
        rental_items = _object_list(
            payload.get("active_rentals", []),
            "Active rentals",
        )
        revenue_items = _object_list(
            payload.get("revenue_history", []),
            "Revenue history",
        )
        rooms = [_room_from_dict(item) for item in room_items]
        room_by_id = _index_rooms(rooms)
        rentals = [
            _rental_from_dict(item, room_by_id, schema_version)
            for item in rental_items
        ]
        revenue_history = [
            _revenue_from_dict(item, schema_version)
            for item in revenue_items
        ]
        _validate_loaded_state(rooms, rentals)
        return rooms, rentals, revenue_history
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise DataFileError(f"Invalid data file {source}: {error}") from error


def _schema_version(payload: dict[str, object]) -> int:
    """Return the supported schema version; missing means the legacy v1 shape."""

    version = payload.get("schema_version", 1)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("Schema version must be an integer.")
    if version not in {1, SCHEMA_VERSION}:
        raise ValueError(
            f"Unsupported schema version {version}; expected 1 or {SCHEMA_VERSION}."
        )
    return version


def _object_list(value: object, field_name: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list.")
    if any(not isinstance(item, dict) for item in value):
        raise TypeError(f"Every item in {field_name.lower()} must be an object.")
    return value


def _room_from_dict(data: dict[str, object]) -> Room:
    common = {
        "room_id": str(data["room_id"]),
        "room_name": str(data["room_name"]),
        "base_price": str(data["base_price"]),
        "status": RoomStatus(str(data["status"])),
    }
    room_type = str(data["room_type"])
    if room_type == StandardRoom.room_type:
        return StandardRoom(**common)
    if room_type == VIPRoom.room_type:
        return VIPRoom(
            **common,
            cleaning_fee=str(data["cleaning_fee"]),
            minibar_fee=str(data["minibar_fee"]),
        )
    raise ValueError(f"Unknown room type: {room_type}")


def _index_rooms(rooms: list[Room]) -> dict[str, Room]:
    room_by_id: dict[str, Room] = {}
    for room in rooms:
        if room.room_id in room_by_id:
            raise ValueError(f"Duplicate room ID: {room.room_id}")
        room_by_id[room.room_id] = room
    return room_by_id


def _rental_from_dict(
    data: dict[str, object],
    room_by_id: dict[str, Room],
    schema_version: int,
) -> RentalRecord:
    room_id = str(data["room_id"])
    if room_id not in room_by_id:
        raise ValueError(f"Rental references missing room: {room_id}")
    customer_data = data["customer"]
    if not isinstance(customer_data, dict):
        raise TypeError("Rental customer must be an object.")
    customer = Customer(
        customer_id=str(customer_data["customer_id"]),
        name=str(customer_data["name"]),
        identity_number=str(customer_data["identity_number"]),
    )
    snapshot_data = _versioned_value(
        data,
        "current_price_snapshot",
        None,
        schema_version,
    )
    if snapshot_data is None:
        if schema_version == SCHEMA_VERSION:
            raise TypeError("Current price snapshot must be an object.")
        current_price_snapshot = None
    elif isinstance(snapshot_data, dict):
        current_price_snapshot = _price_snapshot_from_dict(snapshot_data)
    else:
        raise TypeError("Current price snapshot must be an object.")

    charge_history = tuple(
        _charge_line_from_dict(item)
        for item in _object_list(
            _versioned_value(data, "charge_history", [], schema_version),
            "Charge history",
        )
    )
    transfer_history = tuple(
        _transfer_record_from_dict(item)
        for item in _object_list(
            _versioned_value(data, "transfer_history", [], schema_version),
            "Transfer history",
        )
    )
    return RentalRecord(
        rental_id=str(data["rental_id"]),
        customer=customer,
        room=room_by_id[room_id],
        rental_days=_positive_integer(data["rental_days"], "Rental days"),
        booked_at=str(data["booked_at"]),
        current_price_snapshot=current_price_snapshot,
        security_deposit=str(
            _versioned_value(data, "security_deposit", "0.00", schema_version)
        ),
        charge_history=charge_history,
        transfer_history=transfer_history,
    )


def _revenue_from_dict(
    data: dict[str, object],
    schema_version: int,
) -> RevenueRecord:
    total_amount = str(data["total_amount"])
    stay_charge = str(
        _versioned_value(data, "stay_charge", total_amount, schema_version)
    )
    return RevenueRecord(
        rental_id=str(data["rental_id"]),
        room_id=str(data["room_id"]),
        room_name=str(data["room_name"]),
        room_type=str(data["room_type"]),
        customer_id=str(data["customer_id"]),
        customer_name=str(data["customer_name"]),
        identity_number=str(data["identity_number"]),
        rental_days=_positive_integer(data["rental_days"], "Rental days"),
        total_amount=total_amount,
        checked_out_at=str(data["checked_out_at"]),
        stay_charge=stay_charge,
        damage_charge=str(
            _versioned_value(data, "damage_charge", "0.00", schema_version)
        ),
        # Older v1/v2 records never stored this evidence; do not invent a reason.
        damage_reason=data.get("damage_reason"),
        security_deposit=str(
            _versioned_value(data, "security_deposit", "0.00", schema_version)
        ),
        deposit_deduction=str(
            _versioned_value(data, "deposit_deduction", "0.00", schema_version)
        ),
        deposit_refund=str(
            _versioned_value(data, "deposit_refund", "0.00", schema_version)
        ),
        amount_collected_at_checkout=str(
            _versioned_value(
                data,
                "amount_collected_at_checkout",
                stay_charge,
                schema_version,
            )
        ),
        charge_history=tuple(
            _charge_line_from_dict(item)
            for item in _object_list(
                _versioned_value(data, "charge_history", [], schema_version),
                "Charge history",
            )
        ),
        transfer_history=tuple(
            _transfer_record_from_dict(item)
            for item in _object_list(
                _versioned_value(data, "transfer_history", [], schema_version),
                "Transfer history",
            )
        ),
    )


def _versioned_value(
    data: dict[str, object],
    field_name: str,
    legacy_default: object,
    schema_version: int,
) -> object:
    """Use v1 defaults while requiring every canonical v2 field."""

    if schema_version == 1:
        return data.get(field_name, legacy_default)
    return data[field_name]


def _price_snapshot_from_dict(data: dict[str, object]) -> RoomPriceSnapshot:
    return RoomPriceSnapshot(
        room_id=str(data["room_id"]),
        room_name=str(data["room_name"]),
        room_type=str(data["room_type"]),
        base_price=str(data["base_price"]),
        cleaning_fee=str(data.get("cleaning_fee", "0.00")),
        minibar_fee=str(data.get("minibar_fee", "0.00")),
    )


def _charge_line_from_dict(data: dict[str, object]) -> RoomChargeLine:
    snapshot_data = data["price_snapshot"]
    if not isinstance(snapshot_data, dict):
        raise TypeError("Charge-line price snapshot must be an object.")
    return RoomChargeLine(
        charge_id=str(data["charge_id"]),
        price_snapshot=_price_snapshot_from_dict(snapshot_data),
        rental_days=_positive_integer(data["rental_days"], "Charge rental days"),
        amount=str(data["amount"]),
        finalized_reason=str(data["finalized_reason"]),
        finalized_at=str(data["finalized_at"]),
    )


def _transfer_record_from_dict(data: dict[str, object]) -> RoomTransferRecord:
    return RoomTransferRecord(
        transfer_id=str(data["transfer_id"]),
        source_room_id=str(data["source_room_id"]),
        destination_room_id=str(data["destination_room_id"]),
        source_charge_id=str(data["source_charge_id"]),
        source_days=_positive_integer(data["source_days"], "Transfer source days"),
        actor=str(data["actor"]),
        reason=str(data["reason"]),
        previous_projected_total=str(data["previous_projected_total"]),
        new_projected_total=str(data["new_projected_total"]),
        price_difference=str(data["price_difference"]),
        transferred_at=str(data["transferred_at"]),
    )


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        try:
            result = int(value.strip())
        except ValueError as error:
            raise ValueError(f"{field_name} must be an integer.") from error
    else:
        raise ValueError(f"{field_name} must be an integer.")

    if result <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return result


def _validate_loaded_state(rooms: list[Room], rentals: list[RentalRecord]) -> None:
    rented_room_ids: set[str] = set()
    for rental in rentals:
        room_id = rental.room.room_id
        if room_id in rented_room_ids:
            raise ValueError(f"Room {room_id} has more than one active rental.")
        rented_room_ids.add(room_id)

    for room in rooms:
        expected_status = (
            RoomStatus.RENTED if room.room_id in rented_room_ids else RoomStatus.AVAILABLE
        )
        if room.status is not expected_status:
            raise ValueError(
                f"Room {room.room_id} status does not match its active rental state."
            )
