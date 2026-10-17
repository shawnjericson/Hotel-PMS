from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from file_handler import DataFileError
from gui import HotelApplication
from services import HotelManager


class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "hotel.json"
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = HotelApplication(self.root, HotelManager(storage_path=self.path))
        self.error_patch = patch("gui.messagebox.showerror")
        self.error_dialog = self.error_patch.start()
        self.confirm_patch = patch("gui.messagebox.askyesno", return_value=True)
        self.confirm_patch.start()

    def tearDown(self) -> None:
        self.error_patch.stop()
        self.confirm_patch.stop()
        self.root.destroy()
        self.directory.cleanup()

    def submit(self, **values: str) -> None:
        dialog = self.app.last_dialog
        self.assertIsNotNone(dialog)
        for key, value in values.items():
            dialog.values[key].set(value)
        dialog.submit_button.invoke()
        self.root.update_idletasks()

    def add_room(self, room_id: str, price: str = "100") -> None:
        self.app.add_button.invoke()
        self.submit(id=room_id, name=f"Room {room_id}", price=price)

    def book_room(self, room_id: str) -> None:
        self.app.room_tree.selection_set(room_id)
        self.app.book_button.invoke()
        self.submit(customer_id="C001", name="Alex", identity="ID001", days="3")

    def test_complete_desktop_workflow_and_restart(self) -> None:
        self.add_room("S101")
        self.add_room("S102", "200")
        self.book_room("S101")
        self.app.stay_tree.selection_set("S101")
        self.app.open_deposit()
        self.submit(amount="300")
        self.app.stay_tree.selection_set("S101")
        self.app.open_transfer()
        self.submit(destination="S102", days="1", actor="front_desk", reason="Maintenance")
        self.app.stay_tree.selection_set("S102")
        self.app.open_checkout()
        self.submit(damage="50", reason="Broken glass")

        self.error_dialog.assert_not_called()
        self.assertEqual(self.app.metrics["revenue"].get(), "550.00 VND")
        self.assertEqual(self.app.metrics["available"].get(), "2 / 2")
        self.assertEqual(self.app.metrics["deposits"].get(), "0.00 VND")
        self.assertEqual(len(self.app.history_tree.get_children()), 1)
        restored = HotelManager.load_from_file(self.path)
        self.assertEqual(str(restored.revenue_history[0].total_amount), "550.00")
        self.assertEqual(str(restored.revenue_history[0].deposit_refund), "250.00")
        self.assertEqual(restored.revenue_history[0].damage_reason, "Broken glass")
        self.assertEqual(len(restored.revenue_history[0].transfer_history), 1)
        receipt_text = [
            widget.get("1.0", "end")
            for window in self.root.winfo_children()
            if isinstance(window, tk.Toplevel)
            for widget in window.winfo_children()
            if isinstance(widget, tk.Text)
        ]
        self.assertTrue(any("Broken glass" in text for text in receipt_text))

    def test_invalid_form_stays_open_and_can_be_corrected(self) -> None:
        self.app.open_add_room()
        self.submit(id="S101", name="Standard", price="invalid")
        self.assertTrue(self.app.last_dialog.winfo_exists())
        self.assertEqual(self.app.manager.rooms, [])
        self.submit(price="100")
        self.assertEqual(len(self.app.manager.rooms), 1)
        self.assertFalse(self.app.last_dialog.winfo_exists())

    def test_save_failure_rolls_back_memory_and_retry_does_not_duplicate(self) -> None:
        self.app.open_add_room()
        with patch.object(HotelManager, "save", side_effect=DataFileError("Disk unavailable")):
            self.submit(id="S101", name="Standard", price="100")
        self.assertEqual(self.app.manager.rooms, [])
        self.assertTrue(self.app.last_dialog.winfo_exists())
        self.submit()
        self.assertEqual(len(self.app.manager.rooms), 1)

    def test_cancelled_checkout_keeps_rental_active(self) -> None:
        self.add_room("S101")
        self.book_room("S101")
        self.app.stay_tree.selection_set("S101")
        self.app.open_checkout()
        with patch("gui.messagebox.askyesno", return_value=False):
            self.submit(damage="0")
        self.assertEqual(len(self.app.manager.active_rentals), 1)
        self.assertEqual(self.app.manager.revenue_history, [])
        self.assertTrue(self.app.last_dialog.winfo_exists())

    def test_real_directory_permission_failure_keeps_form_retryable(self) -> None:
        self.app.open_add_room()
        with patch("file_handler.Path.mkdir", side_effect=PermissionError("No access")):
            self.submit(id="S101", name="Standard", price="100")
        self.error_dialog.assert_called_once()
        self.assertEqual(self.app.manager.rooms, [])
        self.assertTrue(self.app.last_dialog.winfo_exists())
        self.submit()
        self.assertEqual(len(self.app.manager.rooms), 1)

    def test_checkout_save_failure_can_be_retried_without_double_checkout(self) -> None:
        self.add_room("S101")
        self.book_room("S101")
        rental = self.app.manager.active_rentals[0]
        self.app.stay_tree.selection_set("S101")
        self.app.open_checkout()
        with patch("file_handler.Path.replace", side_effect=PermissionError("Cannot save")):
            self.submit(damage="0")
        self.assertIs(self.app.manager.active_rentals[0], rental)
        self.assertEqual(self.app.manager.revenue_history, [])
        self.assertTrue(self.app.last_dialog.winfo_exists())
        self.submit()
        self.assertEqual(self.app.manager.active_rentals, [])
        self.assertEqual(len(self.app.manager.revenue_history), 1)


if __name__ == "__main__":
    unittest.main()
