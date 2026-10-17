"""Command-line interface for the hotel management assignment."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from file_handler import DATA_FILE, DataFileError
from models import Customer, RevenueRecord, StandardRoom, VIPRoom
from services import HotelManagementError, HotelManager


def read_required_text(prompt: str) -> str:
    value = input(prompt).strip()
    if not value:
        raise ValueError("This value cannot be empty.")
    return value


def read_positive_integer(prompt: str) -> int:
    raw_value = input(prompt).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError("Please enter a whole number.") from error
    if value <= 0:
        raise ValueError("The number must be greater than zero.")
    return value


def read_non_negative_money(prompt: str) -> Decimal:
    raw_value = input(prompt).strip()
    try:
        value = Decimal(raw_value)
    except InvalidOperation as error:
        raise ValueError("Please enter a valid monetary amount.") from error
    if not value.is_finite() or value < 0:
        raise ValueError("The monetary amount cannot be negative.")
    return value


def format_money(amount: Decimal) -> str:
    return f"{amount:,.2f} VND"


def display_rooms(manager: HotelManager) -> None:
    if not manager.rooms:
        print("No rooms have been added yet.")
        return

    print("\nROOM LIST")
    print("-" * 78)
    print(f"{'ID':<12}{'Name':<24}{'Type':<12}{'Base price':>16}{'Status':>14}")
    print("-" * 78)
    for room in manager.rooms:
        print(
            f"{room.room_id:<12}{room.room_name:<24}{room.room_type.title():<12}"
            f"{format_money(room.base_price):>16}{room.status.value:>14}"
        )


def add_room(manager: HotelManager) -> None:
    room_id = read_required_text("Room ID: ")
    room_name = read_required_text("Room name: ")
    base_price = read_non_negative_money("Base price per day: ")
    room_type = read_required_text("Room type (1 = Standard, 2 = VIP): ")

    if room_type == "1":
        room = StandardRoom(room_id, room_name, base_price)
    elif room_type == "2":
        cleaning_fee = read_non_negative_money("Cleaning fee per stay: ")
        minibar_fee = read_non_negative_money("Minibar fee per stay: ")
        room = VIPRoom(
            room_id,
            room_name,
            base_price,
            cleaning_fee,
            minibar_fee,
        )
    else:
        raise ValueError("Room type must be 1 or 2.")

    manager.apply_and_save(lambda candidate: candidate.add_room(room))
    print(f"Room {room.room_id} was added successfully.")


def book_room(manager: HotelManager) -> None:
    room_id = read_required_text("Room ID to book: ")
    customer = Customer(
        customer_id=read_required_text("Customer ID: "),
        name=read_required_text("Customer name: "),
        identity_number=read_required_text("Citizen/identity number: "),
    )
    rental_days = read_positive_integer("Number of rental days: ")

    rental = manager.apply_and_save(
        lambda candidate: candidate.book_room(room_id, customer, rental_days)
    )
    print(
        f"Room {rental.room.room_id} was booked for {rental.customer.name} "
        f"for {rental.rental_days} day(s)."
    )
    print(f"Booked price snapshot: {format_money(rental.projected_total)}")


def display_checkout_receipt(receipt: RevenueRecord) -> None:
    """Print an itemized receipt while retaining the assignment's total line."""

    print("\nCHECKOUT RECEIPT")
    print(f"Customer: {receipt.customer_name}")
    print(f"Final room: {receipt.room_id} - {receipt.room_name}")
    print(f"Rental days: {receipt.rental_days}")
    if receipt.charge_history:
        print("Stay segments:")
        for index, line in enumerate(receipt.charge_history, start=1):
            snapshot = line.price_snapshot
            print(
                f"  {index}. {snapshot.room_id} - {snapshot.room_name}: "
                f"{line.rental_days} day(s), {format_money(line.amount)}"
            )
    print(f"Stay charge: {format_money(receipt.stay_charge)}")
    print(f"Security deposit held: {format_money(receipt.security_deposit)}")
    print(f"Damage deduction: {format_money(receipt.deposit_deduction)}")
    if receipt.damage_charge > 0:
        print(f"Damage reason: {receipt.damage_reason or 'Not recorded in legacy data'}")
    print(f"Deposit refund: {format_money(receipt.deposit_refund)}")
    print(
        "Amount to collect at checkout: "
        f"{format_money(receipt.amount_collected_at_checkout)}"
    )
    print(f"Total payment: {format_money(receipt.total_amount)}")


def checkout_room(manager: HotelManager) -> None:
    room_id = read_required_text("Room ID to check out: ")
    receipt = manager.apply_and_save(lambda candidate: candidate.checkout_room(room_id))
    display_checkout_receipt(receipt)


def record_security_deposit(manager: HotelManager) -> None:
    room_id = read_required_text("Room ID with an active rental: ")
    amount = read_non_negative_money("Security deposit amount: ")
    rental = manager.apply_and_save(
        lambda candidate: candidate.record_security_deposit(room_id, amount)
    )
    print(
        f"Security deposit for rental {rental.rental_id} recorded: "
        f"{format_money(rental.security_deposit)}"
    )


def transfer_active_rental(manager: HotelManager) -> None:
    source_room_id = read_required_text("Current room ID: ")
    destination_room_id = read_required_text("Destination room ID: ")
    source_days = read_positive_integer(
        "Number of stay days assigned to the current room: "
    )
    actor = read_required_text("Operator name/ID: ")
    reason = read_required_text("Transfer reason: ")
    transfer = manager.apply_and_save(
        lambda candidate: candidate.transfer_room(
            source_room_id,
            destination_room_id,
            source_days,
            reason,
            actor,
        )
    )
    print(
        f"Rental transferred from {transfer.source_room_id} to "
        f"{transfer.destination_room_id}."
    )
    print(f"Price difference: {format_money(transfer.price_difference)}")


def checkout_with_settlement(manager: HotelManager) -> None:
    room_id = read_required_text("Room ID to settle and check out: ")
    damage_deduction = read_non_negative_money(
        "Damage deduction from security deposit (0 if none): "
    )
    reason = None
    if damage_deduction > 0:
        reason = read_required_text("Damage deduction reason: ")

    quote = manager.quote_checkout(room_id, damage_deduction, reason)
    receipt = manager.apply_and_save(
        lambda candidate: candidate.checkout_room(room_id, quote)
    )
    display_checkout_receipt(receipt)


def display_report(manager: HotelManager) -> None:
    report = manager.get_report()
    print("\nHOTEL REPORT")
    print(f"Total revenue: {format_money(report.total_revenue)}")
    print(
        f"Available rooms: {report.available_room_count}/{report.total_room_count}"
    )


def load_manager() -> HotelManager:
    try:
        return HotelManager.load_from_file(DATA_FILE)
    except (DataFileError, HotelManagementError) as error:
        print(f"Warning: {error}")
        backup_path = preserve_invalid_data_file(DATA_FILE)
        if backup_path is None:
            raise DataFileError(
                "Cannot safely start with empty data because the original file "
                "could not be backed up. The original file was left unchanged."
            ) from error
        print(f"The invalid data file was preserved as {backup_path.name}.")
        print("The application will start with empty data.")
        return HotelManager(storage_path=DATA_FILE)


def preserve_invalid_data_file(file_path: str | Path) -> Path | None:
    source = Path(file_path)
    if not source.exists():
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = source.with_name(
        f"{source.stem}.corrupt-{timestamp}{source.suffix}"
    )
    try:
        shutil.copy2(source, backup_path)
    except OSError:
        return None
    return backup_path


def run() -> None:
    try:
        manager = load_manager()
    except (DataFileError, HotelManagementError) as error:
        print(f"Unable to start: {error}")
        return
    actions = {
        "1": lambda: display_rooms(manager),
        "2": lambda: add_room(manager),
        "3": lambda: book_room(manager),
        "4": lambda: checkout_room(manager),
        "5": lambda: display_report(manager),
        "7": lambda: record_security_deposit(manager),
        "8": lambda: transfer_active_rental(manager),
        "9": lambda: checkout_with_settlement(manager),
    }

    while True:
        print("\nHOTEL MANAGEMENT")
        print("1. Display rooms")
        print("2. Add a room")
        print("3. Book a room")
        print("4. Check out and pay")
        print("5. View revenue report")
        print("6. Save and exit")
        print("7. Record a security deposit")
        print("8. Transfer an active rental")
        print("9. Settle deposit/damage and check out")

        try:
            choice = input("Choose an option: ").strip()
            if choice == "6":
                manager.save()
                print("Data saved. Goodbye!")
                return
            action = actions.get(choice)
            if action is None:
                print("Please choose a number from 1 to 9.")
                continue
            action()
        except (HotelManagementError, ValueError, DataFileError) as error:
            print(f"Error: {error}")
        except (EOFError, KeyboardInterrupt):
            print("\nSaving data before exit...")
            try:
                manager.save()
            except DataFileError as error:
                print(f"Unable to save data: {error}")
            return


if __name__ == "__main__":
    run()
