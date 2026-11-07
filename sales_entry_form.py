import calendar
import csv
import os
import tkinter as tk
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk

HEADER = ["date", "product", "quantity_sold"]


class QuantityRow:
    def __init__(self, parent, block):
        self.block = block
        self.frame = ttk.Frame(parent)
        self.qty = tk.StringVar()
        # self.note = tk.StringVar()
        ttk.Entry(self.frame, textvariable=self.qty, width=14).grid(row=0, column=0, padx=(0, 6), pady=2)
        # ttk.Entry(self.frame, textvariable=self.note, width=36).grid(row=0, column=1, padx=(0, 6), pady=2)
        ttk.Button(self.frame, text="−", width=3, command=self.remove).grid(row=0, column=2, pady=2)
        self.frame.pack(anchor="w")

    def remove(self):
        self.block.remove_row(self)


class ProductBlock:
    def __init__(self, parent, app):
        self.app = app
        self.rows = []
        self.product = tk.StringVar()

        self.frame = ttk.Frame(parent, padding=10, relief="groove", borderwidth=2)
        self.frame.pack(fill="x", padx=4, pady=6)

        head = ttk.Frame(self.frame)
        head.pack(fill="x")
        ttk.Label(head, text="Product:", font=("TkDefaultFont", 10, "bold")).pack(side="left")
        ttk.Entry(head, textvariable=self.product, width=34).pack(side="left", padx=8)
        ttk.Button(head, text="Remove product", command=self.remove).pack(side="right")

        indent = ttk.Frame(self.frame, padding=(32, 8, 0, 0))
        indent.pack(fill="x")

        titles = ttk.Frame(indent)
        titles.pack(anchor="w")
        ttk.Label(titles, text="Quantity sold", width=14).grid(row=0, column=0, sticky="w")
        # ttk.Label(titles, text="Note", width=36).grid(row=0, column=1, sticky="w")

        self.rows_frame = ttk.Frame(indent)
        self.rows_frame.pack(anchor="w")

        ttk.Button(indent, text="+ Add row", command=self.add_row).pack(anchor="w", pady=(6, 0))

        self.add_row()

    def add_row(self):
        self.rows.append(QuantityRow(self.rows_frame, self))

    def remove_row(self, row):
        if len(self.rows) == 1:
            row.qty.set("")
            # row.note.set("")
            return
        self.rows.remove(row)
        row.frame.destroy()

    def remove(self):
        self.app.remove_block(self)

    def destroy(self):
        self.frame.destroy()


class CalendarPopup(tk.Toplevel):
    def __init__(self, parent, anchor, current, on_select):
        super().__init__(parent)
        self.title("Select date")
        self.resizable(False, False)
        self.transient(parent)
        self.on_select = on_select
        self.selected = current
        self.year = current.year
        self.month = current.month

        nav = ttk.Frame(self, padding=8)
        nav.pack(fill="x")
        ttk.Button(nav, text="«", width=3, command=lambda: self.shift_year(-1)).pack(side="left")
        ttk.Button(nav, text="‹", width=3, command=lambda: self.shift_month(-1)).pack(side="left")
        self.header = ttk.Label(nav, anchor="center", font=("TkDefaultFont", 11, "bold"))
        self.header.pack(side="left", expand=True, fill="x", padx=6)
        ttk.Button(nav, text="›", width=3, command=lambda: self.shift_month(1)).pack(side="left")
        ttk.Button(nav, text="»", width=3, command=lambda: self.shift_year(1)).pack(side="left")

        self.grid_frame = ttk.Frame(self, padding=(8, 0, 8, 4))
        self.grid_frame.pack()

        ttk.Button(self, text="Today", command=self.pick_today).pack(pady=(0, 8))

        self.draw()
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.focus_set()

    def shift_month(self, step):
        month = self.month + step
        year = self.year
        if month < 1:
            month, year = 12, year - 1
        elif month > 12:
            month, year = 1, year + 1
        self.year, self.month = year, month
        self.draw()

    def shift_year(self, step):
        self.year = max(1900, min(2200, self.year + step))
        self.draw()

    def draw(self):
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.header.configure(text=f"{calendar.month_name[self.month]} {self.year}")

        for col, name in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            ttk.Label(self.grid_frame, text=name, width=4, anchor="center").grid(row=0, column=col, pady=(0, 2))

        today = date.today()
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(self.year, self.month)
        for r, week in enumerate(weeks, start=1):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                current = date(self.year, self.month, day)
                is_selected = current == self.selected
                is_today = current == today
                button = tk.Button(
                    self.grid_frame,
                    text=str(day),
                    width=4,
                    relief="solid" if is_today else "flat",
                    bd=1 if is_today else 0,
                    bg="#2563eb" if is_selected else "#f3f4f6",
                    fg="white" if is_selected else "black",
                    activebackground="#93c5fd",
                    cursor="hand2",
                    command=lambda d=day: self.choose(d),
                )
                button.grid(row=r, column=c, padx=1, pady=1)

    def choose(self, day):
        self.on_select(date(self.year, self.month, day))
        self.destroy()

    def pick_today(self):
        self.on_select(date.today())
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sales Entry Form")
        self.geometry("640x620")
        self.minsize(560, 460)
        self.blocks = []
        self.date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.build()
        self.add_block()

    def build(self):
        top = ttk.Frame(self, padding=(12, 12, 12, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Date:", font=("TkDefaultFont", 10, "bold")).pack(side="left")
        self.date_entry = ttk.Entry(top, textvariable=self.date_var, width=14, state="readonly", cursor="hand2")
        self.date_entry.pack(side="left", padx=8)
        self.date_entry.bind("<Button-1>", lambda e: self.open_calendar())
        ttk.Button(top, text="📅 Pick date", command=self.open_calendar).pack(side="left")

        middle = ttk.Frame(self, padding=(12, 4))
        middle.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(middle, highlightthickness=0)
        scroll = ttk.Scrollbar(middle, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))

        self.bind_all("<MouseWheel>", self.on_wheel)
        self.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        bottom = ttk.Frame(self, padding=12)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="+ Add product", command=self.add_block).pack(side="left")
        ttk.Button(bottom, text="Clear all", command=self.clear).pack(side="left", padx=8)
        ttk.Button(bottom, text="Submit & Save CSV", command=self.submit).pack(side="right")

    def open_calendar(self):
        if getattr(self, "popup", None) is not None and self.popup.winfo_exists():
            self.popup.lift()
            return
        try:
            current = datetime.strptime(self.date_var.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            current = date.today()
        self.popup = CalendarPopup(self, self.date_entry, current, self.set_date)

    def set_date(self, chosen):
        self.date_var.set(chosen.strftime("%Y-%m-%d"))

    def on_wheel(self, event):
        step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")

    def add_block(self):
        self.blocks.append(ProductBlock(self.inner, self))
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)

    def remove_block(self, block):
        if len(self.blocks) == 1:
            block.product.set("")
            for row in block.rows[1:]:
                block.remove_row(row)
            block.rows[0].qty.set("")
            # block.rows[0].note.set("")
            return
        self.blocks.remove(block)
        block.destroy()

    def clear(self):
        if not messagebox.askyesno("Clear all", "Remove everything entered in the form?"):
            return
        for block in self.blocks:
            block.destroy()
        self.blocks = []
        self.date_var.set(datetime.now().strftime("%Y-%m-%d"))
        self.add_block()

    def collect(self):
        text = self.date_var.get().strip()
        try:
            date_text = datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be in YYYY-MM-DD format, for example 2026-11-07.")

        records = []
        for number, block in enumerate(self.blocks, start=1):
            product = block.product.get().strip()
            filled = [r for r in block.rows if r.qty.get().strip()] # or r.note.get().strip()]
            if not product and not filled:
                continue
            if not product:
                raise ValueError(f"Product {number} has quantities but no product name.")
            if not filled:
                raise ValueError(f"Product '{product}' has no quantity rows.")
            for r in filled:
                raw = r.qty.get().strip().replace(",", "")
                if not raw:
                    raise ValueError(f"Product '{product}' has a row with a note but no quantity.")
                try:
                    value = float(raw)
                except ValueError:
                    raise ValueError(f"Quantity '{r.qty.get().strip()}' for '{product}' is not a number.")
                if value < 0:
                    raise ValueError(f"Quantity for '{product}' cannot be negative.")
                quantity = int(value) if value == int(value) else value
                records.append([date_text, product, quantity])

        if not records:
            raise ValueError("Enter at least one product with a quantity.")
        return records

    def submit(self):
        try:
            records = self.collect()
        except ValueError as error:
            messagebox.showwarning("Check your entries", str(error))
            return

        path = filedialog.asksaveasfilename(
            title="Save CSV as",
            defaultextension=".csv",
            filetypes=[("CSV file", "*.csv")],
            confirmoverwrite=False,
        )
        if not path:
            return

        mode, write_header = "w", True
        if os.path.exists(path) and os.path.getsize(path) > 0:
            answer = messagebox.askyesnocancel(
                "File already exists",
                "Append these rows to the existing file?\n\nYes = append\nNo = overwrite\nCancel = abort",
            )
            if answer is None:
                return
            if answer:
                mode, write_header = "a", False

        try:
            with open(path, mode, encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(HEADER)
                writer.writerows(records)
        except OSError as error:
            messagebox.showerror("Could not save file", str(error))
            return

        messagebox.showinfo("Saved", f"{len(records)} row(s) written to:\n{path}")


if __name__ == "__main__":
    App().mainloop()