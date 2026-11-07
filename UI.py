import csv
import os
import sys
import subprocess
import tempfile
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, TypedDict

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds


class ProductEntry(TypedDict):
    name: str
    demand: ttk.Entry
    price: ttk.Entry
    cost: ttk.Entry
    salvage: ttk.Entry


class SalesRow(TypedDict):
    date: datetime
    product: str
    quantity_sold: int


@dataclass
class ProductInfo:
    name: str
    forecast_demand: int = 0
    selling_price: int = 0
    unit_cost: int = 0
    salvage_value: int = 0


@dataclass
class OptimizationConfig:
    budget: int = 500_000
    capacity: int = 200
    uncertainty: float = 0.2
    risk_weight: float = 0.25


@dataclass
class OptimizationResult:
    plan: List[Dict[str, object]] = field(default_factory=list)
    total_production: int = 0
    total_capital_used: int = 0
    expected_profit: float = 0.0
    status: str = ""
    success: bool = False


REQUIRED_COLUMNS = {"date", "product", "quantity_sold"}

INF = float(np.inf)


def read_csv(file_path: str) -> List[SalesRow]:
    rows: List[SalesRow] = []
    for encoding in ("utf-8", "latin-1"):
        try:
            with open(file_path, newline="", encoding=encoding) as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(
                    set(reader.fieldnames)
                ):
                    raise ValueError(
                        f"CSV must contain columns: {', '.join(sorted(REQUIRED_COLUMNS))}"
                    )
                for raw in reader:
                    try:
                        date_str = str(raw["date"]).strip()
                        product = str(raw["product"]).strip()
                        qty = int(float(str(raw["quantity_sold"]).strip()))
                    except (ValueError, TypeError):
                        continue
                    if qty < 0:
                        qty = 0
                    rows.append(
                        {
                            "date": datetime.strptime(date_str, "%Y-%m-%d"),
                            "product": product,
                            "quantity_sold": qty,
                        }
                    )
            break
        except UnicodeDecodeError:
            continue
    if not rows:
        raise ValueError("No valid data rows found in the CSV file.")
    return rows


def aggregate_demand(rows: List[SalesRow]) -> Dict[str, int]:
    daily: Dict[str, Dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        daily[r["product"]][r["date"]] += r["quantity_sold"]

    all_dates = sorted({r["date"] for r in rows})
    first, last = all_dates[0], all_dates[-1]
    n_days = (last - first).days + 1
    next_x = float(n_days)

    demands: Dict[str, int] = {}
    for product, dates in daily.items():
        x = np.arange(n_days, dtype=float)
        y = np.array(
            [dates.get(first + timedelta(days=int(i)), 0) for i in x], dtype=float
        )
        if n_days < 3:
            demands[product] = int(round(y.mean()))
            continue

        slope, intercept = np.polyfit(x, y, 1)
        predicted = intercept + slope * next_x

        recent = y[-14:]
        lo, hi = recent.min(), recent.max()
        predicted = min(max(predicted, lo), hi)
        demands[product] = max(0, int(round(predicted)))
    return demands


def solve(products: List[ProductInfo], config: OptimizationConfig) -> OptimizationResult:
    n = len(products)
    if n == 0:
        return OptimizationResult(status="No products to optimise", success=False)

    lam = min(max(config.risk_weight, 0.0), 1.0)

    low_mult = max(0.0, 1.0 - config.uncertainty)
    high_mult = 1.0 + config.uncertainty
    scenario_specs = [
        ("Rendah", low_mult, 0.25),
        ("Normal", 1.0, 0.50),
        ("Tinggi", high_mult, 0.25),
    ]
    S = len(scenario_specs)

    num_vars = n + n * S * 2 + 1
    t_idx = num_vars - 1

    def var_idx_x(i: int) -> int:
        return i

    def var_idx_sold(s: int, i: int) -> int:
        return n + (s * n + i) * 2

    def var_idx_left(s: int, i: int) -> int:
        return n + (s * n + i) * 2 + 1

    c = np.zeros(num_vars)
    for i, p in enumerate(products):
        for s, (_, _, prob) in enumerate(scenario_specs):
            c[var_idx_sold(s, i)] += (1 - lam) * prob * p.selling_price
            c[var_idx_left(s, i)] += (1 - lam) * prob * p.salvage_value
            c[var_idx_x(i)] -= (1 - lam) * prob * p.unit_cost
    c[t_idx] = lam

    constraints: List[LinearConstraint] = []

    cost_row = np.zeros(num_vars)
    for i, p in enumerate(products):
        cost_row[var_idx_x(i)] = p.unit_cost
    constraints.append(LinearConstraint(cost_row, -INF, config.budget))

    cap_row = np.zeros(num_vars)
    for i in range(n):
        cap_row[var_idx_x(i)] = 1
    constraints.append(LinearConstraint(cap_row, -INF, config.capacity))

    for s in range(S):
        for i in range(n):
            link = np.zeros(num_vars)
            link[var_idx_x(i)] = 1
            link[var_idx_sold(s, i)] = -1
            link[var_idx_left(s, i)] = -1
            constraints.append(LinearConstraint(link, 0, 0))

            demand = max(0, round(products[i].forecast_demand * scenario_specs[s][1]))
            d_row = np.zeros(num_vars)
            d_row[var_idx_sold(s, i)] = 1
            constraints.append(LinearConstraint(d_row, -INF, demand))

    for s in range(S):
        row = np.zeros(num_vars)
        row[t_idx] = 1
        for i, p in enumerate(products):
            row[var_idx_sold(s, i)] -= p.selling_price
            row[var_idx_left(s, i)] -= p.salvage_value
            row[var_idx_x(i)] += p.unit_cost
        constraints.append(LinearConstraint(row, -INF, 0))

    lb = np.zeros(num_vars)
    lb[t_idx] = -INF
    ub = np.full(num_vars, INF)
    bounds = Bounds(**{"lb": lb, "ub": ub})

    integrality = np.ones(num_vars)
    integrality[t_idx] = 0

    res = milp(c=-c, constraints=constraints, bounds=bounds, integrality=integrality)

    if res.x is None:
        return OptimizationResult(
            status="No optimal solution found - check budget and capacity.",
            success=False,
        )

    plan: List[Dict[str, object]] = []
    total_production = 0
    total_capital = 0
    total_profit = 0.0

    for i, p in enumerate(products):
        qty = int(round(res.x[var_idx_x(i)]))
        exp_sold = sum(sp[2] * res.x[var_idx_sold(s, i)] for s, sp in enumerate(scenario_specs))
        exp_left = sum(sp[2] * res.x[var_idx_left(s, i)] for s, sp in enumerate(scenario_specs))
        exp_profit = (
            p.selling_price * exp_sold
            + p.salvage_value * exp_left
            - p.unit_cost * qty
        )

        plan.append(
            {
                "Produk": p.name,
                "Produksi": qty,
                "Perkiraan Terjual": round(exp_sold, 1),
                "Perkiraan Sisa": round(abs(exp_left), 1),
                "Perkiraan Laba (Rp)": round(exp_profit),
            }
        )
        total_production += qty
        total_capital += p.unit_cost * qty
        total_profit += exp_profit

    return OptimizationResult(
        plan=plan,
        total_production=total_production,
        total_capital_used=total_capital,
        expected_profit=total_profit,
        status="Optimal",
        success=True,
    )


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


class FieldError(Exception):
    def __init__(self, widget: ttk.Entry, message: str):
        super().__init__(message)
        self.widget = widget
        self.message = message


class CSVViewerApp:

    DEFAULT_PRICES = {
        "Roti Tawar": (8000, 4000),
        "Roti Cokelat": (8000, 4000),
        "Roti Keju": (10000, 6000),
        "Donat": (6000, 2500),
        "Croissant": (12000, 6000),
        "Eclair": (15000, 7000),
    }

    # key, label, hint, default
    CONSTRAINT_FIELDS = [
        ("budget", "Budget (Rp)", "Maximum total production cost", 500000),
        ("capacity", "Capacity (units)", "Maximum units produced in total", 200),
        ("uncertainty", "Demand uncertainty", "0 to 1 · ± range around forecast", 0.2),
        ("risk_weight", "Risk weight", "0 = maximise profit · 1 = protect worst case", 0.25),
    ]

    PRODUCT_HEADERS = [
        "Product",
        "Predicted demand",
        "Selling price (Rp)",
        "Unit cost (Rp)",
        "Salvage value (Rp)",
    ]

    RESULT_COLUMNS = ["Produk", "Produksi", "Perkiraan Terjual", "Perkiraan Sisa", "Perkiraan Laba (Rp)"]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("OptiMarket - CSV Reader & Production Optimizer")
        self.root.geometry("1100x750")
        self.root.minsize(900, 620)

        self.rows: list[SalesRow] = []
        self.products: list[ProductInfo] = []
        self.product_entries: list[ProductEntry] = []
        self.last_result: OptimizationResult | None = None
        self._sort_state: dict[tuple[int, str], bool] = {}
        self._entry_proc = None
        self._callback_file: Optional[str] = None

        self._setup_style()
        self._build_widgets()
        self._bind_shortcuts()

    def _setup_style(self):
        root = self.root
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

        # Buttons
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

        # Entries
        style.configure("TEntry", padding=6, fieldbackground="white", bordercolor=T.BORDER,
                        lightcolor=T.BORDER, darkcolor=T.BORDER)
        style.map("TEntry", bordercolor=[("focus", T.PRIMARY)],
                  lightcolor=[("focus", T.PRIMARY)], darkcolor=[("focus", T.PRIMARY)])
        style.configure("Invalid.TEntry", padding=6, fieldbackground=T.DANGER_BG, bordercolor=T.DANGER,
                        lightcolor=T.DANGER, darkcolor=T.DANGER)
        style.map("Invalid.TEntry", bordercolor=[("focus", T.DANGER)],
                  lightcolor=[("focus", T.DANGER)], darkcolor=[("focus", T.DANGER)])

        # Notebook
        style.configure("TNotebook", background=T.BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", padding=(20, 9), background="#E3E8F0",
                        foreground=T.MUTED, borderwidth=0, focuscolor="none")
        style.map("TNotebook.Tab",
                  background=[("selected", T.BG), ("active", "#EDF0F6")],
                  foreground=[("selected", T.PRIMARY)])

        # Treeview
        style.configure("Treeview", rowheight=int(30 * scale), background=T.SURFACE,
                        fieldbackground=T.SURFACE, foreground=T.TEXT, borderwidth=0)
        style.configure("Treeview.Heading", background="#EEF2F8", foreground=T.TEXT,
                        font=self.font_bold, padding=(8, 7), relief="flat")
        style.map("Treeview",
                  background=[("selected", T.SELECTED)], foreground=[("selected", T.TEXT)])
        style.map("Treeview.Heading", background=[("active", "#E1E8F4")])

        # Scrollbars
        for orient in ("Vertical", "Horizontal"):
            style.configure(f"{orient}.TScrollbar", background="#C9D0DB", troughcolor=T.BG,
                            borderwidth=0, arrowcolor=T.MUTED)
            style.map(f"{orient}.TScrollbar", background=[("active", "#AEB7C4")])

    def _card(self, parent, title: Optional[str] = None, subtitle: Optional[str] = None):
        """White bordered panel. Returns (outer, content, header_row)."""
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

    def _make_tree(self, parent):
        wrap = tk.Frame(parent, bg=T.SURFACE)
        tree = ttk.Treeview(wrap, show="headings", selectmode="browse")
        ys = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        xs = ttk.Scrollbar(wrap, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        tree.tag_configure("odd", background=T.ROW_ALT)
        tree.tag_configure("loss", foreground=T.DANGER)
        return wrap, tree

    @staticmethod
    def _tags(tree: ttk.Treeview, item: str) -> list[str]:
        tags = tree.item(item, "tags")
        if isinstance(tags, str):
            return [tags] if tags else []
        return list(tags)

    def _sort_tree(self, tree: ttk.Treeview, col: str):
        key_ = (id(tree), col)
        reverse = self._sort_state.get(key_, False)

        def sort_key(pair):
            text = pair[0].replace(",", "")
            try:
                return (0, float(text), "")
            except ValueError:
                return (1, 0.0, text.lower())

        items = [(tree.set(k, col), k) for k in tree.get_children("")]
        items.sort(key=sort_key, reverse=reverse)
        for idx, (_, k) in enumerate(items):
            tags = [t for t in self._tags(tree, k) if t != "odd"]
            if idx % 2:
                tags.append("odd")
            tree.move(k, "", idx)
            tree.item(k, tags=tags)
        self._sort_state[key_] = not reverse

    def set_status(self, message: str, level: str = "info"):
        color = {"info": T.MUTED, "success": T.SUCCESS, "error": T.DANGER}[level]
        self.status_var.set(message)
        self.status_icon.config(fg=color)

    @staticmethod
    def _reset_invalid(event):
        event.widget.configure(style="TEntry")

    @staticmethod
    def _select_all_later(event):
        event.widget.after(1, lambda w=event.widget: w.select_range(0, "end"))

    def _style_entry(self, entry: ttk.Entry):
        entry.bind("<Key>", self._reset_invalid, add="+")
        entry.bind("<FocusIn>", self._select_all_later, add="+")

    def _build_widgets(self):
        self._build_header()
        self._build_status_bar()

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=16, pady=(12, 8))

        self.nb = ttk.Notebook(body)
        self.nb.pack(fill="both", expand=True)

        self.tab_raw = ttk.Frame(self.nb, padding=(0, 14, 0, 0))
        self.tab_config = ttk.Frame(self.nb, padding=(0, 14, 0, 0))
        self.tab_result = ttk.Frame(self.nb, padding=(0, 14, 0, 0))
        self.nb.add(self.tab_raw, text="1 · Raw Data")
        self.nb.add(self.tab_config, text="2 · Configuration")
        self.nb.add(self.tab_result, text="3 · Results")

        self._build_raw_tab()
        self._build_config_tab()
        self._build_result_tab()

    def _build_header(self):
        bar = tk.Frame(self.root, bg=T.HEADER_BG)
        bar.pack(side="top", fill="x")
        inner = tk.Frame(bar, bg=T.HEADER_BG)
        inner.pack(fill="x", padx=16, pady=12)

        titles = tk.Frame(inner, bg=T.HEADER_BG)
        titles.pack(side="left")
        tk.Label(titles, text="OptiMarket", font=self.font_title, bg=T.HEADER_BG, fg="white").pack(anchor="w")
        tk.Label(titles, text="Load sales history, tune the assumptions, get an optimal production plan",
                 font=self.font_small, bg=T.HEADER_BG, fg=T.HEADER_MUTED).pack(anchor="w")

        right = tk.Frame(inner, bg=T.HEADER_BG)
        right.pack(side="right")
        ttk.Button(right, text="New Entry   Ctrl+N", style="Header.TButton",
                   command=self.open_entry_form).pack(side="right", padx=(8, 0))
        ttk.Button(right, text="Open CSV…   Ctrl+O", style="Header.TButton",
                   command=self.browse_file).pack(side="right")
        self.lbl_path = tk.Label(right, text="No file selected", fg=T.HEADER_MUTED,
                                 bg=T.HEADER_BG, anchor="e")
        self.lbl_path.pack(side="right", padx=(0, 14))

    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg=T.SURFACE, highlightbackground=T.BORDER, highlightthickness=1)
        bar.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar()
        self.status_icon = tk.Label(bar, text="●", bg=T.SURFACE, fg=T.MUTED, font=self.font_small)
        self.status_icon.pack(side="left", padx=(12, 6), pady=7)
        tk.Label(bar, textvariable=self.status_var, bg=T.SURFACE, fg=T.TEXT,
                 anchor="w").pack(side="left", fill="x", expand=True)
        self.set_status("Ready - open a CSV file to begin.")

    def _build_raw_tab(self):
        card, content, head = self._card(self.tab_raw, "Sales history")
        card.pack(fill="both", expand=True)

        self.raw_summary_var = tk.StringVar()
        tk.Label(head, textvariable=self.raw_summary_var, font=self.font_small,
                 bg=T.SURFACE, fg=T.MUTED).pack(side="left", padx=(10, 0))

        wrap, self.tree_raw = self._make_tree(content)
        wrap.pack(fill="both", expand=True)
        self.raw_empty = tk.Label(
            wrap,
            text="No data yet\nOpen a CSV with the columns  date, product, quantity_sold",
            font=self.font_empty, bg=T.SURFACE, fg=T.MUTED, justify="center",
        )
        self.raw_empty.place(relx=0.5, rely=0.45, anchor="center")

    def _build_config_tab(self):
        card, content, _ = self._card(self.tab_config, "Constraints",
                                      "Limits and risk preferences for the optimizer")
        card.pack(fill="x")

        self.constraint_vars: dict[str, tk.StringVar] = {}
        self.constraint_entries: dict[str, ttk.Entry] = {}
        n = len(self.CONSTRAINT_FIELDS)
        for col, (key, label, hint, default) in enumerate(self.CONSTRAINT_FIELDS):
            content.grid_columnconfigure(col, weight=1, uniform="constraint")
            cell = tk.Frame(content, bg=T.SURFACE)
            cell.grid(row=0, column=col, sticky="ew",
                      padx=(0 if col == 0 else 8, 8 if col < n - 1 else 0))
            ttk.Label(cell, text=label, style="Field.TLabel").pack(anchor="w")
            var = tk.StringVar(value=str(default))
            entry = ttk.Entry(cell, textvariable=var)
            entry.pack(fill="x", pady=(5, 3))
            self._style_entry(entry)
            ttk.Label(cell, text=hint, style="Muted.TLabel").pack(anchor="w")
            self.constraint_vars[key] = var
            self.constraint_entries[key] = entry

        pcard, pcontent, _ = self._card(self.tab_config, "Products",
                                        "Demand is forecast from your sales history - edit any value")
        pcard.pack(fill="both", expand=True, pady=(12, 0))

        # column headers (kept outside the scroll area so they stay visible)
        header = tk.Frame(pcontent, bg=T.SURFACE)
        header.pack(fill="x", pady=(0, 4))
        for c, text in enumerate(self.PRODUCT_HEADERS):
            header.grid_columnconfigure(c, weight=2 if c == 0 else 1, uniform="pcol")
            ttk.Label(header, text=text, style="Muted.TLabel",
                      anchor="w" if c == 0 else "e").grid(row=0, column=c, sticky="ew", padx=(0, 8) if c == 0 else 4)

        holder = tk.Frame(pcontent, bg=T.SURFACE)
        holder.pack(fill="both", expand=True)
        self.prod_canvas = tk.Canvas(holder, bg=T.SURFACE, highlightthickness=0, borderwidth=0)
        ys = ttk.Scrollbar(holder, orient="vertical", command=self.prod_canvas.yview)
        self.prod_canvas.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.prod_canvas.pack(side="left", fill="both", expand=True)
        header.grid_columnconfigure(len(self.PRODUCT_HEADERS), minsize=ys.winfo_reqwidth())

        self.product_rows_frame = tk.Frame(self.prod_canvas, bg=T.SURFACE)
        self._rows_window = self.prod_canvas.create_window((0, 0), window=self.product_rows_frame, anchor="nw")
        self.product_rows_frame.bind(
            "<Configure>", lambda e: self.prod_canvas.configure(scrollregion=self.prod_canvas.bbox("all"))
        )
        self.prod_canvas.bind(
            "<Configure>", lambda e: self.prod_canvas.itemconfigure(self._rows_window, width=e.width)
        )
        self.root.bind_all("<MouseWheel>", self._on_wheel, add="+")
        self.root.bind_all("<Button-4>", self._on_wheel, add="+")
        self.root.bind_all("<Button-5>", self._on_wheel, add="+")

        self.product_empty = tk.Label(
            self.product_rows_frame, text="Open a CSV to configure products",
            font=self.font_empty, bg=T.SURFACE, fg=T.MUTED, pady=40,
        )
        self.product_empty.pack(fill="x")

        actions = ttk.Frame(self.tab_config)
        actions.pack(fill="x", pady=(12, 0))
        self.btn_run = ttk.Button(actions, text="Run Optimization   F5", style="Accent.TButton",
                                  command=self.run_optimization, state="disabled")
        self.btn_run.pack(side="right")
        self.btn_reset = ttk.Button(actions, text="Reset values", command=self.reset_defaults,
                                    state="disabled")
        self.btn_reset.pack(side="right", padx=(0, 8))

    def _on_wheel(self, event):
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None and widget is not self.prod_canvas:
            widget = widget.master
        if widget is None:
            return
        if self.product_rows_frame.winfo_height() <= self.prod_canvas.winfo_height():
            return
        if event.num == 4:
            step = -1
        elif event.num == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.prod_canvas.yview_scroll(step, "units")

    def _build_result_tab(self):
        summary = ttk.Frame(self.tab_result)
        summary.pack(fill="x")
        self.metric_labels: list[tuple[tk.Label, ttk.Label]] = []
        names = ["Total production", "Capital used", "Expected profit"]
        for i, name in enumerate(names):
            summary.grid_columnconfigure(i, weight=1, uniform="metric")
            outer, content, _ = self._card(summary)
            outer.grid(row=0, column=i, sticky="ew",
                       padx=(0 if i == 0 else 6, 6 if i < len(names) - 1 else 0))
            ttk.Label(content, text=name.upper(), style="Muted.TLabel").pack(anchor="w")
            value = tk.Label(content, text="—", font=self.font_metric, bg=T.SURFACE, fg=T.TEXT)
            value.pack(anchor="w", pady=(2, 0))
            sub = ttk.Label(content, text=" ", style="Muted.TLabel")
            sub.pack(anchor="w")
            self.metric_labels.append((value, sub))

        card, content, head = self._card(self.tab_result, "Production plan", "Click a column header to sort")
        card.pack(fill="both", expand=True, pady=(12, 0))
        self.btn_export = ttk.Button(head, text="Export CSV", command=self.export_results, state="disabled")
        self.btn_export.pack(side="right")

        wrap, self.tree_result = self._make_tree(content)
        wrap.pack(fill="both", expand=True)
        self.result_empty = tk.Label(
            wrap, text="No results yet\nSet your assumptions and run the optimization",
            font=self.font_empty, bg=T.SURFACE, fg=T.MUTED, justify="center",
        )
        self.result_empty.place(relx=0.5, rely=0.45, anchor="center")

    def _bind_shortcuts(self):
        self.root.bind("<Control-o>", lambda e: self.browse_file())
        self.root.bind("<Control-n>", lambda e: self.open_entry_form())
        self.root.bind("<F5>", lambda e: self.run_optimization())
        self.root.bind("<Control-Return>", lambda e: self.run_optimization())

    def open_entry_form(self):
        if self._entry_proc is not None:
            poll = getattr(self._entry_proc, "poll", None)
            if poll and poll() is None:
                self.set_status("Sales entry form is already open.")
                return
        entry_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sales_entry_form.py")
        if not os.path.exists(entry_script):
            messagebox.showerror("Error", f"Cannot find sales_entry_form.py at:\n{entry_script}")
            return
        fd, self._callback_file = tempfile.mkstemp(suffix=".txt", prefix="optimarket_cb_")
        os.close(fd)
        with open(self._callback_file, "w") as f:
            f.write("")
        self._entry_proc = subprocess.Popen([sys.executable, entry_script, "--callback", self._callback_file])
        self.set_status("Sales entry form opened - save a CSV there to load it here automatically.")
        self.root.after(1000, self._poll_entry_form)

    def _poll_entry_form(self):
        if self._entry_proc is None:
            return
        rc = self._entry_proc.poll()
        loaded = False
        if self._callback_file and os.path.exists(self._callback_file):
            with open(self._callback_file, "r") as f:
                content = f.read().strip()
            if content:
                self._callback_file = None
                self._entry_proc = None
                self.load_csv(content)
                loaded = True
        if loaded:
            return
        if rc is not None:
            try:
                if self._callback_file:
                    os.unlink(self._callback_file)
            except OSError:
                pass
            self._callback_file = None
            self._entry_proc = None
            self.set_status("Sales entry form closed without saving.", "info")
            return
        self.root.after(1000, self._poll_entry_form)

    def browse_file(self):
        path = filedialog.askopenfilename(
            title="Select CSV File",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not path:
            return
        self.load_csv(path)

    def load_csv(self, file_path: str):
        name = os.path.basename(file_path)
        try:
            rows = read_csv(file_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read file:\n{e}")
            self.set_status(f"Failed to read {name}", "error")
            return

        self.rows = rows
        self.lbl_path.config(text=name, fg="white")
        self._populate_raw_table()
        self._populate_product_config()
        self._clear_results()
        self.btn_run.config(state="normal")
        self.btn_reset.config(state="normal")
        self.set_status(f"Loaded {len(self.rows):,} rows from {name} - review the data, then configure.", "success")

    def _populate_raw_table(self):
        tree = self.tree_raw
        tree.delete(*tree.get_children())
        headers = ["date", "product", "quantity_sold"]
        tree["columns"] = headers
        for h in headers:
            tree.heading(h, text=h.replace("_", " ").title(), anchor="w",
                         command=lambda c=h: self._sort_tree(tree, c))
            tree.column(h, width=200, anchor="e" if h == "quantity_sold" else "w", stretch=True)
        for i, row in enumerate(self.rows):
            tree.insert(
                "", "end",
                values=[row["date"].strftime("%Y-%m-%d"), row["product"], f"{row['quantity_sold']:,}"],
                tags=("odd",) if i % 2 else (),
            )
        self.raw_empty.place_forget()

        dates = [r["date"] for r in self.rows]
        n_products = len({r["product"] for r in self.rows})
        self.raw_summary_var.set(
            f"{len(self.rows):,} rows · {n_products} products · "
            f"{min(dates):%Y-%m-%d} → {max(dates):%Y-%m-%d}"
        )

    def _populate_product_config(self):
        for widget in self.product_rows_frame.winfo_children():
            widget.destroy()
        self.product_entries.clear()

        frame = self.product_rows_frame
        for c in range(len(self.PRODUCT_HEADERS)):
            frame.grid_columnconfigure(c, weight=2 if c == 0 else 1, uniform="pcol")

        demands = aggregate_demand(self.rows)
        for i, (product, demand) in enumerate(sorted(demands.items())):
            default_price, default_cost = self.DEFAULT_PRICES.get(product, (10000, 5000))

            ttk.Label(frame, text=product, style="Field.TLabel").grid(
                row=i, column=0, sticky="w", padx=(0, 8), pady=3)

            widgets = []
            for col, default in enumerate((demand, default_price, default_cost, 0), start=1):
                entry = ttk.Entry(frame, justify="right")
                entry.insert(0, str(default))
                entry.grid(row=i, column=col, sticky="ew", padx=4, pady=3)
                self._style_entry(entry)
                widgets.append(entry)

            entries: ProductEntry = {
                "name": product,
                "demand": widgets[0],
                "price": widgets[1],
                "cost": widgets[2],
                "salvage": widgets[3],
            }
            self.product_entries.append(entries)

        self.prod_canvas.yview_moveto(0)

    def reset_defaults(self):
        if not self.rows:
            return
        for key, _, _, default in self.CONSTRAINT_FIELDS:
            self.constraint_vars[key].set(str(default))
            self.constraint_entries[key].configure(style="TEntry")
        self._populate_product_config()
        self.set_status("Values reset to defaults and the latest forecast.")

    @staticmethod
    def _read_number(widget: ttk.Entry, label: str, cast=int, minimum=None, maximum=None, empty=None):
        text = widget.get().strip().replace(" ", "")
        text = text.replace(",", ".") if cast is float else text.replace(",", "")
        if text == "" and empty is not None:
            return empty
        try:
            value = cast(text)
        except ValueError:
            kind = "a whole number" if cast is int else "a number"
            raise FieldError(widget, f"{label}: enter {kind}") from None
        if minimum is not None and value < minimum:
            raise FieldError(widget, f"{label}: must be at least {minimum:g}")
        if maximum is not None and value > maximum:
            raise FieldError(widget, f"{label}: must be at most {maximum:g}")
        return value

    def run_optimization(self):
        if not self.rows:
            messagebox.showwarning("Warning", "Please load a CSV file first.")
            return

        errors: list[FieldError] = []

        def read(widget, label, **kw):
            try:
                return self._read_number(widget, label, **kw)
            except FieldError as err:
                widget.configure(style="Invalid.TEntry")
                errors.append(err)
                return 0

        ce = self.constraint_entries
        config = OptimizationConfig(
            budget=read(ce["budget"], "Budget", minimum=0),
            capacity=read(ce["capacity"], "Capacity", minimum=0),
            uncertainty=read(ce["uncertainty"], "Uncertainty", cast=float, minimum=0, maximum=1),
            risk_weight=read(ce["risk_weight"], "Risk weight", cast=float, minimum=0, maximum=1),
        )

        products: list[ProductInfo] = []
        for entries in self.product_entries:
            name = entries["name"]
            products.append(
                ProductInfo(
                    name=name,
                    forecast_demand=read(entries["demand"], f"{name} demand", minimum=0, empty=0),
                    selling_price=read(entries["price"], f"{name} price", minimum=0, empty=0),
                    unit_cost=read(entries["cost"], f"{name} cost", minimum=0, empty=0),
                    salvage_value=read(entries["salvage"], f"{name} salvage", minimum=0, empty=0),
                )
            )

        if errors:
            more = f"  (+{len(errors) - 1} more)" if len(errors) > 1 else ""
            self.set_status(errors[0].message + more, "error")
            first = errors[0].widget
            first.focus_set()
            return

        self.btn_run.config(state="disabled")
        self.root.config(cursor="watch")
        self.set_status("Optimizing…")
        self.root.update_idletasks()
        try:
            result = solve(products, config)
        except Exception as e:
            messagebox.showerror("Optimization Failed", str(e))
            self.set_status(f"Optimization failed: {e}", "error")
            return
        finally:
            self.root.config(cursor="")
            self.btn_run.config(state="normal")

        if not result.success:
            messagebox.showerror("Optimization Failed", result.status)
            self.set_status(result.status, "error")
            return

        self.last_result = result
        self._display_results(result, config)
        self.nb.select(self.tab_result)
        self.set_status(
            f"Optimization complete - {result.total_production:,} units, "
            f"expected profit Rp{result.expected_profit:,.0f}",
            "success",
        )

    def _clear_results(self):
        self.last_result = None
        self.tree_result.delete(*self.tree_result.get_children())
        for value, sub in self.metric_labels:
            value.config(text="—", fg=T.TEXT)
            sub.config(text=" ")
        self.result_empty.place(relx=0.5, rely=0.45, anchor="center")
        self.btn_export.config(state="disabled")

    @staticmethod
    def _format_cell(col: str, value) -> str:
        if col == "Produksi":
            return f"{int(value):,}"
        if col == "Perkiraan Laba (Rp)":
            return f"{value:,.0f}"
        if col in ("Perkiraan Terjual", "Perkiraan Sisa"):
            return f"{value:,.1f}"
        return str(value)

    def _display_results(self, result: OptimizationResult, config: OptimizationConfig):
        tree = self.tree_result
        tree.delete(*tree.get_children())
        cols = self.RESULT_COLUMNS
        tree["columns"] = cols
        for c in cols:
            tree.heading(c, text=c, anchor="w", command=lambda col=c: self._sort_tree(tree, col))
            tree.column(c, width=170, anchor="w" if c == "Produk" else "e", stretch=True)
        for i, row in enumerate(result.plan):
            tags = []
            if i % 2:
                tags.append("odd")
            if isinstance(row["Perkiraan Laba (Rp)"], (int, float)) and row["Perkiraan Laba (Rp)"] < 0:
                tags.append("loss")
            tree.insert("", "end", values=[self._format_cell(c, row[c]) for c in cols], tags=tags)
        self.result_empty.place_forget()
        self.btn_export.config(state="normal")

        cap_pct = result.total_production / config.capacity * 100 if config.capacity else 0
        bud_pct = result.total_capital_used / config.budget * 100 if config.budget else 0
        values = [
            (f"{result.total_production:,} units", f"{cap_pct:.0f}% of capacity ({config.capacity:,})", T.TEXT),
            (f"Rp{result.total_capital_used:,.0f}", f"{bud_pct:.0f}% of budget (Rp{config.budget:,})", T.TEXT),
            (
                f"Rp{result.expected_profit:,.0f}",
                f"Risk weight {config.risk_weight:g} · uncertainty ±{config.uncertainty * 100:.0f}%",
                T.SUCCESS if result.expected_profit >= 0 else T.DANGER,
            ),
        ]
        for (value_lbl, sub_lbl), (text, sub, color) in zip(self.metric_labels, values):
            value_lbl.config(text=text, fg=color)
            sub_lbl.config(text=sub)

    def export_results(self):
        if not self.last_result:
            return
        path = filedialog.asksaveasfilename(
            title="Export production plan",
            defaultextension=".csv",
            initialfile="production_plan.csv",
            filetypes=[("CSV Files", "*.csv")],
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=self.RESULT_COLUMNS)
                writer.writeheader()
                writer.writerows(self.last_result.plan)
        except OSError as e:
            messagebox.showerror("Error", f"Could not save file:\n{e}")
            return
        self.set_status(f"Exported plan to {os.path.basename(path)}", "success")


def main():
    try:  # crisp text on high-DPI Windows displays
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    CSVViewerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
