from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import main
from file_handler import DataFileError, load_data, save_data
from models import Customer, StandardRoom
from services import HotelManager, SettlementQuoteError


def state(manager: HotelManager) -> dict[str, object]:
    return {
        "rooms": [room.to_dict() for room in manager.rooms],
        "rentals": [rental.to_dict() for rental in manager.active_rentals],
        "revenue": [receipt.to_dict() for receipt in manager.revenue_history],
    }


class SafeStartupTests(unittest.TestCase):
    def test_backup_failure_stops_cli_without_overwriting_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hotel.json"
            original = b"{INVALID ORIGINAL DATA"
            path.write_bytes(original)
            with patch.object(main, "DATA_FILE", path), patch(
                "main.shutil.copy2", side_effect=PermissionError("Cannot back up")
            ), patch("builtins.print") as output, patch("builtins.input") as user_input, patch.object(
                HotelManager, "save"
            ) as save:
                main.run()
            user_input.assert_not_called()
            save.assert_not_called()
            self.assertEqual(path.read_bytes(), original)
            self.assertTrue(any("Unable to start" in str(call) for call in output.call_args_list))

    def test_invalid_file_is_recoverable_after_successful_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hotel.json"
            original = b"{INVALID ORIGINAL DATA"
            path.write_bytes(original)
            with patch.object(main, "DATA_FILE", path), patch("builtins.print"):
                manager = main.load_manager()
                manager.save()
            backups = list(Path(directory).glob("hotel.corrupt-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertEqual(load_data(path), ([], [], []))


class SafeStorageTests(unittest.TestCase):
    def test_directory_permission_error_is_a_controlled_data_file_error(self) -> None:
        with patch("file_handler.Path.mkdir", side_effect=PermissionError("No access")):
            with self.assertRaises(DataFileError):
                save_data([], [], file_path="unused.json")

    def test_failed_write_keeps_original_and_removes_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hotel.json"
            save_data([], [], file_path=path)
            original = path.read_bytes()
            with patch("file_handler.os.fsync", side_effect=OSError("Disk full")):
                with self.assertRaises(DataFileError):
                    save_data([StandardRoom("101", "Standard", "100")], [], file_path=path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_cleanup_error_does_not_hide_the_original_save_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hotel.json"
            with patch("file_handler.Path.replace", side_effect=OSError("Original failure")), patch(
                "file_handler.Path.unlink", side_effect=PermissionError("Cleanup failure")
            ):
                with self.assertRaisesRegex(DataFileError, "Original failure"):
                    save_data([], [], file_path=path)


class CLIPersistenceTransactionTests(unittest.TestCase):
    def test_all_cli_mutations_are_retryable_after_save_failure(self) -> None:
        cases = [
            ("add", main.add_room, ["103", "Standard 103", "300", "1"]),
            ("book", main.book_room, ["101", "C1", "Guest", "ID1", "3"]),
            ("checkout", main.checkout_room, ["101"]),
            ("deposit", main.record_security_deposit, ["101", "50"]),
            ("transfer", main.transfer_active_rental, ["101", "102", "1", "operator", "Maintenance"]),
            ("settlement", main.checkout_with_settlement, ["101", "20", "Broken glass"]),
        ]
        for name, action, inputs in cases:
            with self.subTest(action=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "hotel.json"
                manager = HotelManager([
                    StandardRoom("101", "Standard 101", "100"),
                    StandardRoom("102", "Standard 102", "200"),
                ], storage_path=path)
                if name not in {"add", "book"}:
                    manager.book_room("101", Customer("C1", "Guest", "ID1"), 3)
                if name == "settlement":
                    manager.record_security_deposit("101", "50")
                manager.save()
                before = state(manager)
                original_bytes = path.read_bytes()
                original_room = manager.find_room("101")
                original_rental = manager.active_rentals[0] if manager.active_rentals else None
                with patch("builtins.input", side_effect=inputs), patch("builtins.print"), patch(
                    "file_handler.Path.replace", side_effect=PermissionError("Cannot replace file")
                ):
                    with self.assertRaises(DataFileError):
                        action(manager)
                self.assertEqual(state(manager), before)
                self.assertIs(manager.find_room("101"), original_room)
                if original_rental is not None:
                    self.assertIs(manager.active_rentals[0], original_rental)
                self.assertEqual(path.read_bytes(), original_bytes)
                with patch("builtins.input", side_effect=inputs), patch("builtins.print"):
                    action(manager)
                self.assertNotEqual(state(manager), before)
                restored = HotelManager.load_from_file(path)
                self.assertEqual(state(restored), state(manager))


class DamageEvidenceTests(unittest.TestCase):
    def test_damage_reason_is_immutable_persisted_and_printed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hotel.json"
            manager = HotelManager([StandardRoom("101", "Standard", "100")], storage_path=path)
            manager.book_room("101", Customer("C1", "Guest", "ID1"), 2)
            manager.record_security_deposit("101", "100")
            quote = manager.quote_checkout("101", "20", "  Broken lamp  ")
            receipt = manager.apply_and_save(lambda candidate: candidate.checkout_room("101", quote))
            self.assertEqual(receipt.damage_reason, "Broken lamp")
            with self.assertRaises(FrozenInstanceError):
                receipt.damage_reason = "Changed"  # type: ignore[misc]
            restored = HotelManager.load_from_file(path)
            self.assertEqual(restored.revenue_history[0].damage_reason, "Broken lamp")
            self.assertEqual(restored.get_report().total_revenue, Decimal("220.00"))
            with patch("builtins.print") as output:
                main.display_checkout_receipt(restored.revenue_history[0])
            self.assertTrue(any("Broken lamp" in str(call) for call in output.call_args_list))

    def test_older_version_two_history_without_reason_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hotel.json"
            manager = HotelManager([StandardRoom("101", "Standard", "100")], storage_path=path)
            manager.book_room("101", Customer("C1", "Guest", "ID1"), 1)
            manager.record_security_deposit("101", "50")
            manager.checkout_room("101", manager.quote_checkout("101", "20", "Old damage"))
            manager.save()
            payload = json.loads(path.read_text(encoding="utf-8"))
            del payload["revenue_history"][0]["damage_reason"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            restored = HotelManager.load_from_file(path)
            self.assertIsNone(restored.revenue_history[0].damage_reason)
            self.assertEqual(restored.get_report().total_revenue, Decimal("120.00"))


class MoneyValidationTests(unittest.TestCase):
    def test_negative_fraction_cannot_round_into_an_accepted_zero(self) -> None:
        with self.assertRaises(ValueError):
            StandardRoom("101", "Invalid", "-0.001")
        manager = HotelManager([StandardRoom("101", "Standard", "100")])
        manager.book_room("101", Customer("C1", "Guest", "ID1"), 1)
        with self.assertRaises(SettlementQuoteError):
            manager.quote_checkout("101", "-0.001")


if __name__ == "__main__":
    unittest.main()
