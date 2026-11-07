"""
Sales CSV Converter (tkinter)

Form-style UI that takes an input file (CSV / TSV / TXT / JSON / XLSX) and
transforms it into a CSV with the header:

    date,product,quantity_sold

where `date` is always written as YYYY-MM-DD.

Only the standard library is required. Reading .xlsx files needs:
    pip install openpyxl
"""

import csv
import json
import os
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import filedialog, messagebox, ttk

try:
    import openpyxl
except ImportError:  # .xlsx support is optional
    openpyxl = None

OUTPUT_HEADER = ["date", "product", "quantity_sold"]

# ---------------------------------------------------------------- date parsing
YMD_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
    "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
]
DAY_FIRST_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"]
MONTH_FIRST_FORMATS = ["%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y"]

AUTO_LABEL = "Auto-detect"
DATE_FORMAT_CHOICES = [
    AUTO_LABEL,
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%b %d, %Y",
]


def parse_date(value, custom_format=None, day_first=True):
    """Return a `date` from many possible inputs, or raise ValueError."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Excel serial date number
        if 20000 < value < 80000:
            return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
        raise ValueError(f"Unrecognized date number: {value}")

    text = str(value).strip()
    if not text:
        raise ValueError("empty date")

    if custom_format:
        return datetime.strptime(text, custom_format).date()

    # Numeric string that looks like an Excel serial (e.g. "45123")
    if text.isdigit() and len(text) == 5:
        return parse_date(int(text))

    order = DAY_FIRST_FORMATS + MONTH_FIRST_FORMATS if day_first else MONTH_FIRST_FORMATS + DAY_FIRST_FORMATS
    for fmt in YMD_FORMATS + order:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date: {text!r}")


def parse_quantity(value):
    """Return an int (or float if fractional) from a messy value."""
    if value is None:
        raise ValueError("empty quantity")
    if isinstance(value, bool):
        raise ValueError("invalid quantity")
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        text = str(value).strip().replace(",", "").replace(" ", "")
        if not text:
            raise ValueError("empty quantity")
        num = float(text)
    return int(num) if num == int(num) else num


# ---------------------------------------------------------------- file reading
def read_table(path):
    """Read a file and return (headers, rows). Rows are lists of raw values."""
    ext = os.path.splitext(path)[1].lower()

    if ext in (".csv", ".tsv", ".txt"):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(8192)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel_tab if ext == ".tsv" else csv.excel
            data = [r for r in csv.reader(f, dialect) if any(c.strip() for c in r)]
        if not data:
            raise ValueError("The file is empty.")
        return [h.strip() for h in data[0]], data[1:]

    if ext == ".json":
        with open(path, "r", encoding="utf-8-sig") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            # accept {"data": [...]} / {"records": [...]} style wrappers
            lists = [v for v in obj.values() if isinstance(v, list)]
            obj = lists[0] if lists else [obj]
        if not obj or not isinstance(obj[0], dict):
            raise ValueError("JSON must be a list of objects.")
        headers = list(obj[0].keys())
        return headers, [[rec.get(h) for h in headers] for rec in obj]

    if ext in (".xlsx", ".xlsm"):
        if openpyxl is None:
            raise ValueError("Reading Excel files requires openpyxl:\n\n    pip install openpyxl")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        data = [list(r) for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
        wb.close()
        if not data:
            raise ValueError("The worksheet is empty.")
        return [str(h).strip() if h is not None else "" for h in data[0]], data[1:]

    raise ValueError(f"Unsupported file type: {ext or '(none)'}\nUse CSV, TSV, TXT, JSON or XLSX.")


# ---------------------------------------------------------------- transform
def transform(headers, rows, date_col, product_col, qty_col, custom_format, day_first):
    di, pi, qi = headers.index(date_col), headers.index(product_col), headers.index(qty_col)
    out, skipped = [], []

    def cell(row, i):
        return row[i] if i < len(row) else None

    for n, row in enumerate(rows, start=2):  # row 1 is the header
        try:
            d = parse_date(cell(row, di), custom_format, day_first)
            product = str(cell(row, pi) or "").strip()
            if not product:
                raise ValueError("empty product")
            q = parse_quantity(cell(row, qi))
            out.append([d.strftime("%Y-%m-%d"), product, q])
        except (ValueError, TypeError) as e:
            skipped.append((n, str(e)))
    return out, skipped


# ---------------------------------------------------------------- UI
KEYWORDS = {
    "date": ["date", "tanggal", "tgl", "day", "time"],
    "product": ["product", "produk", "item", "barang", "name", "sku", "description"],
    "qty": ["quantity", "qty", "sold", "jumlah", "units", "count", "amount"],
}


def guess_column(headers, key):
    for kw in KEYWORDS[key]:
        for h in headers:
            if kw in h.lower():
                return h
    return ""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sales CSV Converter")
        self.minsize(640, 560)

        self.headers, self.rows = [], []
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.date_col = tk.StringVar()
        self.product_col = tk.StringVar()
        self.qty_col = tk.StringVar()
        self.date_fmt = tk.StringVar(value=AUTO_LABEL)
        self.day_first = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Choose an input file to begin.")

        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)

        # --- Files
        files = ttk.LabelFrame(root, text="1. Files", padding=8)
        files.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        files.columnconfigure(1, weight=1)

        ttk.Label(files, text="Input file:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(files, text="Browse…", command=self.pick_input).grid(row=0, column=2, **pad)

        ttk.Label(files, text="Save CSV as:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(files, text="Browse…", command=self.pick_output).grid(row=1, column=2, **pad)

        # --- Column mapping
        mapping = ttk.LabelFrame(root, text="2. Map your columns", padding=8)
        mapping.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        mapping.columnconfigure(1, weight=1)

        self.combos = {}
        for r, (label, var, key) in enumerate([
            ("Date column  →  date", self.date_col, "date"),
            ("Product column  →  product", self.product_col, "product"),
            ("Quantity column  →  quantity_sold", self.qty_col, "qty"),
        ]):
            ttk.Label(mapping, text=label).grid(row=r, column=0, sticky="w", **pad)
            cb = ttk.Combobox(mapping, textvariable=var, state="readonly", values=[])
            cb.grid(row=r, column=1, sticky="ew", **pad)
            self.combos[key] = cb

        # --- Date options
        opts = ttk.LabelFrame(root, text="3. Date options", padding=8)
        opts.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        opts.columnconfigure(1, weight=1)

        ttk.Label(opts, text="Input date format:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Combobox(opts, textvariable=self.date_fmt, values=DATE_FORMAT_CHOICES).grid(
            row=0, column=1, sticky="ew", **pad)
        ttk.Checkbutton(
            opts, variable=self.day_first,
            text="Ambiguous dates like 03/04/2025 are day/month (uncheck for month/day)",
        ).grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(
            opts, foreground="gray",
            text="Output is always YYYY-MM-DD. You can type a custom strptime format, e.g. %d/%m/%Y.",
        ).grid(row=2, column=0, columnspan=2, sticky="w", **pad)

        # --- Buttons
        btns = ttk.Frame(root)
        btns.grid(row=3, column=0, sticky="e", pady=(0, 8))
        ttk.Button(btns, text="Preview", command=self.preview).pack(side="left", padx=4)
        ttk.Button(btns, text="Submit & Save CSV", command=self.submit).pack(side="left", padx=4)
        ttk.Button(btns, text="Reset", command=self.reset).pack(side="left", padx=4)

        # --- Preview table
        prev = ttk.LabelFrame(root, text="Preview (first 20 rows)", padding=8)
        prev.grid(row=4, column=0, sticky="nsew")
        root.rowconfigure(4, weight=1)
        prev.columnconfigure(0, weight=1)
        prev.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(prev, columns=OUTPUT_HEADER, show="headings", height=8)
        for c in OUTPUT_HEADER:
            self.tree.heading(c, text=c)
            self.tree.column(c, anchor="w", width=150)
        sb = ttk.Scrollbar(prev, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        ttk.Label(root, textvariable=self.status, anchor="w").grid(row=5, column=0, sticky="ew", pady=(8, 0))

    # ------------------------------------------------------------ actions
    def pick_input(self):
        path = filedialog.askopenfilename(
            title="Select input file",
            filetypes=[
                ("Supported files", "*.csv *.tsv *.txt *.json *.xlsx *.xlsm"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.input_var.set(path)
        base = os.path.splitext(path)[0]
        self.output_var.set(base + "_converted.csv")
        self.load_file(path)

    def pick_output(self):
        path = filedialog.asksaveasfilename(
            title="Save CSV as", defaultextension=".csv",
            filetypes=[("CSV file", "*.csv")],
            initialfile=os.path.basename(self.output_var.get() or "output.csv"),
        )
        if path:
            self.output_var.set(path)

    def load_file(self, path):
        try:
            self.headers, self.rows = read_table(path)
        except Exception as e:
            self.headers, self.rows = [], []
            messagebox.showerror("Could not read file", str(e))
            self.status.set("Failed to read file.")
            return

        for key, var in (("date", self.date_col), ("product", self.product_col), ("qty", self.qty_col)):
            self.combos[key]["values"] = self.headers
            var.set(guess_column(self.headers, key))
        self.status.set(f"Loaded {len(self.rows)} rows, {len(self.headers)} columns. Check the mapping below.")

    def _validate(self):
        if not self.input_var.get() or not self.headers:
            messagebox.showwarning("Missing input", "Please choose a valid input file first.")
            return False
        cols = [self.date_col.get(), self.product_col.get(), self.qty_col.get()]
        if not all(cols):
            messagebox.showwarning("Missing mapping", "Please map all three columns.")
            return False
        if len(set(cols)) < 3:
            messagebox.showwarning("Duplicate mapping", "Each output field needs a different source column.")
            return False
        return True

    def _run_transform(self):
        fmt = self.date_fmt.get().strip()
        custom = None if fmt in ("", AUTO_LABEL) else fmt
        return transform(
            self.headers, self.rows,
            self.date_col.get(), self.product_col.get(), self.qty_col.get(),
            custom, self.day_first.get(),
        )

    def preview(self):
        if not self._validate():
            return
        out, skipped = self._run_transform()
        self.tree.delete(*self.tree.get_children())
        for row in out[:20]:
            self.tree.insert("", "end", values=row)
        self.status.set(f"Preview: {len(out)} valid rows, {len(skipped)} would be skipped.")

    def submit(self):
        if not self._validate():
            return
        out_path = self.output_var.get().strip()
        if not out_path:
            messagebox.showwarning("Missing output", "Please choose where to save the CSV.")
            return

        out, skipped = self._run_transform()
        if not out:
            detail = "\n".join(f"Row {n}: {why}" for n, why in skipped[:5])
            messagebox.showerror(
                "Nothing to write",
                "No valid rows were produced. Check the column mapping and date format.\n\n" + detail,
            )
            return

        try:
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(OUTPUT_HEADER)
                writer.writerows(out)
        except OSError as e:
            messagebox.showerror("Could not save file", str(e))
            return

        self.tree.delete(*self.tree.get_children())
        for row in out[:20]:
            self.tree.insert("", "end", values=row)

        msg = f"Saved {len(out)} rows to:\n{out_path}"
        if skipped:
            lines = "\n".join(f"  Row {n}: {why}" for n, why in skipped[:8])
            more = f"\n  …and {len(skipped) - 8} more" if len(skipped) > 8 else ""
            msg += f"\n\nSkipped {len(skipped)} invalid row(s):\n{lines}{more}"
        self.status.set(f"Done. {len(out)} rows written, {len(skipped)} skipped.")
        messagebox.showinfo("Conversion complete", msg)

    def reset(self):
        self.headers, self.rows = [], []
        for v in (self.input_var, self.output_var, self.date_col, self.product_col, self.qty_col):
            v.set("")
        for cb in self.combos.values():
            cb["values"] = []
        self.date_fmt.set(AUTO_LABEL)
        self.day_first.set(True)
        self.tree.delete(*self.tree.get_children())
        self.status.set("Choose an input file to begin.")


if __name__ == "__main__":
    App().mainloop()
