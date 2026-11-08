import calendar
import argparse
import csv
import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk
from typing import Optional

HEADER = ["tanggal", "produk", "jumlah_terjual"]

NAMA_BULAN = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
              "Agustus", "September", "Oktober", "November", "Desember"]
NAMA_HARI = ["Sn", "Sl", "Rb", "Km", "Jm", "Sb", "Mg"]


class Theme:
    BG = "#F3F5F9"
    SURFACE = "#FFFFFF"
    BORDER = "#DDE2EA"
    TEXT = "#1F2937"
    MUTED = "#6B7280"
    HEADER_BG = "#1E3A8A"
    HEADER_MUTED = "#BFD0FF"
    PRIMARY = "#2563EB"
    PRIMARY_HOVER = "#1D4ED8"
    PRIMARY_DISABLED = "#9DB8F2"
    ROW_ALT = "#F7F9FC"
    SELECTED = "#DBE7FF"
    DANGER = "#DC2626"
    DANGER_BG = "#FDE8E8"
    SUCCESS = "#15803D"


T = Theme


class QuantityRow:
    def __init__(self, parent, block, style_helper):
        self.block = block
        self.style_helper = style_helper
        self.frame = ttk.Frame(parent)
        self.qty = tk.StringVar()
        entry = ttk.Entry(self.frame, textvariable=self.qty, width=14, justify="right")
        entry.grid(row=0, column=0, padx=(0, 6), pady=2)
        self.style_helper.style_entry(entry)
        ttk.Button(self.frame, text="Hapus", width=10, command=self.remove).grid(row=0, column=2, pady=2)
        self.frame.pack(anchor="w")

    def remove(self):
        self.block.remove_row(self)


class ProductBlock:
    def __init__(self, parent, app, style_helper):
        self.app = app
        self.style_helper = style_helper
        self.rows = []
        self.product = tk.StringVar()

        self.frame = tk.Frame(parent, bg=T.SURFACE, highlightbackground=T.BORDER,
                              highlightthickness=1)
        body = tk.Frame(self.frame, bg=T.SURFACE, padx=16, pady=14)
        body.pack(fill="both", expand=True)
        self.frame.pack(fill="x", padx=4, pady=6)

        head = tk.Frame(body, bg=T.SURFACE)
        head.pack(fill="x", pady=(0, 10))
        tk.Label(head, text="Produk", font=(style_helper.font_bold[0], 11, "bold"),
                 bg=T.SURFACE, fg=T.TEXT).pack(side="left")
        entry = ttk.Entry(head, textvariable=self.product, width=34)
        entry.pack(side="left", padx=8)
        self.style_helper.style_entry(entry)
        ttk.Button(head, text="Hapus produk", command=self.remove).pack(side="right")

        indent = tk.Frame(body, bg=T.SURFACE)
        indent.pack(fill="x")

        titles = tk.Frame(indent, bg=T.SURFACE)
        titles.pack(anchor="w")
        ttk.Label(titles, text="Jumlah terjual", style="Muted.TLabel", width=14).grid(row=0, column=0, sticky="w")

        self.rows_frame = tk.Frame(indent, bg=T.SURFACE)
        self.rows_frame.pack(anchor="w")

        ttk.Button(indent, text="+ Tambah baris", command=self.add_row).pack(anchor="w", pady=(6, 0))

        self.add_row()

    def add_row(self):
        self.rows.append(QuantityRow(self.rows_frame, self, self.style_helper))

    def remove_row(self, row):
        if len(self.rows) == 1:
            row.qty.set("")
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
        self.title("Pilih tanggal")
        self.resizable(False, False)
        self.transient(parent)
        self.on_select = on_select
        self.selected = current
        self.year = current.year
        self.month = current.month

        self.configure(bg=T.SURFACE)

        nav = ttk.Frame(self, padding=8)
        nav.pack(fill="x")
        ttk.Button(nav, text="<<", width=3, command=lambda: self.shift_year(-1)).pack(side="left")
        ttk.Button(nav, text="<", width=3, command=lambda: self.shift_month(-1)).pack(side="left")
        self.header = ttk.Label(nav, anchor="center", font=(tkfont.nametofont("TkDefaultFont").actual("family"), 11, "bold"))
        self.header.pack(side="left", expand=True, fill="x", padx=6)
        ttk.Button(nav, text=">", width=3, command=lambda: self.shift_month(1)).pack(side="left")
        ttk.Button(nav, text=">>", width=3, command=lambda: self.shift_year(1)).pack(side="left")

        self.grid_frame = ttk.Frame(self, padding=(8, 0, 8, 4))
        self.grid_frame.pack()

        ttk.Button(self, text="Hari ini", command=self.pick_today).pack(pady=(0, 8))

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
        self.header.configure(text=f"{NAMA_BULAN[self.month]} {self.year}")

        for col, name in enumerate(NAMA_HARI):
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
                    bg=T.PRIMARY if is_selected else T.ROW_ALT,
                    fg="white" if is_selected else T.TEXT,
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


class StyleHelper:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.configure(bg=T.BG)

        available = set(tkfont.families(root))
        family = next(
            (f for f in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "Ubuntu", "DejaVu Sans") if f in available),
            tkfont.nametofont("TkDefaultFont").actual("family"),
        )
        for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(family=family, size=10)

        self.font = (family, 10)
        self.font_bold = (family, 10, "bold")
        self.font_small = (family, 9)
        self.font_title = (family, 18, "bold")
        self.font_metric = (family, 20, "bold")
        self.font_empty = (family, 11)

        scale = root.winfo_fpixels("1i") / 96
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure(".", font=self.font, background=T.BG, foreground=T.TEXT)
        style.configure("TFrame", background=T.BG)
        style.configure("Surface.TFrame", background=T.SURFACE)
        style.configure("TLabel", background=T.BG, foreground=T.TEXT)
        style.configure("Surface.TLabel", background=T.SURFACE, foreground=T.TEXT)
        style.configure("Field.TLabel", background=T.SURFACE, foreground=T.TEXT, font=self.font_bold)
        style.configure("Muted.TLabel", background=T.SURFACE, foreground=T.MUTED, font=self.font_small)

        style.configure("TButton", padding=(14, 7), background="#E5E9F0", foreground=T.TEXT,
                        borderwidth=0, focusthickness=0, focuscolor="none")
        style.map("TButton",
                  background=[("disabled", "#EEF0F4"), ("active", "#D5DBE6")],
                  foreground=[("disabled", "#9CA3AF")])
        style.configure("Accent.TButton", padding=(20, 10), background=T.PRIMARY,
                        foreground="white", font=self.font_bold)
        style.map("Accent.TButton",
                  background=[("disabled", T.PRIMARY_DISABLED), ("active", T.PRIMARY_HOVER)],
                  foreground=[("disabled", "white")])
        style.configure("Header.TButton", background="white", foreground=T.HEADER_BG, font=self.font_bold)
        style.map("Header.TButton", background=[("active", "#E0E7FF")])

        style.configure("TEntry", padding=6, fieldbackground="white", bordercolor=T.BORDER,
                        lightcolor=T.BORDER, darkcolor=T.BORDER)
        style.map("TEntry", bordercolor=[("focus", T.PRIMARY)],
                  lightcolor=[("focus", T.PRIMARY)], darkcolor=[("focus", T.PRIMARY)])
        style.configure("Invalid.TEntry", padding=6, fieldbackground=T.DANGER_BG, bordercolor=T.DANGER,
                        lightcolor=T.DANGER, darkcolor=T.DANGER)
        style.map("Invalid.TEntry", bordercolor=[("focus", T.DANGER)],
                  lightcolor=[("focus", T.DANGER)], darkcolor=[("focus", T.DANGER)])

        for orient in ("Vertical", "Horizontal"):
            style.configure(f"{orient}.TScrollbar", background="#C9D0DB", troughcolor=T.BG,
                            borderwidth=0, arrowcolor=T.MUTED)
            style.map(f"{orient}.TScrollbar", background=[("active", "#AEB7C4")])

    @staticmethod
    def _reset_invalid(event):
        event.widget.configure(style="TEntry")

    @staticmethod
    def _select_all_later(event):
        event.widget.after(1, lambda w=event.widget: w.select_range(0, "end"))

    def style_entry(self, entry: ttk.Entry):
        entry.bind("<Key>", self._reset_invalid, add="+")
        entry.bind("<FocusIn>", self._select_all_later, add="+")

    def card(self, parent, title: Optional[str] = None, subtitle: Optional[str] = None):
        outer = tk.Frame(parent, bg=T.SURFACE, highlightbackground=T.BORDER, highlightthickness=1)
        body = tk.Frame(outer, bg=T.SURFACE, padx=16, pady=14)
        body.pack(fill="both", expand=True)
        head = None
        if title:
            head = tk.Frame(body, bg=T.SURFACE)
            head.pack(fill="x", pady=(0, 10))
            tk.Label(head, text=title, font=(self.font_bold[0], 11, "bold"),
                     bg=T.SURFACE, fg=T.TEXT).pack(side="left")
            if subtitle:
                tk.Label(head, text=subtitle, font=self.font_small, bg=T.SURFACE,
                         fg=T.MUTED).pack(side="left", padx=(10, 0))
        content = tk.Frame(body, bg=T.SURFACE)
        content.pack(fill="both", expand=True)
        return outer, content, head


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Formulir Input Penjualan")
        self.geometry("700x680")
        self.minsize(600, 500)
        self.blocks = []
        self.date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.callback_file: Optional[str] = None

        self.style_helper = StyleHelper(self)
        self._build_header()
        self._build_status_bar()
        self._build_content()
        self.add_block()

    def _build_header(self):
        bar = tk.Frame(self, bg=T.HEADER_BG)
        bar.pack(side="top", fill="x")
        inner = tk.Frame(bar, bg=T.HEADER_BG)
        inner.pack(fill="x", padx=16, pady=12)

        titles = tk.Frame(inner, bg=T.HEADER_BG)
        titles.pack(side="left")
        tk.Label(titles, text="Input Penjualan", font=self.style_helper.font_title,
                 bg=T.HEADER_BG, fg="white").pack(anchor="w")
        tk.Label(titles, text="Catat transaksi penjualan harian untuk setiap produk",
                 font=self.style_helper.font_small, bg=T.HEADER_BG, fg=T.HEADER_MUTED).pack(anchor="w")

    def _build_status_bar(self):
        bar = tk.Frame(self, bg=T.SURFACE, highlightbackground=T.BORDER, highlightthickness=1)
        bar.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar()
        self.status_icon = tk.Label(bar, text="\u25CF", bg=T.SURFACE, fg=T.MUTED,
                                    font=self.style_helper.font_small)
        self.status_icon.pack(side="left", padx=(12, 6), pady=7)
        tk.Label(bar, textvariable=self.status_var, bg=T.SURFACE, fg=T.TEXT,
                 anchor="w").pack(side="left", fill="x", expand=True)
        self.set_status("Siap - isi formulir lalu simpan ke CSV.")

    def _build_content(self):
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=16, pady=(12, 8))

        top_card, top_content, _ = self.style_helper.card(body, "Tanggal")
        top_card.pack(fill="x")

        date_row = tk.Frame(top_content, bg=T.SURFACE)
        date_row.pack(fill="x")
        ttk.Label(date_row, text="Tanggal transaksi", style="Field.TLabel").pack(side="left")
        self.date_entry = ttk.Entry(date_row, textvariable=self.date_var, width=14,
                                    state="readonly", cursor="hand2")
        self.date_entry.pack(side="left", padx=8)
        self.date_entry.bind("<Button-1>", lambda e: self.open_calendar())
        ttk.Button(date_row, text="Pilih tanggal", command=self.open_calendar).pack(side="left")

        mid_card, mid_content, _ = self.style_helper.card(body, "Produk",
                                                           "Tambahkan blok produk untuk setiap barang yang terjual hari ini")
        mid_card.pack(fill="both", expand=True, pady=(12, 0))

        self.canvas = tk.Canvas(mid_content, bg=T.SURFACE, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(mid_content, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=T.SURFACE)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))

        self.bind_all("<MouseWheel>", self.on_wheel)
        self.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=16, pady=(0, 8))
        ttk.Button(actions, text="+ Tambah produk", command=self.add_block).pack(side="left")
        ttk.Button(actions, text="Bersihkan semua", command=self.clear).pack(side="left", padx=8)
        ttk.Button(actions, text="Kirim & Simpan CSV   Ctrl+S", style="Accent.TButton",
                   command=self.submit).pack(side="right")

        self.bind("<Control-s>", lambda e: self.submit())

    def set_status(self, message: str, level: str = "info"):
        color = {"info": T.MUTED, "success": T.SUCCESS, "error": T.DANGER}[level]
        self.status_var.set(message)
        self.status_icon.config(fg=color)

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
        self.blocks.append(ProductBlock(self.inner, self, self.style_helper))
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)

    def remove_block(self, block):
        if len(self.blocks) == 1:
            block.product.set("")
            for row in block.rows[1:]:
                block.remove_row(row)
            block.rows[0].qty.set("")
            return
        self.blocks.remove(block)
        block.destroy()

    def clear(self):
        if not messagebox.askyesno("Bersihkan semua", "Hapus semua isian di formulir?"):
            return
        for block in self.blocks:
            block.destroy()
        self.blocks = []
        self.date_var.set(datetime.now().strftime("%Y-%m-%d"))
        self.add_block()
        self.set_status("Formulir dibersihkan.")

    def collect(self):
        text = self.date_var.get().strip()
        try:
            date_text = datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError("Tanggal harus berformat YYYY-MM-DD, contoh 2026-11-07.")

        records = []
        for number, block in enumerate(self.blocks, start=1):
            product = block.product.get().strip()
            filled = [r for r in block.rows if r.qty.get().strip()]
            if not product and not filled:
                continue
            if not product:
                raise ValueError(f"Produk {number} memiliki jumlah tetapi belum ada nama produk.")
            if not filled:
                raise ValueError(f"Produk '{product}' belum memiliki jumlah terjual.")
            for r in filled:
                raw = r.qty.get().strip().replace(",", "")
                if not raw:
                    raise ValueError(f"Produk '{product}' memiliki baris tanpa jumlah.")
                try:
                    value = float(raw)
                except ValueError:
                    raise ValueError(f"Jumlah '{r.qty.get().strip()}' untuk '{product}' bukan angka.")
                if value < 0:
                    raise ValueError(f"Jumlah untuk '{product}' tidak boleh negatif.")
                quantity = int(value) if value == int(value) else value
                records.append([date_text, product, quantity])

        if not records:
            raise ValueError("Masukkan setidaknya satu produk beserta jumlahnya.")
        return records

    def submit(self):
        try:
            records = self.collect()
        except ValueError as error:
            messagebox.showwarning("Periksa isian Anda", str(error))
            self.set_status(str(error), "error")
            return

        path = filedialog.asksaveasfilename(
            title="Simpan CSV sebagai",
            defaultextension=".csv",
            filetypes=[("File CSV", "*.csv")],
            confirmoverwrite=False,
        )
        if not path:
            return

        mode, write_header = "w", True
        if os.path.exists(path) and os.path.getsize(path) > 0:
            answer = messagebox.askyesnocancel(
                "File sudah ada",
                "Tambahkan baris ini ke file yang ada?\n\nYa = tambahkan\nTidak = timpa\nBatal = batalkan",
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
            messagebox.showerror("Gagal menyimpan file", str(error))
            self.set_status(f"Gagal menyimpan: {error}", "error")
            return

        self.set_status(f"{len(records)} baris disimpan ke {os.path.basename(path)}", "success")
        messagebox.showinfo("Tersimpan", f"{len(records)} baris ditulis ke:\n{path}")
        cb = self.callback_file
        if cb is not None:
            try:
                with open(cb, "w") as f:
                    f.write(path)
            except OSError:
                pass


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--callback", help="Lokasi file untuk menulis path CSV yang tersimpan")
    args = parser.parse_args()
    app = App()
    if args.callback:
        app.callback_file = args.callback
    app.mainloop()


if __name__ == "__main__":
    main()
