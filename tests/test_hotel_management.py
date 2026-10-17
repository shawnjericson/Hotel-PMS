from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from file_handler import DataFileError, load_data
from models import Customer, RentalRecord, RoomStatus, StandardRoom, VIPRoom
from services import (
    DuplicateRoomError,
    HotelManager,
    RentalNotFoundError,
    RoomNotFoundError,
    RoomUnavailableError,
)


class RoomModelTests(unittest.TestCase):
    def test_standard_and_vip_rooms_calculate_totals_polymorphically(self) -> None:
        rooms = [
            StandardRoom("S101", "Standard 101", "500000"),
            VIPRoom("V201", "VIP 201", "1000000", "150000", "250000"),
        ]

        totals = [room.calculate_total(2) for room in rooms]

        self.assertEqual(totals, [Decimal("1000000.00"), Decimal("2400000.00")])

    def test_room_status_is_read_only_and_changes_through_methods(self) -> None:
        room = StandardRoom("S101", "Standard 101", "500000")
        self.assertEqual(room.status, RoomStatus.AVAILABLE)

        with self.assertRaises(AttributeError):
            room.status = RoomStatus.RENTED  # type: ignore[misc]

        room.mark_rented()
        self.assertEqual(room.status, RoomStatus.RENTED)
        room.mark_available()
        self.assertEqual(room.status, RoomStatus.AVAILABLE)

    def test_invalid_prices_fees_and_rental_days_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StandardRoom("S101", "Standard 101", "-1")
        with self.assertRaises(ValueError):
            VIPRoom("V201", "VIP 201", "1000000", "-1", "0")
        with self.assertRaises(ValueError):
            StandardRoom("S102", "Standard 102", "1e999999")

        room = StandardRoom("S101", "Standard 101", "500000")
        with self.assertRaises(ValueError):
            room.calculate_total(0)


class HotelManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room = StandardRoom("S101", "Standard 101", "500000")
        self.customer = Customer("C001", "Alex Nguyen", "079123456789")
        self.manager = HotelManager([self.room])

    def test_add_room_rejects_duplicate_room_id(self) -> None:
        with self.assertRaises(DuplicateRoomError):
            self.manager.add_room(StandardRoom("S101", "Duplicate", "600000"))

    def test_add_room_rejects_a_room_already_marked_rented(self) -> None:
        room = StandardRoom("S102", "Standard 102", "600000")
        room.mark_rented()

        with self.assertRaises(RoomUnavailableError):
            self.manager.add_room(room)

    def test_manager_rejects_mismatched_room_and_rental_state(self) -> None:
        rental = RentalRecord(self.customer, self.room, 1)

        with self.assertRaises(RoomUnavailableError):
            HotelManager([self.room], [rental])

    def test_booking_rejects_missing_and_unavailable_rooms(self) -> None:
        with self.assertRaises(RoomNotFoundError):
            self.manager.book_room("MISSING", self.customer, 1)

        self.manager.book_room("S101", self.customer, 2)
        with self.assertRaises(RoomUnavailableError):
            self.manager.book_room("S101", self.customer, 1)

    def test_invalid_rental_days_do_not_mutate_room_or_rentals(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.book_room("S101", self.customer, 0)

        self.assertTrue(self.room.is_available)
        self.assertEqual(self.manager.active_rentals, [])

    def test_booking_and_checkout_update_status_revenue_and_availability(self) -> None:
        self.manager.book_room("S101", self.customer, 3)
        self.assertEqual(self.room.status, RoomStatus.RENTED)

        receipt = self.manager.checkout_room("S101")
        report = self.manager.get_report()

        self.assertEqual(receipt.total_amount, Decimal("1500000.00"))
        self.assertEqual(self.room.status, RoomStatus.AVAILABLE)
        self.assertEqual(self.manager.active_rentals, [])
        self.assertEqual(report.total_revenue, Decimal("1500000.00"))
        self.assertEqual(report.available_room_count, 1)

    def test_checkout_rejects_room_without_active_rental(self) -> None:
        with self.assertRaises(RentalNotFoundError):
            self.manager.checkout_room("S101")


class PersistenceTests(unittest.TestCase):
    def test_missing_data_file_loads_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing_path = Path(directory) / "khachsan_data.json"
            self.assertEqual(load_data(missing_path), ([], [], []))

    def test_save_and_load_preserve_rooms_active_rentals_and_revenue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "khachsan_data.json"
            standard = StandardRoom("S101", "Standard 101", "500000")
            vip = VIPRoom("V201", "VIP 201", "1000000", "150000", "250000")
            manager = HotelManager([standard, vip], storage_path=data_path)
            manager.book_room(
                "S101",
                Customer("C001", "Alex Nguyen", "079123456789"),
                2,
            )
            manager.book_room(
                "V201",
                Customer("C002", "Jamie Tran", "012345678901"),
                1,
            )
            manager.checkout_room("V201")
            manager.save()

            restored = HotelManager.load_from_file(data_path)

            self.assertEqual(len(restored.rooms), 2)
            self.assertEqual(len(restored.active_rentals), 1)
            self.assertEqual(restored.active_rentals[0].room.room_id, "S101")
            self.assertIs(restored.active_rentals[0].room, restored.find_room("S101"))
            self.assertEqual(restored.find_room("S101").status, RoomStatus.RENTED)
            self.assertEqual(restored.find_room("V201").status, RoomStatus.AVAILABLE)
            self.assertEqual(restored.get_report().total_revenue, Decimal("1400000.00"))

    def test_invalid_json_raises_a_controlled_data_file_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "khachsan_data.json"
            data_path.write_text("{not valid json", encoding="utf-8")

            with self.assertRaises(DataFileError):
                load_data(data_path)

    def test_valid_json_with_wrong_root_type_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "khachsan_data.json"
            data_path.write_text("[]", encoding="utf-8")

            with self.assertRaises(DataFileError):
                load_data(data_path)

    def test_inconsistent_room_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "khachsan_data.json"
            data_path.write_text(
                json.dumps(
                    {
                        "rooms": [
                            {
                                "room_type": "standard",
                                "room_id": "S101",
                                "room_name": "Standard 101",
                                "base_price": "500000.00",
                                "status": "Đã thuê",
                            }
                        ],
                        "active_rentals": [],
                        "revenue_history": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(DataFileError):
                load_data(data_path)

    def test_invalid_revenue_history_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "khachsan_data.json"
            data_path.write_text(
                json.dumps(
                    {
                        "rooms": [],
                        "active_rentals": [],
                        "revenue_history": [
                            {
                                "rental_id": "R001",
                                "room_id": "S101",
                                "room_name": "Standard 101",
                                "room_type": "standard",
                                "customer_id": "C001",
                                "customer_name": "Alex Nguyen",
                                "identity_number": "079123456789",
                                "rental_days": 1.5,
                                "total_amount": "-500000",
                                "checked_out_at": "2026-10-17T00:00:00+00:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(DataFileError):
                load_data(data_path)


if __name__ == "__main__":
    unittest.main()
