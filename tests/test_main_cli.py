from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from models import StandardRoom, VIPRoom
from services import HotelManager


class MainCLITests(unittest.TestCase):
    def test_invalid_data_file_is_preserved_before_starting_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "khachsan_data.json"
            invalid_content = "{not valid json"
            data_path.write_text(invalid_content, encoding="utf-8")

            with patch.object(main, "DATA_FILE", data_path), patch("builtins.print"):
                manager = main.load_manager()

            backups = list(Path(directory).glob("khachsan_data.corrupt-*.json"))
            self.assertEqual(manager.rooms, [])
            self.assertEqual(manager.storage_path, data_path)
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), invalid_content)

    def test_invalid_numeric_input_returns_to_menu_and_exit_saves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "khachsan_data.json"
            manager = HotelManager(storage_path=data_path)
            user_inputs = [
                "2",
                "S101",
                "Standard 101",
                "not-a-number",
                "6",
            ]

            with patch.object(
                main.HotelManager,
                "load_from_file",
                return_value=manager,
            ), patch("builtins.input", side_effect=user_inputs), patch(
                "builtins.print"
            ) as print_mock:
                main.run()

            printed = "\n".join(
                " ".join(str(argument) for argument in call.args)
                for call in print_mock.call_args_list
            )
            self.assertIn("Please enter a valid monetary amount", printed)
            self.assertTrue(data_path.exists())
            self.assertEqual(manager.rooms, [])

    def test_missing_room_is_reported_and_loop_continues(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "khachsan_data.json"
            manager = HotelManager(storage_path=data_path)
            user_inputs = [
                "3",
                "MISSING",
                "C001",
                "Alex Nguyen",
                "079123456789",
                "1",
                "6",
            ]

            with patch.object(
                main.HotelManager,
                "load_from_file",
                return_value=manager,
            ), patch("builtins.input", side_effect=user_inputs), patch(
                "builtins.print"
            ) as print_mock:
                main.run()

            printed = "\n".join(
                " ".join(str(argument) for argument in call.args)
                for call in print_mock.call_args_list
            )
            self.assertIn("Room MISSING does not exist", printed)
            self.assertTrue(data_path.exists())

    def test_advanced_menu_runs_deposit_transfer_and_settlement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "khachsan_data.json"
            manager = HotelManager(
                [
                    StandardRoom("S101", "Standard 101", "100"),
                    VIPRoom("V201", "VIP 201", "200", "10", "20"),
                ],
                storage_path=data_path,
            )
            user_inputs = [
                "3",
                "S101",
                "C001",
                "Alex Nguyen",
                "ID001",
                "3",
                "7",
                "S101",
                "300",
                "8",
                "S101",
                "V201",
                "1",
                "front_desk",
                "Air conditioner failure",
                "9",
                "V201",
                "100",
                "Broken lamp",
                "5",
                "6",
            ]

            with patch.object(
                main.HotelManager,
                "load_from_file",
                return_value=manager,
            ), patch("builtins.input", side_effect=user_inputs), patch(
                "builtins.print"
            ) as print_mock:
                main.run()

            printed = "\n".join(
                " ".join(str(argument) for argument in call.args)
                for call in print_mock.call_args_list
            )
            self.assertEqual(manager.active_rentals, [])
            self.assertEqual(len(manager.revenue_history), 1)
            receipt = manager.revenue_history[0]
            self.assertEqual(str(receipt.stay_charge), "530.00")
            self.assertEqual(str(receipt.damage_charge), "100.00")
            self.assertEqual(str(receipt.total_amount), "630.00")
            self.assertIn("Stay segments:", printed)
            self.assertIn("Total revenue: 630.00 VND", printed)
            self.assertTrue(data_path.exists())


if __name__ == "__main__":
    unittest.main()
