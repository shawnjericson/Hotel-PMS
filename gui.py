"""Tkinter desktop interface sharing the CLI's hotel business services."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from file_handler import DATA_FILE, DataFileError
from models import Customer, RevenueRecord, StandardRoom, VIPRoom
from services import HotelManagementError, HotelManager


def format_money(amount: Decimal) -> str:
    return f"{amount:,.2f} VND"


class FormDialog(tk.Toplevel):
    """Modal form that remains open when validation fails."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        fields: list[tuple[str, str, object]],
        on_submit: Callable[[dict[str, str]], bool],
        note: str = "",
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.values: dict[str, tk.StringVar] = {}
        self.on_submit = on_submit
        body = ttk.Frame(self, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, style="Heading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 18)
        )
        first_widget = None
        for row, (key, label, default) in enumerate(fields, start=1):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 20), pady=7)
            choices = default if isinstance(default, list) else None
            value = choices[0] if choices else default
            variable = tk.StringVar(value=value)
            self.values[key] = variable
            if choices is not None:
                widget = ttk.Combobox(body, textvariable=variable, values=choices, state="readonly", width=30)
            else:
                widget = ttk.Entry(body, textvariable=variable, width=33)
            widget.grid(row=row, column=1, sticky="ew", pady=7)
            first_widget = first_widget or widget
        last_row = len(fields) + 1
        if note:
            ttk.Label(body, text=note, wraplength=460, style="Muted.TLabel").grid(
                row=last_row, column=0, columnspan=2, sticky="w", pady=(12, 4)
            )
        actions = ttk.Frame(body)
        actions.grid(row=last_row + 1, column=0, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(actions, text="Hủy", command=self.destroy).pack(side="left", padx=8)
        self.submit_button = ttk.Button(actions, text="Xác nhận", style="Accent.TButton", command=self.submit)
        self.submit_button.pack(side="left")
        self.bind("<Return>", lambda event: self.submit())
        self.bind("<Escape>", lambda event: self.destroy())
        self.grab_set()
        if first_widget:
            first_widget.focus_set()

    def submit(self) -> None:
        if str(self.submit_button["state"]) == "disabled":
            return
        self.submit_button.configure(state="disabled")
        try:
            values = {key: value.get().strip() for key, value in self.values.items()}
            if self.on_submit(values):
                self.destroy()
                return
        finally:
            if self.winfo_exists():
                self.submit_button.configure(state="normal")


class HotelApplication:
    """Desktop dashboard with room, stay, settlement, and history views."""

    def __init__(self, root: tk.Tk, manager: HotelManager) -> None:
        self.root = root
        self.manager = manager
        self.last_dialog: FormDialog | None = None
        root.title("Hotel Desk | Quản lý khách sạn")
        root.geometry("1180x760")
        root.minsize(980, 650)
        root.configure(background="#f3f6fa")
        self._configure_style()
        header = tk.Frame(root, bg="#142b45", padx=28, pady=22)
        header.pack(fill="x")
        tk.Label(header, text="HOTEL DESK", font=("Segoe UI", 24, "bold"), bg="#142b45", fg="white").pack(anchor="w")
        tk.Label(header, text="Phòng • Lưu trú • Thanh toán", font=("Segoe UI", 11), bg="#142b45", fg="#bbd4e9").pack(anchor="w", pady=(4, 0))
        content = ttk.Frame(root, padding=24)
        content.pack(fill="both", expand=True)
        cards = ttk.Frame(content)
        cards.pack(fill="x", pady=(0, 20))
        self.metrics: dict[str, tk.StringVar] = {}
        for index, (key, label) in enumerate([
            ("revenue", "DOANH THU ĐÃ CHỐT"),
            ("available", "PHÒNG TRỐNG"),
            ("active", "ĐANG LƯU TRÚ"),
            ("deposits", "CỌC BẢO ĐẢM ĐANG GIỮ"),
        ]):
            cards.columnconfigure(index, weight=1)
            card = ttk.Frame(cards, style="Card.TFrame", padding=16)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 12, 0))
            ttk.Label(card, text=label, style="CardCaption.TLabel").pack(anchor="w")
            value = tk.StringVar()
            self.metrics[key] = value
            ttk.Label(card, textvariable=value, style="Metric.TLabel").pack(anchor="w", pady=(10, 0))
        self.notebook = ttk.Notebook(content)
        self.notebook.pack(fill="both", expand=True)
        self.room_tab = ttk.Frame(self.notebook, padding=16)
        self.stay_tab = ttk.Frame(self.notebook, padding=16)
        self.history_tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(self.room_tab, text="  Danh sách phòng  ")
        self.notebook.add(self.stay_tab, text="  Khách đang ở  ")
        self.notebook.add(self.history_tab, text="  Lịch sử thanh toán  ")
        room_actions = ttk.Frame(self.room_tab)
        room_actions.pack(fill="x", pady=(0, 14))
        ttk.Label(room_actions, text="Quản lý phòng", style="Heading.TLabel").pack(side="left")
        self.add_button = ttk.Button(room_actions, text="+ Thêm phòng", command=self.open_add_room, style="Accent.TButton")
        self.add_button.pack(side="right")
        self.book_button = ttk.Button(room_actions, text="Đặt phòng đã chọn", command=self.open_booking)
        self.book_button.pack(side="right", padx=10)
        self.room_tree = self._table(self.room_tab, [
            ("id", "Mã phòng", 100), ("name", "Tên phòng", 240),
            ("type", "Loại", 100), ("price", "Giá / ngày", 160),
            ("fees", "Phí VIP / lượt", 160), ("status", "Trạng thái", 130),
        ])
        stay_actions = ttk.Frame(self.stay_tab)
        stay_actions.pack(fill="x", pady=(0, 14))
        ttk.Label(stay_actions, text="Khách đang lưu trú", style="Heading.TLabel").pack(side="left")
        for label, action in [("Trả phòng", self.open_checkout), ("Chuyển phòng", self.open_transfer), ("Nhận cọc", self.open_deposit)]:
            ttk.Button(stay_actions, text=label, command=action).pack(side="right", padx=(8, 0))
        self.stay_tree = self._table(self.stay_tab, [
            ("room", "Phòng", 90), ("guest", "Khách hàng", 220),
            ("days", "Tổng ngày", 90), ("remaining", "Ngày chưa chốt", 120),
            ("charge", "Giá thuê đã chốt", 170), ("deposit", "Cọc bảo đảm", 160),
        ])
        ttk.Label(self.stay_tab, text="Chọn một khách để nhận cọc, chuyển phòng hoặc xem đối soát trước khi trả phòng.", style="Muted.TLabel").pack(anchor="w", pady=(12, 0))
        history_actions = ttk.Frame(self.history_tab)
        history_actions.pack(fill="x", pady=(0, 14))
        ttk.Label(history_actions, text="Thanh toán đã hoàn tất", style="Heading.TLabel").pack(side="left")
        ttk.Button(history_actions, text="Xem biên nhận", command=self.open_receipt).pack(side="right")
        self.history_tree = self._table(self.history_tab, [
            ("room", "Phòng cuối", 100), ("guest", "Khách hàng", 200),
            ("stay", "Tiền phòng", 140), ("damage", "Bồi thường", 140),
            ("refund", "Cọc hoàn lại", 140), ("total", "Doanh thu", 160),
        ])
        self.status = tk.StringVar(value="Sẵn sàng. Chọn “Thêm phòng” để bắt đầu.")
        ttk.Label(content, textvariable=self.status, style="Muted.TLabel").pack(anchor="w", pady=(14, 0))
        self.room_tree.bind("<Double-1>", lambda event: self.open_booking())
        self.history_tree.bind("<Double-1>", lambda event: self.open_receipt())
        self.refresh()
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background="#f3f6fa", foreground="#18334c")
        style.configure("TButton", padding=(14, 9))
        style.configure("Accent.TButton", background="#087f8c", foreground="white")
        style.map("Accent.TButton", background=[("active", "#096b76")])
        style.configure("Card.TFrame", background="white")
        style.configure("CardCaption.TLabel", background="white", foreground="#60768a", font=("Segoe UI", 9))
        style.configure("Metric.TLabel", background="white", font=("Segoe UI", 20, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Muted.TLabel", foreground="#60768a")
        style.configure("Treeview", rowheight=37, background="white", fieldbackground="white", borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=10)
        style.map("Treeview", background=[("selected", "#d3eef0")], foreground=[("selected", "#103b45")])
        style.configure("TNotebook.Tab", padding=(10, 10))

    def _table(self, parent: ttk.Frame, columns: list[tuple[str, str, int]]) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=[item[0] for item in columns], show="headings", selectmode="browse")
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=75)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        tree.tag_configure("available", foreground="#087f63")
        tree.tag_configure("rented", foreground="#9a5c12")
        return tree

    def refresh(self) -> None:
        report = self.manager.get_report()
        deposits = sum((rental.security_deposit for rental in self.manager.active_rentals), Decimal("0"))
        self.metrics["revenue"].set(format_money(report.total_revenue))
        self.metrics["available"].set(f"{report.available_room_count} / {report.total_room_count}")
        self.metrics["active"].set(str(len(self.manager.active_rentals)))
        self.metrics["deposits"].set(format_money(deposits))
        for tree in (self.room_tree, self.stay_tree, self.history_tree):
            for item in tree.get_children():
                tree.delete(item)
        for room in self.manager.rooms:
            fees = room.cleaning_fee + room.minibar_fee if isinstance(room, VIPRoom) else Decimal("0")
            self.room_tree.insert("", "end", iid=room.room_id, values=(room.room_id, room.room_name, room.room_type.upper(), format_money(room.base_price), format_money(fees), room.status.value), tags=("available" if room.is_available else "rented",))
        for rental in self.manager.active_rentals:
            self.stay_tree.insert("", "end", iid=rental.room.room_id, values=(rental.room.room_id, rental.customer.name, rental.rental_days, rental.remaining_days, format_money(rental.projected_total), format_money(rental.security_deposit)))
        for index, receipt in enumerate(self.manager.revenue_history):
            self.history_tree.insert("", 0, iid=str(index), values=(receipt.room_id, receipt.customer_name, format_money(receipt.stay_charge), format_money(receipt.damage_charge), format_money(receipt.deposit_refund), format_money(receipt.total_amount)))

    def _selected(self, tree: ttk.Treeview) -> str | None:
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("Chọn bản ghi", "Anh/chị hãy chọn một dòng trong danh sách trước.", parent=self.root)
            return None
        return selection[0]

    def _form(self, title: str, fields: list[tuple[str, str, object]], submit: Callable[[dict[str, str]], bool], note: str = "") -> None:
        self.last_dialog = FormDialog(self.root, title, fields, submit, note)

    def _commit(self, operation: Callable[[HotelManager], object], success: str) -> bool:
        """Persist the candidate change before publishing it to the interface."""
        try:
            self.manager.apply_and_save(operation)
        except (HotelManagementError, ValueError, DataFileError) as error:
            messagebox.showerror("Chưa thể hoàn tất", str(error), parent=self.last_dialog or self.root)
            self.refresh()
            return False
        self.refresh()
        self.status.set(success)
        return True

    def open_add_room(self) -> None:
        def submit(values: dict[str, str]) -> bool:
            def operation(candidate: HotelManager) -> None:
                if values["type"] == "VIP":
                    room = VIPRoom(values["id"], values["name"], values["price"], values["cleaning"], values["minibar"])
                else:
                    room = StandardRoom(values["id"], values["name"], values["price"])
                candidate.add_room(room)
            return self._commit(operation, f"Đã thêm phòng {values['id']} và lưu dữ liệu.")
        self._form("Thêm phòng", [("id", "Mã phòng", ""), ("name", "Tên phòng", ""), ("type", "Loại phòng", ["Standard", "VIP"]), ("price", "Giá phòng / ngày (VND)", ""), ("cleaning", "Phí vệ sinh VIP (VND)", "0"), ("minibar", "Phí minibar VIP (VND)", "0")], submit, "Phí vệ sinh và minibar chỉ áp dụng cho VIP, tính một lần cho mỗi lượt ở phòng đó.")

    def open_booking(self) -> None:
        room_id = self._selected(self.room_tree)
        if room_id is None:
            return
        if not self.manager.find_room(room_id).is_available:
            messagebox.showinfo("Phòng đang được thuê", "Chọn một phòng trống để đặt phòng.", parent=self.root)
            return
        def submit(values: dict[str, str]) -> bool:
            return self._commit(lambda candidate: candidate.book_room(room_id, Customer(values["customer_id"], values["name"], values["identity"]), int(values["days"])), f"Đã đặt phòng {room_id}; giá được chốt theo thời điểm đặt.")
        self._form(f"Đặt phòng {room_id}", [("customer_id", "Mã khách hàng", ""), ("name", "Tên khách hàng", ""), ("identity", "CCCD / Hộ chiếu", ""), ("days", "Số ngày thuê", "1")], submit, "Giá đã chốt được giữ nguyên nếu danh mục giá phòng thay đổi sau này.")

    def open_deposit(self) -> None:
        room_id = self._selected(self.stay_tree)
        if room_id is None:
            return
        self._form(f"Nhận cọc • {room_id}", [("amount", "Số tiền cọc (VND)", "")], lambda values: self._commit(lambda candidate: candidate.record_security_deposit(room_id, values["amount"]), f"Đã nhận cọc bảo đảm cho phòng {room_id}."), "Cọc bảo đảm được giữ riêng và hoàn lại khi trả phòng, sau khi trừ khoản bồi thường được xác nhận.")

    def open_transfer(self) -> None:
        room_id = self._selected(self.stay_tree)
        if room_id is None:
            return
        available = [room.room_id for room in self.manager.rooms if room.is_available]
        if not available:
            messagebox.showinfo("Chưa có phòng trống", "Cần có phòng trống để chuyển khách.", parent=self.root)
            return
        self._form(f"Chuyển phòng • {room_id}", [("destination", "Phòng đích", available), ("days", "Ngày đã ở phòng hiện tại", "1"), ("actor", "Nhân viên thực hiện", ""), ("reason", "Lý do chuyển phòng", "")], lambda values: self._commit(lambda candidate: candidate.transfer_room(room_id, values["destination"], int(values["days"]), values["reason"], values["actor"]), f"Đã chuyển khách từ {room_id} sang {values['destination']}."), "Số ngày đã ở thuộc phân đoạn phòng hiện tại. Phải còn ít nhất một ngày cho phòng đích; giá và phí phòng đích áp dụng cho phân đoạn mới.")

    def open_checkout(self) -> None:
        room_id = self._selected(self.stay_tree)
        if room_id is None:
            return
        def submit(values: dict[str, str]) -> bool:
            try:
                quote = self.manager.quote_checkout(room_id, values["damage"], values["reason"] or None)
            except (HotelManagementError, ValueError) as error:
                messagebox.showerror("Chưa thể lập đối soát", str(error), parent=self.last_dialog)
                return False
            summary = (
                f"Tiền phòng: {format_money(quote.stay_charge)}\n"
                f"Cọc đang giữ: {format_money(quote.security_deposit)}\n"
                f"Bồi thường trừ cọc: {format_money(quote.damage_deduction)}\n"
                f"Hoàn cọc: {format_money(quote.deposit_refund)}\n\n"
                f"Thu tiền phòng: {format_money(quote.amount_to_collect)}\n"
                "Xác nhận đã thu tiền và hoàn cọc đúng số tiền trên?"
            )
            if not messagebox.askyesno("Xác nhận thanh toán", summary, parent=self.last_dialog):
                return False
            receipts: list[RevenueRecord] = []
            if self._commit(lambda candidate: receipts.append(candidate.checkout_room(room_id, quote)), f"Đã trả phòng {room_id} và lưu thanh toán."):
                self.show_receipt(receipts[0])
                return True
            return False
        self._form(f"Đối soát và trả phòng • {room_id}", [("damage", "Bồi thường trừ cọc (VND)", "0"), ("reason", "Lý do bồi thường", "")], submit, "Nhập 0 nếu không có thiệt hại. Màn hình tiếp theo hiển thị số tiền cần thu và cọc cần hoàn trước khi xác nhận.")

    def open_receipt(self) -> None:
        selected = self._selected(self.history_tree)
        if selected is not None:
            self.show_receipt(self.manager.revenue_history[int(selected)])

    def show_receipt(self, receipt: RevenueRecord) -> None:
        window = tk.Toplevel(self.root)
        window.title("Biên nhận thanh toán")
        window.geometry("700x570")
        text = tk.Text(window, wrap="word", font=("Segoe UI", 11), padx=24, pady=22, bg="white", fg="#18334c")
        text.pack(fill="both", expand=True)
        lines = ["HOTEL DESK — BIÊN NHẬN", "", f"Mã lưu trú: {receipt.rental_id}", f"Khách: {receipt.customer_name}", f"Thời điểm: {receipt.checked_out_at}", "", "CHI TIẾT TIỀN PHÒNG"]
        for line in receipt.charge_history:
            snapshot = line.price_snapshot
            lines.append(f"• {snapshot.room_id} — {snapshot.room_name}: {line.rental_days} ngày × {format_money(snapshot.base_price)}, phí {format_money(snapshot.cleaning_fee + snapshot.minibar_fee)} → {format_money(line.amount)}")
        lines += ["", f"Tổng tiền phòng: {format_money(receipt.stay_charge)}", f"Cọc đã nhận: {format_money(receipt.security_deposit)}", f"Bồi thường: {format_money(receipt.damage_charge)}", f"Cọc hoàn lại: {format_money(receipt.deposit_refund)}", f"Thu khi trả phòng: {format_money(receipt.amount_collected_at_checkout)}", f"Doanh thu ghi nhận: {format_money(receipt.total_amount)}"]
        if receipt.damage_charge > 0:
            lines.append(f"Lý do bồi thường: {receipt.damage_reason or 'Không có trong dữ liệu cũ'}")
        for transfer in receipt.transfer_history:
            lines.append(f"Chuyển {transfer.source_room_id} → {transfer.destination_room_id} | {transfer.actor} | {transfer.reason}")
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
        ttk.Button(window, text="Đóng", command=window.destroy).pack(pady=10)

    def close(self) -> None:
        try:
            self.manager.save()
        except DataFileError as error:
            messagebox.showerror("Chưa lưu được dữ liệu", str(error), parent=self.root)
            return
        self.root.destroy()


def run(storage_path: str | Path = DATA_FILE) -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        manager = HotelManager.load_from_file(storage_path)
    except (DataFileError, HotelManagementError) as error:
        messagebox.showerror("Không mở được dữ liệu", f"{error}\n\nHãy kiểm tra file dữ liệu trước khi mở lại ứng dụng.", parent=root)
        root.destroy()
        return
    HotelApplication(root, manager)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    run()
