"""Domain models for the hotel management CLI application."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from uuid import uuid4


def _required_text(value: str, field_name: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty.")
    return cleaned


def _money(value: Decimal | int | float | str, field_name: str) -> Decimal:
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


def _signed_money(value: Decimal | int | float | str, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} must be a valid number.") from error
    if not amount.is_finite():
        raise ValueError(f"{field_name} must be a finite number.")
    return amount


def _positive_integer(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer.")
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RoomStatus(str, Enum):
    """The two statuses required by the assignment."""

    AVAILABLE = "Trống"
    RENTED = "Đã thuê"


class Room(ABC):
    """Base room with an encapsulated, read-only status property."""

    room_type = "base"

    def __init__(
        self,
        room_id: str,
        room_name: str,
        base_price: Decimal | int | float | str,
        status: RoomStatus | str = RoomStatus.AVAILABLE,
    ) -> None:
        self.room_id = _required_text(room_id, "Room ID")
        self.room_name = _required_text(room_name, "Room name")
        self.base_price = _money(base_price, "Base price")
        self.__status = RoomStatus(status)

    @property
    def status(self) -> RoomStatus:
        """Expose status without allowing direct assignment."""

        return self.__status

    @property
    def is_available(self) -> bool:
        return self.__status is RoomStatus.AVAILABLE

    def mark_rented(self) -> None:
        if not self.is_available:
            raise ValueError(f"Room {self.room_id} is already rented.")
        self.__status = RoomStatus.RENTED

    def mark_available(self) -> None:
        if self.is_available:
            raise ValueError(f"Room {self.room_id} is already available.")
        self.__status = RoomStatus.AVAILABLE

    @abstractmethod
    def calculate_total(self, rental_days: int) -> Decimal:
        """Calculate the charge polymorphically for a stay."""

    def _validate_rental_days(self, rental_days: int) -> int:
        return _positive_integer(rental_days, "Rental days")

    def to_dict(self) -> dict[str, Any]:
        return {
            "room_type": self.room_type,
            "room_id": self.room_id,
            "room_name": self.room_name,
            "base_price": str(self.base_price),
            "status": self.status.value,
        }


class StandardRoom(Room):
    """A standard room with no additional service fee."""

    room_type = "standard"

    def calculate_total(self, rental_days: int) -> Decimal:
        days = self._validate_rental_days(rental_days)
        return (self.base_price * days).quantize(Decimal("0.01"))


class VIPRoom(Room):
    """A VIP room with one cleaning fee and one minibar fee per stay."""

    room_type = "vip"

    def __init__(
        self,
        room_id: str,
        room_name: str,
        base_price: Decimal | int | float | str,
        cleaning_fee: Decimal | int | float | str,
        minibar_fee: Decimal | int | float | str,
        status: RoomStatus | str = RoomStatus.AVAILABLE,
    ) -> None:
        super().__init__(room_id, room_name, base_price, status)
        self.cleaning_fee = _money(cleaning_fee, "Cleaning fee")
        self.minibar_fee = _money(minibar_fee, "Minibar fee")

    def calculate_total(self, rental_days: int) -> Decimal:
        days = self._validate_rental_days(rental_days)
        return (
            self.base_price * days + self.cleaning_fee + self.minibar_fee
        ).quantize(Decimal("0.01"))

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "cleaning_fee": str(self.cleaning_fee),
                "minibar_fee": str(self.minibar_fee),
            }
        )
        return data


@dataclass(frozen=True, slots=True)
class Customer:
    customer_id: str
    name: str
    identity_number: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "customer_id", _required_text(self.customer_id, "Customer ID"))
        object.__setattr__(self, "name", _required_text(self.name, "Customer name"))
        object.__setattr__(
            self,
            "identity_number",
            _required_text(self.identity_number, "Identity number"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "customer_id": self.customer_id,
            "name": self.name,
            "identity_number": self.identity_number,
        }


@dataclass(frozen=True, slots=True)
class RoomPriceSnapshot:
    """Immutable room identity and pricing captured for one stay segment."""

    room_id: str
    room_name: str
    room_type: str
    base_price: Decimal
    cleaning_fee: Decimal = Decimal("0.00")
    minibar_fee: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        object.__setattr__(self, "room_id", _required_text(self.room_id, "Room ID"))
        object.__setattr__(self, "room_name", _required_text(self.room_name, "Room name"))
        object.__setattr__(self, "room_type", _required_text(self.room_type, "Room type"))
        object.__setattr__(self, "base_price", _money(self.base_price, "Base price"))
        object.__setattr__(
            self,
            "cleaning_fee",
            _money(self.cleaning_fee, "Cleaning fee"),
        )
        object.__setattr__(
            self,
            "minibar_fee",
            _money(self.minibar_fee, "Minibar fee"),
        )

    @classmethod
    def from_room(cls, room: Room) -> "RoomPriceSnapshot":
        return cls(
            room_id=room.room_id,
            room_name=room.room_name,
            room_type=room.room_type,
            base_price=room.base_price,
            cleaning_fee=room.cleaning_fee if isinstance(room, VIPRoom) else Decimal("0.00"),
            minibar_fee=room.minibar_fee if isinstance(room, VIPRoom) else Decimal("0.00"),
        )

    def calculate_total(self, rental_days: int) -> Decimal:
        days = _positive_integer(rental_days, "Rental days")
        return (
            self.base_price * days + self.cleaning_fee + self.minibar_fee
        ).quantize(Decimal("0.01"))

    def to_dict(self) -> dict[str, str]:
        return {
            "room_id": self.room_id,
            "room_name": self.room_name,
            "room_type": self.room_type,
            "base_price": str(self.base_price),
            "cleaning_fee": str(self.cleaning_fee),
            "minibar_fee": str(self.minibar_fee),
        }


@dataclass(frozen=True, slots=True)
class RoomChargeLine:
    """Immutable charge for a finalized room segment."""

    charge_id: str
    price_snapshot: RoomPriceSnapshot
    rental_days: int
    amount: Decimal
    finalized_reason: str
    finalized_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "charge_id", _required_text(self.charge_id, "Charge ID"))
        _positive_integer(self.rental_days, "Rental days")
        if self.finalized_reason not in {"transfer", "checkout"}:
            raise ValueError("Finalized reason must be transfer or checkout.")
        object.__setattr__(
            self,
            "finalized_at",
            _required_text(self.finalized_at, "Finalized time"),
        )
        expected_amount = self.price_snapshot.calculate_total(self.rental_days)
        actual_amount = _money(self.amount, "Charge amount")
        if actual_amount != expected_amount:
            raise ValueError("Charge amount does not match its immutable price snapshot.")
        object.__setattr__(self, "amount", actual_amount)

    @classmethod
    def create(
        cls,
        price_snapshot: RoomPriceSnapshot,
        rental_days: int,
        finalized_reason: str,
    ) -> "RoomChargeLine":
        return cls(
            charge_id=str(uuid4()),
            price_snapshot=price_snapshot,
            rental_days=rental_days,
            amount=price_snapshot.calculate_total(rental_days),
            finalized_reason=finalized_reason,
            finalized_at=_utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "charge_id": self.charge_id,
            "price_snapshot": self.price_snapshot.to_dict(),
            "rental_days": self.rental_days,
            "amount": str(self.amount),
            "finalized_reason": self.finalized_reason,
            "finalized_at": self.finalized_at,
        }


@dataclass(frozen=True, slots=True)
class RoomTransferRecord:
    """Append-only audit evidence for a successful room transfer."""

    transfer_id: str
    source_room_id: str
    destination_room_id: str
    source_charge_id: str
    source_days: int
    actor: str
    reason: str
    previous_projected_total: Decimal
    new_projected_total: Decimal
    price_difference: Decimal
    transferred_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "transfer_id", _required_text(self.transfer_id, "Transfer ID"))
        object.__setattr__(
            self,
            "source_room_id",
            _required_text(self.source_room_id, "Source room ID"),
        )
        object.__setattr__(
            self,
            "destination_room_id",
            _required_text(self.destination_room_id, "Destination room ID"),
        )
        if self.source_room_id == self.destination_room_id:
            raise ValueError("Source and destination rooms must be different.")
        object.__setattr__(
            self,
            "source_charge_id",
            _required_text(self.source_charge_id, "Source charge ID"),
        )
        _positive_integer(self.source_days, "Source days")
        object.__setattr__(self, "actor", _required_text(self.actor, "Actor"))
        object.__setattr__(self, "reason", _required_text(self.reason, "Transfer reason"))
        previous_total = _money(self.previous_projected_total, "Previous projected total")
        new_total = _money(self.new_projected_total, "New projected total")
        difference = _signed_money(self.price_difference, "Price difference")
        if difference != new_total - previous_total:
            raise ValueError("Transfer price difference does not reconcile.")
        object.__setattr__(self, "previous_projected_total", previous_total)
        object.__setattr__(self, "new_projected_total", new_total)
        object.__setattr__(self, "price_difference", difference)
        object.__setattr__(
            self,
            "transferred_at",
            _required_text(self.transferred_at, "Transfer time"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "transfer_id": self.transfer_id,
            "source_room_id": self.source_room_id,
            "destination_room_id": self.destination_room_id,
            "source_charge_id": self.source_charge_id,
            "source_days": self.source_days,
            "actor": self.actor,
            "reason": self.reason,
            "previous_projected_total": str(self.previous_projected_total),
            "new_projected_total": str(self.new_projected_total),
            "price_difference": str(self.price_difference),
            "transferred_at": self.transferred_at,
        }


@dataclass(slots=True)
class RentalRecord:
    customer: Customer
    room: Room
    rental_days: int
    rental_id: str = field(default_factory=lambda: str(uuid4()))
    booked_at: str = field(default_factory=_utc_now)
    current_price_snapshot: RoomPriceSnapshot | None = None
    security_deposit: Decimal = Decimal("0.00")
    charge_history: tuple[RoomChargeLine, ...] = ()
    transfer_history: tuple[RoomTransferRecord, ...] = ()

    def __post_init__(self) -> None:
        self.rental_id = _required_text(self.rental_id, "Rental ID")
        self.booked_at = _required_text(self.booked_at, "Booked time")
        self.room._validate_rental_days(self.rental_days)
        self.current_price_snapshot = (
            self.current_price_snapshot or RoomPriceSnapshot.from_room(self.room)
        )
        if self.current_price_snapshot.room_id != self.room.room_id:
            raise ValueError("Current price snapshot must belong to the current room.")
        self.security_deposit = _money(self.security_deposit, "Security deposit")
        self.charge_history = tuple(self.charge_history)
        self.transfer_history = tuple(self.transfer_history)
        if self.completed_days >= self.rental_days:
            raise ValueError("An active rental must retain at least one unfinalized day.")

    @property
    def completed_days(self) -> int:
        return sum(line.rental_days for line in self.charge_history)

    @property
    def remaining_days(self) -> int:
        return self.rental_days - self.completed_days

    @property
    def projected_total(self) -> Decimal:
        finalized_total = sum(
            (line.amount for line in self.charge_history),
            start=Decimal("0.00"),
        )
        return (
            finalized_total
            + self.current_price_snapshot.calculate_total(self.remaining_days)
        ).quantize(Decimal("0.01"))

    def record_security_deposit(self, amount: Decimal | int | float | str) -> None:
        deposit = _money(amount, "Security deposit")
        if deposit <= 0:
            raise ValueError("Security deposit must be greater than zero.")
        if self.security_deposit > 0:
            raise ValueError("Security deposit has already been recorded.")
        if deposit > self.projected_total:
            raise ValueError("Security deposit cannot exceed the projected stay charge.")
        self.security_deposit = deposit

    def to_dict(self) -> dict[str, Any]:
        return {
            "rental_id": self.rental_id,
            "customer": self.customer.to_dict(),
            "room_id": self.room.room_id,
            "rental_days": self.rental_days,
            "booked_at": self.booked_at,
            "current_price_snapshot": self.current_price_snapshot.to_dict(),
            "security_deposit": str(self.security_deposit),
            "charge_history": [line.to_dict() for line in self.charge_history],
            "transfer_history": [record.to_dict() for record in self.transfer_history],
        }


@dataclass(frozen=True, slots=True)
class SettlementQuote:
    """Deterministic checkout plan bound to the current rental state."""

    rental_id: str
    current_room_id: str
    stay_charge: Decimal
    security_deposit: Decimal
    damage_deduction: Decimal
    deposit_refund: Decimal
    amount_to_collect: Decimal
    total_revenue: Decimal
    reason: str | None
    state_hash: str
    quoted_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "rental_id", _required_text(self.rental_id, "Rental ID"))
        object.__setattr__(
            self,
            "current_room_id",
            _required_text(self.current_room_id, "Current room ID"),
        )
        stay_charge = _money(self.stay_charge, "Stay charge")
        deposit = _money(self.security_deposit, "Security deposit")
        deduction = _money(self.damage_deduction, "Damage deduction")
        refund = _money(self.deposit_refund, "Deposit refund")
        amount_to_collect = _money(self.amount_to_collect, "Amount to collect")
        total_revenue = _money(self.total_revenue, "Total revenue")
        if deduction > deposit:
            raise ValueError("Damage deduction cannot exceed the security deposit.")
        if deduction > 0 and not (self.reason and self.reason.strip()):
            raise ValueError("A reason is required for a security-deposit deduction.")
        if refund != deposit - deduction:
            raise ValueError("Security-deposit refund does not reconcile.")
        if amount_to_collect != stay_charge:
            raise ValueError("Room payment must equal the complete stay charge.")
        if total_revenue != stay_charge + deduction:
            raise ValueError("Total revenue does not reconcile with stay and damage charges.")
        if deposit + amount_to_collect - refund != total_revenue:
            raise ValueError("Checkout cash settlement does not balance.")
        state_hash = _required_text(self.state_hash, "State hash").lower()
        if len(state_hash) != 64 or any(character not in "0123456789abcdef" for character in state_hash):
            raise ValueError("State hash must be a SHA-256 hexadecimal value.")
        object.__setattr__(self, "stay_charge", stay_charge)
        object.__setattr__(self, "security_deposit", deposit)
        object.__setattr__(self, "damage_deduction", deduction)
        object.__setattr__(self, "deposit_refund", refund)
        object.__setattr__(self, "amount_to_collect", amount_to_collect)
        object.__setattr__(self, "total_revenue", total_revenue)
        object.__setattr__(self, "reason", self.reason.strip() if self.reason else None)
        object.__setattr__(self, "state_hash", state_hash)
        object.__setattr__(self, "quoted_at", _required_text(self.quoted_at, "Quoted time"))


@dataclass(frozen=True, slots=True)
class RevenueRecord:
    rental_id: str
    room_id: str
    room_name: str
    room_type: str
    customer_id: str
    customer_name: str
    identity_number: str
    rental_days: int
    total_amount: Decimal
    checked_out_at: str
    stay_charge: Decimal | None = None
    damage_charge: Decimal = Decimal("0.00")
    security_deposit: Decimal = Decimal("0.00")
    deposit_deduction: Decimal = Decimal("0.00")
    deposit_refund: Decimal = Decimal("0.00")
    amount_collected_at_checkout: Decimal | None = None
    charge_history: tuple[RoomChargeLine, ...] = ()
    transfer_history: tuple[RoomTransferRecord, ...] = ()
    damage_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rental_id", _required_text(self.rental_id, "Rental ID"))
        object.__setattr__(self, "room_id", _required_text(self.room_id, "Room ID"))
        object.__setattr__(self, "room_name", _required_text(self.room_name, "Room name"))
        object.__setattr__(self, "room_type", _required_text(self.room_type, "Room type"))
        object.__setattr__(
            self,
            "customer_id",
            _required_text(self.customer_id, "Customer ID"),
        )
        object.__setattr__(
            self,
            "customer_name",
            _required_text(self.customer_name, "Customer name"),
        )
        object.__setattr__(
            self,
            "identity_number",
            _required_text(self.identity_number, "Identity number"),
        )
        _positive_integer(self.rental_days, "Rental days")
        total_amount = _money(self.total_amount, "Total amount")
        stay_charge = _money(
            self.stay_charge if self.stay_charge is not None else total_amount,
            "Stay charge",
        )
        damage_charge = _money(self.damage_charge, "Damage charge")
        security_deposit = _money(self.security_deposit, "Security deposit")
        deposit_deduction = _money(self.deposit_deduction, "Deposit deduction")
        deposit_refund = _money(self.deposit_refund, "Deposit refund")
        amount_collected = _money(
            self.amount_collected_at_checkout
            if self.amount_collected_at_checkout is not None
            else stay_charge,
            "Amount collected at checkout",
        )
        charge_history = tuple(self.charge_history)
        transfer_history = tuple(self.transfer_history)
        if self.damage_reason is not None and not isinstance(self.damage_reason, str):
            raise ValueError("Damage reason must be text or absent for legacy data.")
        damage_reason = (
            self.damage_reason.strip() or None
            if self.damage_reason is not None
            else None
        )
        if total_amount != stay_charge + damage_charge:
            raise ValueError("Revenue total does not reconcile with stay and damage charges.")
        if deposit_deduction != damage_charge:
            raise ValueError("Damage charge must equal the security-deposit deduction.")
        if deposit_deduction > security_deposit:
            raise ValueError("Deposit deduction cannot exceed the security deposit.")
        if deposit_refund != security_deposit - deposit_deduction:
            raise ValueError("Deposit refund does not reconcile.")
        if amount_collected != stay_charge:
            raise ValueError("Checkout collection must equal the stay charge.")
        if security_deposit + amount_collected - deposit_refund != total_amount:
            raise ValueError("Revenue cash settlement does not balance.")
        if charge_history:
            if sum(line.rental_days for line in charge_history) != self.rental_days:
                raise ValueError("Charge history days do not match the rental duration.")
            if sum(
                (line.amount for line in charge_history),
                start=Decimal("0.00"),
            ) != stay_charge:
                raise ValueError("Charge history does not reconcile with the stay charge.")
        object.__setattr__(self, "total_amount", total_amount)
        object.__setattr__(self, "stay_charge", stay_charge)
        object.__setattr__(self, "damage_charge", damage_charge)
        object.__setattr__(self, "security_deposit", security_deposit)
        object.__setattr__(self, "deposit_deduction", deposit_deduction)
        object.__setattr__(self, "deposit_refund", deposit_refund)
        object.__setattr__(self, "amount_collected_at_checkout", amount_collected)
        object.__setattr__(self, "charge_history", charge_history)
        object.__setattr__(self, "transfer_history", transfer_history)
        object.__setattr__(self, "damage_reason", damage_reason)
        object.__setattr__(
            self,
            "checked_out_at",
            _required_text(self.checked_out_at, "Checkout time"),
        )

    @classmethod
    def from_rental(
        cls,
        rental: RentalRecord,
        total_amount: Decimal,
    ) -> "RevenueRecord":
        final_line = RoomChargeLine.create(
            rental.current_price_snapshot,
            rental.remaining_days,
            "checkout",
        )
        charge_history = rental.charge_history + (final_line,)
        snapshotted_total = sum(
            (line.amount for line in charge_history),
            start=Decimal("0.00"),
        )
        if _money(total_amount, "Total amount") != snapshotted_total:
            raise ValueError("Provided total does not match the snapshotted stay charges.")
        return cls(
            rental_id=rental.rental_id,
            room_id=rental.room.room_id,
            room_name=rental.room.room_name,
            room_type=rental.room.room_type,
            customer_id=rental.customer.customer_id,
            customer_name=rental.customer.name,
            identity_number=rental.customer.identity_number,
            rental_days=rental.rental_days,
            total_amount=snapshotted_total,
            checked_out_at=_utc_now(),
            stay_charge=snapshotted_total,
            amount_collected_at_checkout=snapshotted_total,
            charge_history=charge_history,
            transfer_history=rental.transfer_history,
        )

    @classmethod
    def from_settlement(
        cls,
        rental: RentalRecord,
        quote: SettlementQuote,
        charge_history: tuple[RoomChargeLine, ...],
    ) -> "RevenueRecord":
        return cls(
            rental_id=rental.rental_id,
            room_id=rental.room.room_id,
            room_name=rental.current_price_snapshot.room_name,
            room_type=rental.current_price_snapshot.room_type,
            customer_id=rental.customer.customer_id,
            customer_name=rental.customer.name,
            identity_number=rental.customer.identity_number,
            rental_days=rental.rental_days,
            total_amount=quote.total_revenue,
            checked_out_at=_utc_now(),
            stay_charge=quote.stay_charge,
            damage_charge=quote.damage_deduction,
            damage_reason=quote.reason,
            security_deposit=quote.security_deposit,
            deposit_deduction=quote.damage_deduction,
            deposit_refund=quote.deposit_refund,
            amount_collected_at_checkout=quote.amount_to_collect,
            charge_history=charge_history,
            transfer_history=rental.transfer_history,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rental_id": self.rental_id,
            "room_id": self.room_id,
            "room_name": self.room_name,
            "room_type": self.room_type,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "identity_number": self.identity_number,
            "rental_days": self.rental_days,
            "total_amount": str(self.total_amount),
            "checked_out_at": self.checked_out_at,
            "stay_charge": str(self.stay_charge),
            "damage_charge": str(self.damage_charge),
            "damage_reason": self.damage_reason,
            "security_deposit": str(self.security_deposit),
            "deposit_deduction": str(self.deposit_deduction),
            "deposit_refund": str(self.deposit_refund),
            "amount_collected_at_checkout": str(self.amount_collected_at_checkout),
            "charge_history": [line.to_dict() for line in self.charge_history],
            "transfer_history": [record.to_dict() for record in self.transfer_history],
        }
