from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

from file_handler import load_data
from models import Customer, RoomStatus, StandardRoom, VIPRoom
from services import (
    HotelManagementError,
    HotelManager,
    SecurityDepositError,
    SettlementQuoteError,
)


def manager_state(manager: HotelManager) -> dict[str, object]:
    """Return a value-only snapshot suitable for atomicity assertions."""

    return {
        "rooms": [room.to_dict() for room in manager.rooms],
        "active_rentals": [
            rental.to_dict() for rental in manager.active_rentals
        ],
        "revenue_history": [
            record.to_dict() for record in manager.revenue_history
        ],
    }


class PriceSnapshotTests(unittest.TestCase):
    def test_standard_and_vip_booking_prices_ignore_later_catalog_edits(self) -> None:
        standard = StandardRoom("S101", "Standard Original", "500")
        standard_manager = HotelManager([standard])
        standard_rental = standard_manager.book_room(
            "S101",
            Customer("C001", "Alex Nguyen", "ID001"),
            2,
        )

        standard.room_name = "Standard Renamed"
        standard.base_price = Decimal("999.00")

        self.assertEqual(standard_rental.projected_total, Decimal("1000.00"))
        self.assertEqual(
            standard_rental.current_price_snapshot.room_name,
            "Standard Original",
        )
        self.assertEqual(
            standard_rental.current_price_snapshot.base_price,
            Decimal("500.00"),
        )

        vip = VIPRoom("V201", "VIP Original", "1000", "150", "250")
        vip_manager = HotelManager([vip])
        vip_rental = vip_manager.book_room(
            "V201",
            Customer("C002", "Jamie Tran", "ID002"),
            2,
        )

        vip.room_name = "VIP Renamed"
        vip.base_price = Decimal("10.00")
        vip.cleaning_fee = Decimal("20.00")
        vip.minibar_fee = Decimal("30.00")

        self.assertEqual(vip_rental.projected_total, Decimal("2400.00"))
        self.assertEqual(vip_rental.current_price_snapshot.room_name, "VIP Original")
        self.assertEqual(
            vip_rental.current_price_snapshot.cleaning_fee,
            Decimal("150.00"),
        )
        self.assertEqual(
            vip_rental.current_price_snapshot.minibar_fee,
            Decimal("250.00"),
        )
        with self.assertRaises(FrozenInstanceError):
            vip_rental.current_price_snapshot.base_price = Decimal("1.00")  # type: ignore[misc]


class DepositAndSettlementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room = StandardRoom("S101", "Standard 101", "500")
        self.manager = HotelManager([self.room])
        self.rental = self.manager.book_room(
            "S101",
            Customer("C001", "Alex Nguyen", "ID001"),
            3,
        )

    def test_security_deposit_is_positive_bounded_and_recorded_once(self) -> None:
        for invalid_amount in ("0", "-1", "1500.01"):
            with self.subTest(amount=invalid_amount):
                before = manager_state(self.manager)
                with self.assertRaises(SecurityDepositError):
                    self.manager.record_security_deposit("S101", invalid_amount)
                self.assertEqual(manager_state(self.manager), before)

        self.manager.record_security_deposit("S101", "300")
        self.assertEqual(self.rental.security_deposit, Decimal("300.00"))

        before_duplicate = manager_state(self.manager)
        with self.assertRaises(SecurityDepositError):
            self.manager.record_security_deposit("S101", "100")
        self.assertEqual(manager_state(self.manager), before_duplicate)

    def test_checkout_quote_reconciles_deposit_refund_and_revenue(self) -> None:
        self.manager.record_security_deposit("S101", "300")

        quote = self.manager.quote_checkout(
            "S101",
            damage_deduction="100",
            reason="Broken lamp",
        )

        self.assertEqual(quote.stay_charge, Decimal("1500.00"))
        self.assertEqual(quote.security_deposit, Decimal("300.00"))
        self.assertEqual(quote.damage_deduction, Decimal("100.00"))
        self.assertEqual(quote.deposit_refund, Decimal("200.00"))
        self.assertEqual(quote.amount_to_collect, Decimal("1500.00"))
        self.assertEqual(quote.total_revenue, Decimal("1600.00"))
        self.assertEqual(
            quote.security_deposit
            + quote.amount_to_collect
            - quote.deposit_refund,
            quote.total_revenue,
        )
        self.assertEqual(len(quote.state_hash), 64)
        self.assertEqual(self.manager.revenue_history, [])

    def test_invalid_damage_deductions_leave_the_rental_unchanged(self) -> None:
        self.manager.record_security_deposit("S101", "300")

        cases = (
            {"damage_deduction": "301", "reason": "Damage"},
            {"damage_deduction": "1", "reason": None},
            {"damage_deduction": "1", "reason": "   "},
            {"damage_deduction": "-1", "reason": "Damage"},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                before = manager_state(self.manager)
                with self.assertRaises(SettlementQuoteError):
                    self.manager.quote_checkout("S101", **arguments)
                self.assertEqual(manager_state(self.manager), before)

    def test_quote_becomes_stale_after_a_room_transfer(self) -> None:
        destination = StandardRoom("S102", "Standard 102", "650")
        self.manager.add_room(destination)
        self.manager.record_security_deposit("S101", "300")
        quote = self.manager.quote_checkout(
            "S101",
            damage_deduction="50",
            reason="Stained towel",
        )
        self.manager.transfer_room(
            "S101",
            "S102",
            source_days=1,
            reason="Air conditioner failure",
            actor="front_desk",
        )
        before = manager_state(self.manager)

        with self.assertRaises(SettlementQuoteError):
            self.manager.checkout_room("S102", quote)

        self.assertEqual(manager_state(self.manager), before)
        self.assertEqual(destination.status, RoomStatus.RENTED)
        self.assertEqual(self.manager.revenue_history, [])


class RoomTransferTests(unittest.TestCase):
    def test_successful_transfer_preserves_identity_and_appends_audit(self) -> None:
        source = StandardRoom("S101", "Standard 101", "100")
        destination = VIPRoom("V201", "VIP 201", "200", "10", "20")
        manager = HotelManager([source, destination])
        customer = Customer("C001", "Alex Nguyen", "ID001")
        rental = manager.book_room("S101", customer, 4)
        original_rental_id = rental.rental_id
        manager.record_security_deposit("S101", "100")

        transfer = manager.transfer_room(
            "S101",
            "V201",
            source_days=1,
            reason="Plumbing failure",
            actor="night_manager",
        )

        self.assertEqual(source.status, RoomStatus.AVAILABLE)
        self.assertEqual(destination.status, RoomStatus.RENTED)
        self.assertIs(rental.room, destination)
        self.assertEqual(rental.rental_id, original_rental_id)
        self.assertIs(rental.customer, customer)
        self.assertEqual(rental.security_deposit, Decimal("100.00"))
        self.assertEqual(rental.completed_days, 1)
        self.assertEqual(rental.remaining_days, 3)
        self.assertEqual(len(rental.charge_history), 1)
        self.assertEqual(rental.charge_history[0].amount, Decimal("100.00"))
        self.assertEqual(rental.charge_history[0].finalized_reason, "transfer")
        self.assertEqual(len(rental.transfer_history), 1)
        self.assertIs(rental.transfer_history[0], transfer)
        self.assertEqual(transfer.source_charge_id, rental.charge_history[0].charge_id)
        self.assertEqual(transfer.actor, "night_manager")
        self.assertEqual(transfer.reason, "Plumbing failure")
        self.assertEqual(transfer.previous_projected_total, Decimal("400.00"))
        self.assertEqual(transfer.new_projected_total, Decimal("730.00"))
        self.assertEqual(transfer.price_difference, Decimal("330.00"))

    def test_failed_transfers_are_atomic(self) -> None:
        source = StandardRoom("S101", "Standard 101", "100")
        occupied = StandardRoom("S102", "Standard 102", "150")
        available = StandardRoom("S103", "Standard 103", "200")
        manager = HotelManager([source, occupied, available])
        manager.book_room(
            "S101",
            Customer("C001", "Alex Nguyen", "ID001"),
            3,
        )
        manager.book_room(
            "S102",
            Customer("C002", "Jamie Tran", "ID002"),
            2,
        )

        invalid_calls = (
            ("S101", "S101", 1, "Same room", "operator"),
            ("S101", "MISSING", 1, "Move", "operator"),
            ("S101", "S102", 1, "Occupied", "operator"),
            ("S101", "S103", 0, "Bad days", "operator"),
            ("S101", "S103", 3, "No remaining days", "operator"),
            ("S101", "S103", 1, "   ", "operator"),
            ("S101", "S103", 1, "Move", "   "),
        )
        for arguments in invalid_calls:
            with self.subTest(arguments=arguments):
                before = manager_state(manager)
                with self.assertRaises((HotelManagementError, ValueError)):
                    manager.transfer_room(
                        arguments[0],
                        arguments[1],
                        source_days=arguments[2],
                        reason=arguments[3],
                        actor=arguments[4],
                    )
                self.assertEqual(manager_state(manager), before)

    def test_multiple_transfers_conserve_days_and_prior_audit_history(self) -> None:
        first = StandardRoom("S101", "Standard 101", "100")
        second = StandardRoom("S102", "Standard 102", "200")
        third = VIPRoom("V201", "VIP 201", "300", "10", "20")
        manager = HotelManager([first, second, third])
        rental = manager.book_room(
            "S101",
            Customer("C001", "Alex Nguyen", "ID001"),
            5,
        )

        manager.transfer_room(
            "S101",
            "S102",
            source_days=2,
            reason="First move",
            actor="operator_one",
        )
        first_audit = rental.transfer_history[0]
        first_audit_values = first_audit.to_dict()
        manager.transfer_room(
            "S102",
            "V201",
            source_days=1,
            reason="Second move",
            actor="operator_two",
        )

        self.assertEqual(rental.completed_days, 3)
        self.assertEqual(rental.remaining_days, 2)
        self.assertEqual(
            sum(line.rental_days for line in rental.charge_history)
            + rental.remaining_days,
            rental.rental_days,
        )
        self.assertEqual([line.rental_days for line in rental.charge_history], [2, 1])
        self.assertEqual(len(rental.transfer_history), 2)
        self.assertEqual(first_audit.to_dict(), first_audit_values)
        with self.assertRaises(FrozenInstanceError):
            first_audit.reason = "Rewritten history"  # type: ignore[misc]
        self.assertEqual(rental.projected_total, Decimal("1030.00"))

    def test_checkout_uses_exact_frozen_segments_after_catalog_edits(self) -> None:
        source = StandardRoom("S101", "Standard Original", "100")
        destination = VIPRoom("V201", "VIP Original", "300", "10", "20")
        manager = HotelManager([source, destination])
        rental = manager.book_room(
            "S101",
            Customer("C001", "Alex Nguyen", "ID001"),
            4,
        )
        manager.transfer_room(
            "S101",
            "V201",
            source_days=2,
            reason="Upgrade",
            actor="front_desk",
        )

        source.base_price = Decimal("9000.00")
        source.room_name = "Standard Changed"
        destination.base_price = Decimal("8000.00")
        destination.cleaning_fee = Decimal("7000.00")
        destination.minibar_fee = Decimal("6000.00")
        destination.room_name = "VIP Changed"

        receipt = manager.checkout_room("V201")

        self.assertEqual(receipt.stay_charge, Decimal("830.00"))
        self.assertEqual(receipt.total_amount, Decimal("830.00"))
        self.assertEqual(receipt.room_name, "VIP Original")
        self.assertEqual([line.rental_days for line in receipt.charge_history], [2, 2])
        self.assertEqual(
            [line.amount for line in receipt.charge_history],
            [Decimal("200.00"), Decimal("630.00")],
        )
        self.assertEqual(
            sum(line.rental_days for line in receipt.charge_history),
            rental.rental_days,
        )


class AdvancedPersistenceTests(unittest.TestCase):
    def test_version_one_json_loads_with_safe_advanced_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "khachsan_data.json"
            path.write_text(
                json.dumps(
                    {
                        "rooms": [
                            {
                                "room_type": "standard",
                                "room_id": "S101",
                                "room_name": "Standard 101",
                                "base_price": "500.00",
                                "status": "Đã thuê",
                            }
                        ],
                        "active_rentals": [
                            {
                                "rental_id": "R001",
                                "customer": {
                                    "customer_id": "C001",
                                    "name": "Alex Nguyen",
                                    "identity_number": "ID001",
                                },
                                "room_id": "S101",
                                "rental_days": 2,
                                "booked_at": "2026-10-17T00:00:00+00:00",
                            }
                        ],
                        "revenue_history": [
                            {
                                "rental_id": "R000",
                                "room_id": "S100",
                                "room_name": "Archived Room",
                                "room_type": "standard",
                                "customer_id": "C000",
                                "customer_name": "Prior Guest",
                                "identity_number": "ID000",
                                "rental_days": 1,
                                "total_amount": "400.00",
                                "checked_out_at": "2026-10-16T00:00:00+00:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            rooms, rentals, revenue_history = load_data(path)

            self.assertEqual(len(rooms), 1)
            self.assertEqual(len(rentals), 1)
            self.assertEqual(rentals[0].security_deposit, Decimal("0.00"))
            self.assertEqual(rentals[0].charge_history, ())
            self.assertEqual(rentals[0].transfer_history, ())
            self.assertEqual(
                rentals[0].current_price_snapshot.base_price,
                Decimal("500.00"),
            )
            self.assertEqual(revenue_history[0].stay_charge, Decimal("400.00"))
            self.assertEqual(revenue_history[0].damage_charge, Decimal("0.00"))
            self.assertEqual(revenue_history[0].charge_history, ())

    def test_version_two_roundtrip_preserves_active_transfer_and_settlement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "khachsan_data.json"
            source = StandardRoom("S101", "Standard 101", "100")
            destination = VIPRoom("V201", "VIP 201", "200", "10", "20")
            checkout_room = StandardRoom("S102", "Standard 102", "300")
            manager = HotelManager(
                [source, destination, checkout_room],
                storage_path=path,
            )

            active = manager.book_room(
                "S101",
                Customer("C001", "Alex Nguyen", "ID001"),
                4,
            )
            manager.record_security_deposit("S101", "100")
            manager.transfer_room(
                "S101",
                "V201",
                source_days=1,
                reason="Maintenance",
                actor="front_desk",
            )
            manager.book_room(
                "S102",
                Customer("C002", "Jamie Tran", "ID002"),
                2,
            )
            manager.record_security_deposit("S102", "200")
            quote = manager.quote_checkout(
                "S102",
                damage_deduction="50",
                reason="Broken glass",
            )
            settled = manager.checkout_room("S102", quote)
            manager.save()

            raw_payload = json.loads(path.read_text(encoding="utf-8"))
            restored = HotelManager.load_from_file(path)

            self.assertEqual(raw_payload["schema_version"], 2)
            self.assertEqual(len(restored.active_rentals), 1)
            restored_active = restored.active_rentals[0]
            self.assertEqual(restored_active.rental_id, active.rental_id)
            self.assertEqual(restored_active.room.room_id, "V201")
            self.assertEqual(restored_active.security_deposit, Decimal("100.00"))
            self.assertEqual(len(restored_active.charge_history), 1)
            self.assertEqual(len(restored_active.transfer_history), 1)
            self.assertEqual(
                restored_active.transfer_history[0].reason,
                "Maintenance",
            )
            self.assertEqual(len(restored.revenue_history), 1)
            restored_settlement = restored.revenue_history[0]
            self.assertEqual(restored_settlement.rental_id, settled.rental_id)
            self.assertEqual(restored_settlement.stay_charge, Decimal("600.00"))
            self.assertEqual(restored_settlement.damage_charge, Decimal("50.00"))
            self.assertEqual(restored_settlement.total_amount, Decimal("650.00"))
            self.assertEqual(restored_settlement.deposit_refund, Decimal("150.00"))
            self.assertEqual(len(restored_settlement.charge_history), 1)


class RevenueReportTests(unittest.TestCase):
    def test_report_includes_damage_revenue_but_not_refunded_deposit(self) -> None:
        room = StandardRoom("S101", "Standard 101", "500")
        manager = HotelManager([room])
        manager.book_room(
            "S101",
            Customer("C001", "Alex Nguyen", "ID001"),
            2,
        )
        manager.record_security_deposit("S101", "300")
        quote = manager.quote_checkout(
            "S101",
            damage_deduction="100",
            reason="Damaged linen",
        )

        receipt = manager.checkout_room("S101", quote)
        report = manager.get_report()

        self.assertEqual(receipt.stay_charge, Decimal("1000.00"))
        self.assertEqual(receipt.damage_charge, Decimal("100.00"))
        self.assertEqual(receipt.security_deposit, Decimal("300.00"))
        self.assertEqual(receipt.deposit_refund, Decimal("200.00"))
        self.assertEqual(receipt.amount_collected_at_checkout, Decimal("1000.00"))
        self.assertEqual(receipt.total_amount, Decimal("1100.00"))
        self.assertEqual(report.total_revenue, Decimal("1100.00"))


if __name__ == "__main__":
    unittest.main()
