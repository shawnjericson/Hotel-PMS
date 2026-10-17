"""Core hotel-management business operations."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterable, TypeVar
from uuid import uuid4

from file_handler import DATA_FILE, load_data, save_data
from models import (
    Customer,
    RentalRecord,
    RevenueRecord,
    Room,
    RoomChargeLine,
    RoomPriceSnapshot,
    RoomTransferRecord,
    SettlementQuote,
)


OperationResult = TypeVar("OperationResult")


class HotelManagementError(Exception):
    """Base exception for expected business-rule failures."""


class DuplicateRoomError(HotelManagementError):
    pass


class RoomNotFoundError(HotelManagementError):
    pass


class RoomUnavailableError(HotelManagementError):
    pass


class RentalNotFoundError(HotelManagementError):
    pass


class SecurityDepositError(HotelManagementError):
    pass


class SettlementQuoteError(HotelManagementError):
    pass


class RoomTransferError(HotelManagementError):
    pass


@dataclass(frozen=True, slots=True)
class HotelReport:
    total_revenue: Decimal
    available_room_count: int
    total_room_count: int


class HotelManager:
    """Own rooms, active rentals, checkout history, and persistence."""

    def __init__(
        self,
        rooms: Iterable[Room] = (),
        active_rentals: Iterable[RentalRecord] = (),
        revenue_history: Iterable[RevenueRecord] = (),
        storage_path: str | Path = DATA_FILE,
    ) -> None:
        self.rooms = list(rooms)
        self.active_rentals = list(active_rentals)
        self.revenue_history = list(revenue_history)
        self.storage_path = Path(storage_path)
        self._validate_state()

    @classmethod
    def load_from_file(cls, storage_path: str | Path = DATA_FILE) -> "HotelManager":
        rooms, rentals, revenue_history = load_data(storage_path)
        return cls(rooms, rentals, revenue_history, storage_path)

    def save(self) -> None:
        save_data(
            self.rooms,
            self.active_rentals,
            self.revenue_history,
            self.storage_path,
        )

    def apply_and_save(
        self,
        operation: Callable[["HotelManager"], OperationResult],
    ) -> OperationResult:
        """Publish a change only after its candidate state is saved successfully.

        Running on a separate object graph leaves existing rooms and rentals
        untouched on validation or storage failure, allowing a safe retry.
        """

        candidate = copy.deepcopy(self)
        result = operation(candidate)
        candidate._validate_state()
        candidate.save()
        self.rooms = candidate.rooms
        self.active_rentals = candidate.active_rentals
        self.revenue_history = candidate.revenue_history
        return result

    def add_room(self, room: Room) -> Room:
        if any(existing.room_id == room.room_id for existing in self.rooms):
            raise DuplicateRoomError(f"Room {room.room_id} already exists.")
        if not room.is_available:
            raise RoomUnavailableError("A newly added room must be available.")
        self.rooms.append(room)
        return room

    def find_room(self, room_id: str) -> Room:
        normalized_id = str(room_id).strip()
        for room in self.rooms:
            if room.room_id == normalized_id:
                return room
        raise RoomNotFoundError(f"Room {normalized_id or room_id} does not exist.")

    def book_room(
        self,
        room_id: str,
        customer: Customer,
        rental_days: int,
    ) -> RentalRecord:
        room = self.find_room(room_id)
        if not room.is_available:
            raise RoomUnavailableError(f"Room {room.room_id} is not available.")

        # RentalRecord freezes room pricing before status changes, so future
        # catalogue edits cannot rewrite this stay's financial history.
        rental = RentalRecord(customer=customer, room=room, rental_days=rental_days)
        room.mark_rented()
        self.active_rentals.append(rental)
        return rental

    def record_security_deposit(
        self,
        room_id: str,
        amount: Decimal | int | float | str,
    ) -> RentalRecord:
        """Record the one-time deposit held for an active rental.

        A security deposit remains a liability until checkout. It is therefore
        kept separate from both the stay charge and recognized revenue.
        """

        room = self.find_room(room_id)
        rental = self._active_rental_for_room(room.room_id)
        try:
            rental.record_security_deposit(amount)
        except ValueError as error:
            raise SecurityDepositError(str(error)) from error
        return rental

    def quote_checkout(
        self,
        room_id: str,
        damage_deduction: Decimal | int | float | str = Decimal("0.00"),
        reason: str | None = None,
    ) -> SettlementQuote:
        """Build a deterministic, non-mutating checkout settlement quote."""

        room = self.find_room(room_id)
        rental = self._active_rental_for_room(room.room_id)
        try:
            deduction = _money(damage_deduction, "Damage deduction")
        except ValueError as error:
            raise SettlementQuoteError(str(error)) from error

        normalized_reason = _optional_text(reason)
        if deduction > rental.security_deposit:
            raise SettlementQuoteError(
                "Damage deduction cannot exceed the held security deposit."
            )
        if deduction > 0 and normalized_reason is None:
            raise SettlementQuoteError(
                "A reason is required for a security-deposit deduction."
            )

        stay_charge = rental.projected_total
        deposit_refund = rental.security_deposit - deduction
        amount_to_collect = stay_charge
        total_revenue = stay_charge + deduction
        state_hash = self._settlement_state_hash(
            rental,
            deduction,
            normalized_reason,
        )
        return SettlementQuote(
            rental_id=rental.rental_id,
            current_room_id=room.room_id,
            stay_charge=stay_charge,
            security_deposit=rental.security_deposit,
            damage_deduction=deduction,
            deposit_refund=deposit_refund,
            amount_to_collect=amount_to_collect,
            total_revenue=total_revenue,
            reason=normalized_reason,
            state_hash=state_hash,
            quoted_at=_utc_now(),
        )

    def checkout_room(
        self,
        room_id: str,
        settlement_quote: SettlementQuote | None = None,
    ) -> RevenueRecord:
        """Settle and close an active rental using frozen segment prices.

        Passing no quote preserves the original one-argument API and performs a
        normal checkout with no deposit deduction. When a quote is supplied, it
        is recomputed and compared before any mutation, preventing a stale or
        altered quote from being applied.
        """

        room = self.find_room(room_id)
        rental = self._active_rental_for_room(room.room_id)
        if settlement_quote is None:
            settlement_quote = self.quote_checkout(room.room_id)
        elif not isinstance(settlement_quote, SettlementQuote):
            raise SettlementQuoteError("Checkout requires a valid settlement quote.")

        expected_quote = self.quote_checkout(
            room.room_id,
            settlement_quote.damage_deduction,
            settlement_quote.reason,
        )
        if not _same_settlement(expected_quote, settlement_quote):
            raise SettlementQuoteError(
                "The settlement quote is stale or does not match the active rental."
            )

        # Build every immutable record before changing room/rental ownership.
        # Thus validation failures leave the manager untouched.
        final_charge = RoomChargeLine.create(
            rental.current_price_snapshot,
            rental.remaining_days,
            "checkout",
        )
        charge_history = rental.charge_history + (final_charge,)
        revenue_record = RevenueRecord.from_settlement(
            rental,
            settlement_quote,
            charge_history,
        )

        room.mark_available()
        try:
            self.active_rentals.remove(rental)
            self.revenue_history.append(revenue_record)
        except Exception:
            # Lists are normal Python lists, but keep the business operation
            # atomic even if a custom list implementation fails unexpectedly.
            if revenue_record in self.revenue_history:
                self.revenue_history.remove(revenue_record)
            if rental not in self.active_rentals:
                self.active_rentals.append(rental)
            if room.is_available:
                room.mark_rented()
            raise
        return revenue_record

    def transfer_room(
        self,
        source_room_id: str,
        destination_room_id: str,
        source_days: int,
        reason: str,
        actor: str = "cli_operator",
    ) -> RoomTransferRecord:
        """Move an active stay and append an immutable, auditable price segment.

        ``source_days`` is the number of still-unfinalized days spent in the
        current room before moving. At least one day must remain for the target
        room. Validation and record construction finish before state mutation;
        the guarded mutation also rolls back if an unexpected failure occurs.
        """

        source_room = self.find_room(source_room_id)
        destination_room = self.find_room(destination_room_id)
        if source_room.room_id == destination_room.room_id:
            raise RoomTransferError("Source and destination rooms must be different.")

        rental = self._active_rental_for_room(source_room.room_id)
        if not destination_room.is_available:
            raise RoomUnavailableError(
                f"Room {destination_room.room_id} is not available."
            )
        if isinstance(source_days, bool) or not isinstance(source_days, int):
            raise RoomTransferError("Source days must be an integer.")
        if source_days <= 0:
            raise RoomTransferError("Source days must be greater than zero.")
        if source_days >= rental.remaining_days:
            raise RoomTransferError(
                "At least one rental day must remain for the destination room."
            )

        normalized_reason = _required_text(reason, "Transfer reason")
        normalized_actor = _required_text(actor, "Actor")

        previous_projected_total = rental.projected_total
        source_charge = RoomChargeLine.create(
            rental.current_price_snapshot,
            source_days,
            "transfer",
        )
        destination_snapshot = RoomPriceSnapshot.from_room(destination_room)
        new_charge_history = rental.charge_history + (source_charge,)
        remaining_days = rental.remaining_days - source_days
        new_projected_total = (
            sum(
                (line.amount for line in new_charge_history),
                start=Decimal("0.00"),
            )
            + destination_snapshot.calculate_total(remaining_days)
        ).quantize(Decimal("0.01"))
        transfer_record = RoomTransferRecord(
            transfer_id=str(uuid4()),
            source_room_id=source_room.room_id,
            destination_room_id=destination_room.room_id,
            source_charge_id=source_charge.charge_id,
            source_days=source_days,
            actor=normalized_actor,
            reason=normalized_reason,
            previous_projected_total=previous_projected_total,
            new_projected_total=new_projected_total,
            price_difference=new_projected_total - previous_projected_total,
            transferred_at=_utc_now(),
        )
        new_transfer_history = rental.transfer_history + (transfer_record,)

        original_room = rental.room
        original_snapshot = rental.current_price_snapshot
        original_charge_history = rental.charge_history
        original_transfer_history = rental.transfer_history
        source_status_changed = False
        destination_status_changed = False
        try:
            source_room.mark_available()
            source_status_changed = True
            destination_room.mark_rented()
            destination_status_changed = True
            rental.room = destination_room
            rental.current_price_snapshot = destination_snapshot
            rental.charge_history = new_charge_history
            rental.transfer_history = new_transfer_history
        except Exception as error:
            rental.room = original_room
            rental.current_price_snapshot = original_snapshot
            rental.charge_history = original_charge_history
            rental.transfer_history = original_transfer_history
            if destination_status_changed and not destination_room.is_available:
                destination_room.mark_available()
            if source_status_changed and source_room.is_available:
                source_room.mark_rented()
            raise RoomTransferError("Room transfer could not be completed.") from error

        return transfer_record

    def get_report(self) -> HotelReport:
        return HotelReport(
            total_revenue=sum(
                (record.total_amount for record in self.revenue_history),
                start=Decimal("0.00"),
            ),
            available_room_count=sum(1 for room in self.rooms if room.is_available),
            total_room_count=len(self.rooms),
        )

    def _active_rental_for_room(self, room_id: str) -> RentalRecord:
        rental = next(
            (
                active_rental
                for active_rental in self.active_rentals
                if active_rental.room.room_id == room_id
            ),
            None,
        )
        if rental is None:
            raise RentalNotFoundError(
                f"Room {room_id} does not have an active rental."
            )
        return rental

    @staticmethod
    def _settlement_state_hash(
        rental: RentalRecord,
        damage_deduction: Decimal,
        reason: str | None,
    ) -> str:
        payload = {
            "damage_deduction": str(damage_deduction),
            "reason": reason,
            "rental": rental.to_dict(),
        }
        canonical_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def _validate_state(self) -> None:
        room_ids = [room.room_id for room in self.rooms]
        if len(room_ids) != len(set(room_ids)):
            raise DuplicateRoomError("The room list contains duplicate room IDs.")

        active_room_ids = [rental.room.room_id for rental in self.active_rentals]
        if len(active_room_ids) != len(set(active_room_ids)):
            raise RoomUnavailableError(
                "A room cannot have more than one active rental."
            )
        known_rooms = {room.room_id: room for room in self.rooms}
        if any(room_id not in known_rooms for room_id in active_room_ids):
            raise RoomNotFoundError("An active rental references an unknown room.")

        rental_ids = [rental.rental_id for rental in self.active_rentals]
        if len(rental_ids) != len(set(rental_ids)):
            raise HotelManagementError("Active rentals contain duplicate rental IDs.")

        for rental in self.active_rentals:
            canonical_room = known_rooms[rental.room.room_id]
            if canonical_room is not rental.room:
                raise RoomNotFoundError(
                    "An active rental must reference the manager's room object."
                )
            if rental.current_price_snapshot.room_id != rental.room.room_id:
                raise HotelManagementError(
                    "An active rental's price snapshot does not match its room."
                )

        active_room_id_set = set(active_room_ids)
        for room in self.rooms:
            should_be_available = room.room_id not in active_room_id_set
            if room.is_available is not should_be_available:
                raise RoomUnavailableError(
                    f"Room {room.room_id} status does not match its active rental state."
                )


def _money(
    value: Decimal | int | float | str,
    field_name: str,
) -> Decimal:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError(f"{field_name} must be a non-negative number.")
        amount = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} must be a valid number.") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{field_name} must be a non-negative number.")
    return amount


def _required_text(value: object, field_name: str) -> str:
    if value is None:
        raise RoomTransferError(f"{field_name} cannot be empty.")
    normalized = str(value).strip()
    if not normalized:
        raise RoomTransferError(f"{field_name} cannot be empty.")
    return normalized


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _same_settlement(expected: SettlementQuote, supplied: SettlementQuote) -> bool:
    return (
        supplied.rental_id == expected.rental_id
        and supplied.current_room_id == expected.current_room_id
        and supplied.stay_charge == expected.stay_charge
        and supplied.security_deposit == expected.security_deposit
        and supplied.damage_deduction == expected.damage_deduction
        and supplied.deposit_refund == expected.deposit_refund
        and supplied.amount_to_collect == expected.amount_to_collect
        and supplied.total_revenue == expected.total_revenue
        and supplied.reason == expected.reason
        and supplied.state_hash == expected.state_hash
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
