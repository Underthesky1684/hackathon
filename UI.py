import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, TypedDict

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds


class ProductEntry(TypedDict):
    name: str
    demand: tk.Entry
    price: tk.Entry
    cost: tk.Entry
    salvage: tk.Entry


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


class CSVViewerApp:

    DEFAULT_PRICES = {
        "Roti Tawar": (8000, 4000),
        "Roti Cokelat": (8000, 4000),
        "Roti Keju": (10000, 6000),
        "Donat": (6000, 2500),
        "Croissant": (12000, 6000),
        "Eclair": (15000, 7000),
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("OptiMarket - CSV Reader & Production Optimizer")
        self.root.geometry("1100x750")

        self.rows: list[SalesRow] = []
        self.products: list[ProductInfo] = []
        self.product_entries: list[ProductEntry] = []

        self._build_widgets()

    def _build_widgets(self):
        top = tk.Frame(self.root, padx=10, pady=5)
        top.pack(side="top", fill="x")

        tk.Button(top, text="Browse CSV", command=self.browse_file, width=15).pack(side="left")
        self.lbl_path = tk.Label(top, text="No file selected", fg="gray", anchor="w")
        self.lbl_path.pack(side="left", padx=10, fill="x", expand=True)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=5)

        self.tab_raw = ttk.Frame(nb)
        self.tab_config = ttk.Frame(nb)
        self.tab_result = ttk.Frame(nb)
        nb.add(self.tab_raw, text="Raw Data")
        nb.add(self.tab_config, text="Configuration")
        nb.add(self.tab_result, text="Results")

        self._build_raw_tab()
        self._build_config_tab()
        self._build_result_tab()

        self.status_var = tk.StringVar(value="Ready - load a CSV to begin.")
        tk.Label(self.root, textvariable=self.status_var, anchor="w", bd=1, relief="sunken").pack(side="bottom", fill="x")

    def _build_raw_tab(self):
        frame = tk.Frame(self.tab_raw)
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.tree_raw = ttk.Treeview(frame)
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.tree_raw.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=self.tree_raw.xview)
        self.tree_raw.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.tree_raw.pack(side="left", fill="both", expand=True)

    def _build_config_tab(self):
        constraints = tk.LabelFrame(self.tab_config, text="Constraints", padx=10, pady=10)
        constraints.pack(fill="x", padx=10, pady=5)

        labels_defs = [
            ("Budget (Rp):", "budget", 500000),
            ("Capacity (units):", "capacity", 200),
            ("Uncertainty:", "uncertainty", 0.2),
            ("Risk weight:", "risk_weight", 0.25),
        ]
        self.constraint_vars: dict[str, tk.StringVar] = {}
        for col, (label, key, default) in enumerate(labels_defs):
            r, c = divmod(col, 3)
            tk.Label(constraints, text=label).grid(row=r, column=c * 2, sticky="w", padx=5, pady=3)
            var = tk.StringVar(value=str(default))
            entry = tk.Entry(constraints, textvariable=var, width=15)
            entry.grid(row=r, column=c * 2 + 1, padx=5, pady=3)
            self.constraint_vars[key] = var

        prod_frame = tk.LabelFrame(self.tab_config, text="Product Configuration", padx=10, pady=10)
        prod_frame.pack(fill="both", expand=True, padx=10, pady=5)

        headers = ["Product", "Predicted Demand", "Selling Price (Rp)", "Unit Cost (Rp)", "Salvage Value (Rp)"]
        for c, h in enumerate(headers):
            tk.Label(prod_frame, text=h, font=("Segoe UI", 9, "bold")).grid(row=0, column=c, padx=5, pady=(0, 5))

        self.product_rows_frame = tk.Frame(prod_frame)
        self.product_rows_frame.grid(row=1, column=0, columnspan=len(headers))

        tk.Button(
            self.tab_config, text="Run Optimization", command=self.run_optimization,
            bg="#4CAF50", fg="white", font=("Segoe UI", 11, "bold"), height=2
        ).pack(pady=10)

    def _build_result_tab(self):
        frame = tk.Frame(self.tab_result)
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.tree_result = ttk.Treeview(frame)
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.tree_result.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=self.tree_result.xview)
        self.tree_result.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.tree_result.pack(side="left", fill="both", expand=True)

        self.summary_frame = tk.Frame(self.tab_result)
        self.summary_frame.pack(fill="x", padx=10, pady=5)

    def browse_file(self):
        path = filedialog.askopenfilename(
            title="Select CSV File",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not path:
            return
        self.load_csv(path)

    def load_csv(self, file_path: str):
        try:
            self.rows = read_csv(file_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read file:\n{e}")
            return

        self.lbl_path.config(text=file_path, fg="black")
        self._populate_raw_table()
        self._populate_product_config()
        self.status_var.set(f"Loaded {len(self.rows)} rows from {file_path.split('/')[-1]}")

    def _populate_raw_table(self):
        self.tree_raw.delete(*self.tree_raw.get_children())
        headers = ["date", "product", "quantity_sold"]
        self.tree_raw["columns"] = headers
        self.tree_raw["show"] = "headings"
        for h in headers:
            self.tree_raw.heading(h, text=h)
            self.tree_raw.column(h, width=200, anchor="w")
        for row in self.rows:
            self.tree_raw.insert(
                "", "end",
                values=[row["date"].strftime("%Y-%m-%d"), row["product"], row["quantity_sold"]],
            )

    def _populate_product_config(self):
        for widget in self.product_rows_frame.winfo_children():
            widget.destroy()
        self.product_entries.clear()

        demands = aggregate_demand(self.rows)

        for i, (product, demand) in enumerate(sorted(demands.items())):
            default_price, default_cost = self.DEFAULT_PRICES.get(product, (10000, 5000))

            tk.Label(self.product_rows_frame, text=product).grid(row=i, column=0, padx=5, pady=2, sticky="w")

            entry_fc = tk.Entry(self.product_rows_frame, width=15)
            entry_fc.insert(0, str(demand))
            entry_fc.grid(row=i, column=1, padx=5, pady=2)

            entry_price = tk.Entry(self.product_rows_frame, width=15)
            entry_price.insert(0, str(default_price))
            entry_price.grid(row=i, column=2, padx=5, pady=2)

            entry_cost = tk.Entry(self.product_rows_frame, width=15)
            entry_cost.insert(0, str(default_cost))
            entry_cost.grid(row=i, column=3, padx=5, pady=2)

            entry_salvage = tk.Entry(self.product_rows_frame, width=15)
            entry_salvage.insert(0, "0")
            entry_salvage.grid(row=i, column=4, padx=5, pady=2)

            entries: ProductEntry = {
                "name": product,
                "demand": entry_fc,
                "price": entry_price,
                "cost": entry_cost,
                "salvage": entry_salvage,
            }

            self.product_entries.append(entries)

    def run_optimization(self):
        if not self.rows:
            messagebox.showwarning("Warning", "Please load a CSV file first.")
            return

        try:
            config = OptimizationConfig(
                budget=int(self.constraint_vars["budget"].get()),
                capacity=int(self.constraint_vars["capacity"].get()),
                uncertainty=float(self.constraint_vars["uncertainty"].get()),
                risk_weight=float(self.constraint_vars["risk_weight"].get()),
            )
        except ValueError:
            messagebox.showerror("Error", "Invalid constraint values. Please enter numbers.")
            return

        products: list[ProductInfo] = []
        for entries in self.product_entries:
            try:
                products.append(
                    ProductInfo(
                        name=entries["name"],
                        forecast_demand=int(entries["demand"].get() or 0),
                        selling_price=int(entries["price"].get() or 0),
                        unit_cost=int(entries["cost"].get() or 0),
                        salvage_value=int(entries["salvage"].get() or 0),
                    )
                )
            except ValueError:
                messagebox.showerror("Error", "Invalid product values. Please enter numbers only.")
                return

        result = solve(products, config)

        if not result.success:
            messagebox.showerror("Optimization Failed", result.status)
            self.status_var.set(result.status)
            return

        self._display_results(result)
        self.status_var.set(
            f"Optimization complete - {result.total_production} units, "
            f"expected profit Rp{result.expected_profit:,.0f}"
        )

    def _display_results(self, result: OptimizationResult):
        self.tree_result.delete(*self.tree_result.get_children())
        cols = ["Produk", "Produksi", "Perkiraan Terjual", "Perkiraan Sisa", "Perkiraan Laba (Rp)"]
        self.tree_result["columns"] = cols
        self.tree_result["show"] = "headings"
        for c in cols:
            self.tree_result.heading(c, text=c)
            self.tree_result.column(c, width=180, anchor="w")
        for row in result.plan:
            self.tree_result.insert("", "end", values=[row[c] for c in cols])

        for widget in self.summary_frame.winfo_children():
            widget.destroy()

        metrics = [
            ("Total Production", f"{result.total_production:,} units"),
            ("Capital Used", f"Rp{result.total_capital_used:,.0f}"),
            ("Expected Profit", f"Rp{result.expected_profit:,.0f}"),
        ]
        for i, (label, value) in enumerate(metrics):
            card = tk.Frame(self.summary_frame, relief="groove", bd=1, padx=15, pady=10)
            card.grid(row=0, column=i, padx=10, pady=5, sticky="ew")
            tk.Label(card, text=label, font=("Segoe UI", 9)).pack()
            tk.Label(card, text=value, font=("Segoe UI", 14, "bold")).pack()


def main():
    root = tk.Tk()
    CSVViewerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
