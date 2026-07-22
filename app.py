"""
CLE3 Productive Time Dashboard
Double-click run.bat or the Desktop shortcut to launch.
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import threading, webbrowser, os, sys, json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import processor, fclm
try:
    import vantage as _vantage
except ImportError:
    _vantage = None
try:
    import updater as _updater
except ImportError:
    _updater = None
try:
    import bmi as _bmi
except ImportError:
    _bmi = None

_CFG = fclm._CONFIG  # shared config (warehouse, pt_target, etc.)

# ── Colors ────────────────────────────────────────────────────
BG      = "#0f1117"
CARD    = "#1a1d27"
BORDER  = "#2a2d3a"
ACCENT  = "#ff9900"
TEXT    = "#e8eaf0"
MUTED   = "#7a7f96"
C_RED   = "#e05260"
C_ORA   = "#f59e0b"
C_LGR   = "#4ade80"
C_DGR   = "#16a34a"

def pt_color(pt):
    if pt is None:  return MUTED
    if pt < 80:     return C_RED
    if pt < 85:     return C_ORA
    if pt < 90:     return C_LGR
    return C_DGR

def pt_tag(pt):
    if pt is None:  return "na"
    if pt < 80:     return "red"
    if pt < 85:     return "orange"
    if pt < 90:     return "lgreen"
    return "dgreen"

def pt_str(pt):
    return f"{pt:.1f}%" if pt is not None else "””"

# ── ttk dark style ────────────────────────────────────────────
def apply_tree_style():
    s = ttk.Style()
    s.theme_use("clam")
    for name in ("Dark.Treeview", "Compact.Treeview"):
        s.configure(name,
            background=CARD, foreground=TEXT, fieldbackground=CARD,
            borderwidth=0, rowheight=28, font=("Segoe UI", 10))
        s.configure(f"{name}.Heading",
            background="#12141e", foreground=MUTED,
            font=("Segoe UI", 9, "bold"), relief="flat")
        s.map(name,
            background=[("selected", BORDER)],
            foreground=[("selected", TEXT)])
        s.map(f"{name}.Heading",
            background=[("active", "#12141e")])

# ── Main App ──────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title("CLE3 Productive Time Dashboard")
        self.geometry("1280x820")
        self.minsize(1000, 640)
        self.configure(fg_color=BG)
        apply_tree_style()

        self._data       = {}   # date_key → processed data
        self._last_url   = ""
        self._build_ui()
        self._check_for_updates()

    # ─────────────────────────────────────────────────────────
    # Auto-load last 7 PM report snapshot
    # ─────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────
    # UI Construction
    # ─────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_topbar()
        self._build_controls()
        self._cards_frame = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._cards_frame.pack(fill="x", padx=18, pady=(12, 0))
        self._build_tabs()

    def _build_topbar(self):
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=52)
        bar.pack(fill="x"); bar.pack_propagate(False)
        ctk.CTkLabel(bar, text="●", text_color=ACCENT,
                     font=ctk.CTkFont(size=20)).pack(side="left", padx=(14,6), pady=0)
        ctk.CTkLabel(bar, text="CLE3 · Productive Time Dashboard",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT).pack(side="left")
        self._status_var = tk.StringVar(value="Select a date and shift, then click Get Data.")
        ctk.CTkLabel(bar, textvariable=self._status_var,
                     font=ctk.CTkFont(size=12), text_color=MUTED,
                     wraplength=600).pack(side="left", padx=20)
        self._open_btn = ctk.CTkButton(bar, text="Open in FCLM",
                                        command=self._open_fclm,
                                        width=120, height=30,
                                        fg_color=BORDER, hover_color="#3a3d4a",
                                        text_color=MUTED,
                                        font=ctk.CTkFont(size=11))
        self._open_btn.pack(side="right", padx=14)

    def _build_controls(self):
        bar = ctk.CTkFrame(self, fg_color="#12141e", corner_radius=0, height=50)
        bar.pack(fill="x"); bar.pack_propagate(False)

        def lbl(text): 
            ctk.CTkLabel(bar, text=text, text_color=MUTED,
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=(14,3))

        lbl("Date:")
        self._date_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
        ctk.CTkEntry(bar, textvariable=self._date_var, width=108,
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0,10))

        lbl("Shift:")
        self._shift_var = tk.StringVar(value="All Day")
        ctk.CTkOptionMenu(bar, variable=self._shift_var,
                          values=list(fclm.SHIFTS.keys()),
                          width=160, font=ctk.CTkFont(size=11),
                          fg_color=CARD, button_color=BORDER,
                          button_hover_color="#3a3d4a",
                          dropdown_fg_color=CARD).pack(side="left", padx=(0,10))

        lbl("Warehouse:")
        self._wh_var = tk.StringVar(value=_CFG.get("warehouse_id", "CLE3"))
        ctk.CTkEntry(bar, textvariable=self._wh_var, width=70,
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0,14))

        self._fetch_btn = ctk.CTkButton(bar, text="Get Data",
                                         command=self._on_fetch,
                                         width=100, height=32,
                                         fg_color=ACCENT, hover_color="#cc7a00",
                                         text_color="black",
                                         font=ctk.CTkFont(size=12, weight="bold"))
        self._fetch_btn.pack(side="left")

        self._auto_btn = ctk.CTkButton(bar, text="⟳ Auto",
                                        command=self._toggle_autorefresh,
                                        width=80, height=32,
                                        fg_color=BORDER, hover_color="#3a3d4a",
                                        text_color=MUTED,
                                        font=ctk.CTkFont(size=11))
        self._auto_btn.pack(side="left", padx=(6, 0))

        # Threshold
        lbl("Flag below:")
        self._thresh_var = tk.StringVar(value=str(_CFG.get("pt_target", 84)))
        ctk.CTkOptionMenu(bar, variable=self._thresh_var,
                          values=["80","82","84","85","87","90"],
                          width=65, font=ctk.CTkFont(size=11),
                          fg_color=CARD, button_color=BORDER,
                          button_hover_color="#3a3d4a",
                          dropdown_fg_color=CARD,
                          command=lambda _: self._refresh_flagged()).pack(side="left")
        ctk.CTkLabel(bar, text="%", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(2,0))

        # Color legend
        for color, label in [(C_DGR,"≥90%"),(C_LGR,"85-89%"),(C_ORA,"80-84%"),(C_RED,"<80%")]:
            ctk.CTkLabel(bar, text="■", text_color=color,
                         font=ctk.CTkFont(size=14)).pack(side="right", padx=(0,2))
            ctk.CTkLabel(bar, text=label, text_color=MUTED,
                         font=ctk.CTkFont(size=10)).pack(side="right", padx=(8,0))

    def _build_tabs(self):
        self._tab = ctk.CTkTabview(self, fg_color=CARD,
                                    segmented_button_fg_color=CARD,
                                    segmented_button_selected_color=ACCENT,
                                    segmented_button_selected_hover_color="#cc7a00",
                                    segmented_button_unselected_color=CARD,
                                    segmented_button_unselected_hover_color=BORDER,
                                    text_color=TEXT, border_width=1, border_color=BORDER)
        self._tab.pack(fill="both", expand=True, padx=18, pady=(10,14))

        for name in ["AM Rankings", "Flagged Associates", "Week-over-Week", "Stow Rates"]:
            self._tab.add(name)
            self._tab.tab(name).configure(fg_color=BG)

        self._build_am_tab()
        self._build_flagged_tab()
        self._build_wow_tab()
        self._build_stow_tab()

    # ── AM Rankings Tab ───────────────────────────────────────
    def _build_am_tab(self):
        parent = self._tab.tab("AM Rankings")
        cols = ("Rank", "Area Manager", "Team PT%", "Inferred Hrs", "Total Hrs", "AAs", "Flagged")

        f = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        f.pack(fill="both", expand=True, padx=4, pady=4)

        hint = ctk.CTkLabel(f, text="▶ Click an AM row to expand their associates",
                            text_color=MUTED, font=ctk.CTkFont(size=11))
        hint.pack(anchor="w", padx=4, pady=(0,4))

        vsb = ttk.Scrollbar(f, orient="vertical")
        vsb.pack(side="right", fill="y")

        self._am_tree = ttk.Treeview(f, columns=cols, show="tree headings",
                                      style="Dark.Treeview", yscrollcommand=vsb.set)
        vsb.configure(command=self._am_tree.yview)

        self._am_tree.column("#0",  width=22, stretch=False)
        widths = [50,220,110,110,100,60,75]
        for col, w in zip(cols, widths):
            self._am_tree.heading(col, text=col,
                                  command=lambda c=col: self._sort_am(c))
            self._am_tree.column(col, width=w, anchor="center", minwidth=40)

        self._am_tree.pack(fill="both", expand=True)

        # Color tags
        for tag, color in [("red",C_RED),("orange",C_ORA),("lgreen",C_LGR),("dgreen",C_DGR),("na",MUTED)]:
            self._am_tree.tag_configure(tag, foreground=color)
        self._am_tree.tag_configure("assoc", foreground=MUTED, font=("Segoe UI", 9))

    # ── Flagged Associates Tab ────────────────────────────────
    def _build_flagged_tab(self):
        parent = self._tab.tab("Flagged Associates")
        cols = ("Badge ID", "Associate Name", "PT%", "Inferred Hrs", "Total Hrs", "Gap to Target", "Station", "Floor")

        f = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        f.pack(fill="both", expand=True, padx=4, pady=4)

        # ── Filter bar: manager dropdown + search + copy button ───
        mgr_bar = ctk.CTkFrame(f, fg_color=BG, corner_radius=0)
        mgr_bar.pack(fill="x", pady=(0, 2))

        ctk.CTkLabel(mgr_bar, text="Manager:", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(4, 4))
        self._flag_mgr_var = tk.StringVar(value="All Managers")
        self._flag_mgr_menu = ctk.CTkOptionMenu(
            mgr_bar, variable=self._flag_mgr_var, values=["All Managers"],
            width=200, font=ctk.CTkFont(size=11),
            fg_color=CARD, button_color=BORDER, button_hover_color="#3a3d4a",
            dropdown_fg_color=CARD,
            command=lambda _: self._refresh_flagged())
        self._flag_mgr_menu.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(mgr_bar, text="Search:", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 4))
        self._flag_search_var = tk.StringVar()
        self._flag_search_var.trace_add("write", lambda *_: self._refresh_flagged())
        ctk.CTkEntry(mgr_bar, textvariable=self._flag_search_var,
                     width=160, font=ctk.CTkFont(size=11),
                     placeholder_text="name or badge…").pack(side="left", padx=(0, 10))

        self._copy_btn = ctk.CTkButton(mgr_bar, text="📋 Copy List",
                                        command=self._copy_flagged,
                                        width=100, height=28,
                                        fg_color=BORDER, hover_color="#3a3d4a",
                                        text_color=TEXT, font=ctk.CTkFont(size=11))
        self._copy_btn.pack(side="left")

        hint = ctk.CTkLabel(f,
            text="▶ Click name → FCLM  ·  Right-click → History  ·  Station/Floor: load Stow Rates → Current Now first",
            text_color=MUTED, font=ctk.CTkFont(size=11))
        hint.pack(anchor="w", padx=4, pady=(4, 4))

        vsb = ttk.Scrollbar(f, orient="vertical")
        vsb.pack(side="right", fill="y")

        self._flag_tree = ttk.Treeview(f, columns=cols, show="tree headings",
                                        style="Dark.Treeview", yscrollcommand=vsb.set)
        vsb.configure(command=self._flag_tree.yview)

        self._flag_tree.column("#0", width=22, stretch=False)
        widths = [110, 200, 85, 90, 80, 85, 90, 80]
        for col, w in zip(cols, widths):
            self._flag_tree.heading(col, text=col)
            self._flag_tree.column(col, width=w, anchor="center", minwidth=40)
        self._flag_tree.column("Badge ID", anchor="center")
        self._flag_tree.column("Associate Name", anchor="w")

        self._flag_tree.pack(fill="both", expand=True)

        for tag, color in [("red", C_RED), ("orange", C_ORA), ("detail", "#4a5068")]:
            self._flag_tree.tag_configure(tag, foreground=color)
        self._flag_tree.tag_configure("mgr_header",
            foreground=ACCENT, font=("Segoe UI", 10, "bold"))

        self._flag_tree.bind("<ButtonRelease-1>", self._on_flag_click)
        self._flag_tree.bind("<Button-3>",        self._on_flag_rightclick)

    # ── Week-over-Week Tab ────────────────────────────────────
    def _build_wow_tab(self):
        parent = self._tab.tab("Week-over-Week")

        ctrl = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=8)
        ctrl.pack(fill="x", padx=8, pady=(8,4))

        def lbl(p, t):
            ctk.CTkLabel(p, text=t, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(side="left", padx=(10,3))

        lbl(ctrl, "Date 1:")
        self._wow_d1 = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
        ctk.CTkEntry(ctrl, textvariable=self._wow_d1, width=108,
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0,12))

        lbl(ctrl, "Date 2:")
        d2 = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        self._wow_d2 = tk.StringVar(value=d2)
        ctk.CTkEntry(ctrl, textvariable=self._wow_d2, width=108,
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0,12))

        lbl(ctrl, "Shift:")
        self._wow_shift = tk.StringVar(value="All Day")
        ctk.CTkOptionMenu(ctrl, variable=self._wow_shift,
                          values=list(fclm.SHIFTS.keys()),
                          width=160, font=ctk.CTkFont(size=11),
                          fg_color=CARD, button_color=BORDER,
                          button_hover_color="#3a3d4a",
                          dropdown_fg_color=CARD).pack(side="left", padx=(0,12))

        self._wow_btn = ctk.CTkButton(ctrl, text="Compare",
                                       command=self._on_wow_compare,
                                       width=100, height=30,
                                       fg_color=ACCENT, hover_color="#cc7a00",
                                       text_color="black",
                                       font=ctk.CTkFont(size=11, weight="bold"))
        self._wow_btn.pack(side="left")

        # Side-by-side area
        split = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        split.pack(fill="both", expand=True, padx=8, pady=4)
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=1)

        self._wow_trees = []
        for col_idx, label in enumerate(["Date 1", "Date 2"]):
            side = ctk.CTkFrame(split, fg_color=BG, corner_radius=0)
            side.grid(row=0, column=col_idx, sticky="nsew", padx=(0 if col_idx else 0, 6 if col_idx==0 else 0))

            ctk.CTkLabel(side, text=label, font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=ACCENT).pack(anchor="w", padx=4, pady=(0,4))

            cols = ("Manager", "PT%", "AAs", "Δ vs other")
            vsb  = ttk.Scrollbar(side, orient="vertical")
            vsb.pack(side="right", fill="y")
            t = ttk.Treeview(side, columns=cols, show="headings",
                              style="Dark.Treeview", yscrollcommand=vsb.set)
            vsb.configure(command=t.yview)
            for c, w in zip(cols, [200,90,60,100]):
                t.heading(c, text=c); t.column(c, width=w, anchor="center")
            t.pack(fill="both", expand=True)
            for tag, color in [("red",C_RED),("orange",C_ORA),("lgreen",C_LGR),("dgreen",C_DGR)]:
                t.tag_configure(tag, foreground=color)
            self._wow_trees.append(t)

    # ─────────────────────────────────────────────────────────
    # Data Fetching
    # ─────────────────────────────────────────────────────────

    # ── Stow Rates Tab ──────────────────────────────────────────────────────────
    def _build_stow_tab(self):
        parent = self._tab.tab("Stow Rates")
        self._stow_snapshot = {}   # name -> record
        self._stow_current  = {}   # name -> record
        self._stow_zones    = []

        # ── Controls ──────────────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=8)
        ctrl.pack(fill="x", padx=8, pady=(8, 4))

        def lbl(t):
            ctk.CTkLabel(ctrl, text=t, text_color=MUTED,
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=(10, 3))

        # Zone checkboxes (auto-discovered)
        lbl("Zones:")
        self._stow_zone_frame = ctk.CTkScrollableFrame(
            ctrl, fg_color=CARD, orientation="horizontal", height=30, width=260)
        self._stow_zone_frame.pack(side="left", padx=(0, 6))
        self._stow_zone_vars = {}
        ctk.CTkLabel(self._stow_zone_frame, text="(click Discover first)",
                     text_color=MUTED, font=ctk.CTkFont(size=10)).pack(side="left", padx=4)

        ctk.CTkButton(ctrl, text="Discover Zones", width=110, height=26,
                      fg_color=BORDER, hover_color="#3a3d4a", text_color=TEXT,
                      font=ctk.CTkFont(size=10),
                      command=self._stow_discover_zones).pack(side="left", padx=(0, 6))

        lbl("Snapshot (HHMM):")
        self._stow_time_var = tk.StringVar(value="1750")
        ctk.CTkEntry(ctrl, textvariable=self._stow_time_var, width=72,
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))

        ctk.CTkButton(ctrl, text="End of Period", width=95, height=28,
                      fg_color=BORDER, hover_color="#3a3d4a", text_color=TEXT,
                      font=ctk.CTkFont(size=10),
                      command=self._stow_end_of_period).pack(side="left", padx=(0, 4))

        self._stow_snap_btn = ctk.CTkButton(
            ctrl, text="Snapshot", width=85, height=28,
            fg_color=ACCENT, hover_color="#cc7a00", text_color="black",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._stow_fetch_snapshot)
        self._stow_snap_btn.pack(side="left", padx=(0, 4))

        self._stow_now_btn = ctk.CTkButton(
            ctrl, text="Current Now", width=100, height=28,
            fg_color="#2563eb", hover_color="#1d4ed8", text_color="white",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._stow_fetch_current)
        self._stow_now_btn.pack(side="left", padx=(0, 4))

        ctk.CTkButton(ctrl, text="📷 Debug", width=72, height=26,
                      fg_color=BORDER, hover_color="#3a3d4a", text_color=MUTED,
                      font=ctk.CTkFont(size=10),
                      command=self._stow_debug_screenshot).pack(side="left", padx=(0, 4))

        ctk.CTkButton(ctrl, text="Load CSV", width=78, height=26,
                      fg_color="#1e4d2b", hover_color="#166534", text_color="#4ade80",
                      font=ctk.CTkFont(size=10),
                      command=self._stow_import_csv).pack(side="left", padx=(0, 4))

        self._stow_status = ctk.CTkLabel(ctrl, text="", text_color=MUTED,
                                          font=ctk.CTkFont(size=10))
        self._stow_status.pack(side="left", padx=6)

        # ── Main split: tree (left) + detail card (right) ─────────────────────
        split = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        split.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        split.columnconfigure(0, weight=3)
        split.columnconfigure(1, weight=1)
        split.rowconfigure(0, weight=1)

        # Left: grouped tree Floor → Station → AA
        tree_frame = ctk.CTkFrame(split, fg_color=BG, corner_radius=0)
        tree_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        cols = ("Name", "Rate", "CT", "UPF", "Δ Rate", "Δ CT", "Δ UPF")
        widths = (180, 65, 55, 55, 65, 55, 55)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        vsb.pack(side="right", fill="y")

        self._stow_tree = ttk.Treeview(
            tree_frame, columns=cols, show="tree headings",
            style="Dark.Treeview", yscrollcommand=vsb.set)
        vsb.configure(command=self._stow_tree.yview)

        self._stow_tree.column("#0", width=20, stretch=False)
        for c, w in zip(cols, widths):
            self._stow_tree.heading(c, text=c,
                command=lambda _c=c: self._stow_sort(_c))
            self._stow_tree.column(c, width=w, anchor="center",
                                    minwidth=40, stretch=False)
        self._stow_tree.column("Name", anchor="w", stretch=True)
        self._stow_tree.pack(fill="both", expand=True)

        for tag, color in [("red", C_RED), ("orange", C_ORA),
                            ("lgreen", C_LGR), ("dgreen", C_DGR),
                            ("muted", MUTED), ("floor_hdr", ACCENT),
                            ("station_hdr", TEXT)]:
            self._stow_tree.tag_configure(tag, foreground=color)
        self._stow_tree.tag_configure(
            "floor_hdr", font=("Segoe UI", 10, "bold"), foreground=ACCENT)
        self._stow_tree.tag_configure(
            "station_hdr", font=("Segoe UI", 9, "bold"), foreground=TEXT)
        self._stow_tree.bind("<<TreeviewSelect>>", self._stow_on_select)

        # Right: detail card (scrollable)
        card_border = ctk.CTkFrame(split, fg_color=CARD, corner_radius=8,
                                    border_width=1, border_color=BORDER)
        card_border.grid(row=0, column=1, sticky="nsew")
        card_outer = ctk.CTkScrollableFrame(card_border, fg_color=CARD,
                                             scrollbar_button_color=BORDER,
                                             scrollbar_button_hover_color=ACCENT)
        card_outer.pack(fill="both", expand=True, padx=2, pady=2)
        ctk.CTkLabel(card_outer,
                     text="Select an associate\nfor comparison",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).pack(
            pady=40)
        self._stow_card = card_outer

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _stow_import_csv(self):
        """Import stow data from a CSV file exported from Vantage or any source."""
        from tkinter import filedialog
        import csv as _csv
        path = filedialog.askopenfilename(
            title="Import Stow Data (CSV)",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return

        def _num_s(v):
            if v is None: return None
            try: return float(str(v).replace(",", "").strip())
            except: return None

        def _col(row, *keys):
            for k in keys:
                for variant in (k, k.lower(), k.upper(), k.replace(" ", ""), k.replace(" ", "_")):
                    if variant in row and str(row[variant]).strip():
                        return str(row[variant]).strip()
            return None

        try:
            records = []
            with open(path, newline='', encoding='utf-8-sig') as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    name = _col(row, 'Associate', 'Name', 'AssociateName',
                                'Employee', 'EmployeeName', 'Login', 'AA')
                    if not name or len(name) < 2:
                        continue
                    records.append({
                        'name':       name,
                        'zone':       _col(row, 'Zone', 'Floor', 'Area', 'ZoneId') or '',
                        'station':    _col(row, 'Station', 'StationId',
                                          'Node', 'NodeId', 'StationLabel') or '',
                        'rate':       _num_s(_col(row, 'Rate', 'StowRate',
                                                  'UPH', 'UnitsPerHour', 'Stow Rate')),
                        'cycle_time': _num_s(_col(row, 'CycleTime', 'Cycle Time',
                                                  'CT', 'AvgCycleTime', 'Avg Cycle Time')),
                        'upf':        _num_s(_col(row, 'UPF', 'UnitsPerFace',
                                                  'Units Per Face', 'UnitsPerFace')),
                    })
            if not records:
                messagebox.showwarning("CSV Import", "No valid rows found.\nExpected columns: Associate, Zone, Station, Rate, Cycle Time, UPF")
                return
            self._stow_current = {r['name']: r for r in records}
            self._stow_set_status(f"Loaded {len(records)} associates from CSV")
            self._stow_refresh_tree()
        except Exception as e:
            messagebox.showerror("CSV Import Error", str(e))

    def _stow_set_status(self, msg):
        self._stow_status.configure(text=msg)

    def _stow_end_of_period(self):
        now = datetime.now()
        self._stow_time_var.set("0600" if now.hour < 12 else "1800")

    def _stow_selected_zones(self):
        return [zid for zid, var in self._stow_zone_vars.items() if var.get()]

    # ── Zone discovery ────────────────────────────────────────────────────────
    def _stow_discover_zones(self):
        if _vantage is None:
            messagebox.showerror("Missing", "vantage.py not found.")
            return
        wh = self._wh_var.get().strip().upper() or "CLE3"
        self._stow_set_status("Discovering zones…")
        threading.Thread(target=self._stow_discover_thread,
                         args=(wh,), daemon=True).start()

    def _stow_discover_thread(self, wh):
        result = _vantage.discover_zones(
            wh, status_cb=lambda m: self.after(0, self._stow_set_status, m))
        self.after(0, self._stow_finish_discover, result)

    def _stow_finish_discover(self, result):
        if not result.get("ok"):
            self._stow_set_status(f"Discovery failed: {result.get('error','')}")
            return
        zones = result["zones"]
        self._stow_zones = [z["id"] for z in zones if z.get("id")]
        for w in self._stow_zone_frame.winfo_children():
            w.destroy()
        self._stow_zone_vars = {}
        if not zones:
            ctk.CTkLabel(self._stow_zone_frame, text="No zones found",
                         text_color=MUTED, font=ctk.CTkFont(size=10)).pack(
                side="left", padx=4)
        else:
            for z in zones:
                zid  = z.get("id", "")
                zlbl = z.get("label") or zid
                var  = tk.BooleanVar(value=True)
                self._stow_zone_vars[zid] = var
                ctk.CTkCheckBox(
                    self._stow_zone_frame, text=zlbl[:12], variable=var,
                    width=20, font=ctk.CTkFont(size=10),
                    text_color=TEXT, fg_color=ACCENT,
                    hover_color="#cc7a00").pack(side="left", padx=(4, 2))
        self._stow_set_status(f"Found {len(zones)} zone(s)")

    # ── Fetch snapshot ────────────────────────────────────────────────────────
    def _stow_fetch_snapshot(self):
        if _vantage is None:
            messagebox.showerror("Missing", "vantage.py not found.")
            return
        time_str = self._stow_time_var.get().strip().replace(":", "")
        wh = self._wh_var.get().strip().upper() or "CLE3"
        zones = self._stow_selected_zones()
        self._stow_snap_btn.configure(state="disabled", text="Loading…")
        threading.Thread(target=self._stow_snap_thread,
                         args=(wh, time_str, zones), daemon=True).start()

    def _stow_snap_thread(self, wh, time_str, zones):
        result = _vantage.fetch(
            wh, time_str, zones,
            status_cb=lambda m: self.after(0, self._stow_set_status, m))
        self.after(0, self._stow_finish_snap, result, time_str)

    def _stow_finish_snap(self, result, time_str):
        self._stow_snap_btn.configure(state="normal", text="Snapshot")
        if not result.get("ok"):
            self._stow_set_status(f"Snapshot failed: {result.get('error','')}")
            return
        self._stow_snapshot = {r["name"]: r for r in result["associates"]}
        self._stow_set_status(
            f"Snapshot {time_str}: {len(self._stow_snapshot)} associates")
        self._stow_refresh_tree()

    # ── Fetch current ─────────────────────────────────────────────────────────
    def _stow_fetch_current(self):
        if _vantage is None:
            messagebox.showerror("Missing", "vantage.py not found.")
            return
        now_str = datetime.now().strftime("%H%M")
        wh = self._wh_var.get().strip().upper() or "CLE3"
        zones = self._stow_selected_zones()
        self._stow_now_btn.configure(state="disabled", text="Loading…")
        threading.Thread(target=self._stow_now_thread,
                         args=(wh, now_str, zones), daemon=True).start()

    def _stow_now_thread(self, wh, time_str, zones):
        result = _vantage.fetch(
            wh, time_str, zones,
            status_cb=lambda m: self.after(0, self._stow_set_status, m))
        self.after(0, self._stow_finish_now, result, time_str)

    def _stow_finish_now(self, result, time_str):
        self._stow_now_btn.configure(state="normal", text="Current Now")
        if not result.get("ok"):
            self._stow_set_status(
                self._stow_status.cget("text") + " | Current failed")
            return
        self._stow_current = {r["name"]: r for r in result["associates"]}
        self._stow_set_status(
            self._stow_status.cget("text") +
            f" | Current {time_str}: {len(self._stow_current)} associates")
        self._stow_refresh_tree()

    # ── Debug screenshot ──────────────────────────────────────────────────────
    def _stow_debug_screenshot(self):
        import os
        shot = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            ".pt_dashboard", "vantage_last.png")
        if os.path.exists(shot):
            os.startfile(shot)
            self._stow_set_status(f"Opened: {shot}")
        else:
            self._stow_set_status("No screenshot yet — run Discover or Current Now first")

    # ── Tree refresh: Floor → Station → AA ────────────────────────────────────
    def _stow_refresh_tree(self):
        tree = self._stow_tree
        tree.delete(*tree.get_children())

        # Union all associates from both datasets; group by floor then station
        from collections import defaultdict
        floor_map = defaultdict(lambda: defaultdict(list))

        all_names = set(list(self._stow_current) + list(self._stow_snapshot))
        for name in all_names:
            rec = self._stow_current.get(name) or self._stow_snapshot.get(name, {})
            floor   = rec.get("zone", "") or "Unknown Floor"
            station = rec.get("station", "") or "Unknown Station"
            floor_map[floor][station].append(name)

        def fmt(v):
            return f"{v:.0f}" if v is not None else "—"

        def delta_tag(d, higher_better):
            if d is None: return "muted"
            improved = (d > 0) == higher_better
            return "dgreen" if improved else "red"

        def _avg(vals):
            v = [x for x in vals if x is not None]
            return sum(v) / len(v) if v else None

        for floor in sorted(floor_map):
            stations = floor_map[floor]
            aa_total = sum(len(v) for v in stations.values())
            # Aggregate floor metrics
            all_floor_names = [n for nl in stations.values() for n in nl]
            fr  = _avg([self._stow_current.get(n, {}).get("rate") for n in all_floor_names])
            fct = _avg([self._stow_current.get(n, {}).get("cycle_time") for n in all_floor_names])
            fupf= _avg([self._stow_current.get(n, {}).get("upf") for n in all_floor_names])
            floor_id = tree.insert(
                "", "end", open=True,
                values=(f"{floor}  —  {len(stations)} stations, {aa_total} AAs",
                        fmt(fr), fmt(fct), fmt(fupf), "", "", ""),
                tags=("floor_hdr",))

            for station in sorted(stations):
                names_here = stations[station]
                # Aggregate station metrics
                sr  = _avg([self._stow_current.get(n, {}).get("rate") for n in names_here])
                sct = _avg([self._stow_current.get(n, {}).get("cycle_time") for n in names_here])
                supf= _avg([self._stow_current.get(n, {}).get("upf") for n in names_here])
                sta_tag = "dgreen" if sr is not None and sr >= 150 else ("red" if sr is not None else "station_hdr")
                sta_id = tree.insert(
                    floor_id, "end", open=True,
                    values=(f"  {station}  ({len(names_here)} AAs)",
                            fmt(sr), fmt(sct), fmt(supf), "", "", ""),
                    tags=(sta_tag, "station_hdr"))

                for name in sorted(names_here):
                    snap = self._stow_snapshot.get(name, {})
                    now  = self._stow_current.get(name, {})
                    nr   = now.get("rate");       sr = snap.get("rate")
                    nct  = now.get("cycle_time"); sct = snap.get("cycle_time")
                    nupf = now.get("upf");        supf = snap.get("upf")

                    dr   = (nr - sr)  if nr  is not None and sr  is not None else None
                    dct  = (nct - sct) if nct is not None and sct is not None else None
                    dupf = (nupf - supf) if nupf is not None and supf is not None else None

                    def d_str(d, higher_better=True):
                        if d is None: return "—"
                        return ("+" if d > 0 else "") + f"{d:.0f}"

                    # Row color from current rate vs target
                    row_tag = "muted"
                    if nr is not None:
                        row_tag = "dgreen" if nr >= 150 else "red"

                    tree.insert(sta_id, "end", iid=f"aa__{name}",
                        values=(name,
                                fmt(nr), fmt(nct), fmt(nupf),
                                d_str(dr),
                                d_str(dct, higher_better=False),
                                d_str(dupf)),
                        tags=(row_tag,))

    # ── Sort ──────────────────────────────────────────────────────────────────
    def _stow_sort(self, col):
        tree = self._stow_tree
        items = [(tree.set(k, col), k) for k in tree.get_children("")]
        def key(x):
            try: return float(x[0].replace("+", "").replace("—", "0"))
            except: return x[0].lower()
        rev = not getattr(self, "_stow_sort_rev", False)
        items.sort(key=key, reverse=rev)
        self._stow_sort_rev = rev
        for idx, (_, k) in enumerate(items):
            tree.move(k, "", idx)

    # ── AA detail card ────────────────────────────────────────────────────────
    def _stow_on_select(self, event):
        sel = self._stow_tree.selection()
        if not sel: return
        iid = sel[0]
        if not iid.startswith("aa__"): return
        name = iid[4:]
        snap = self._stow_snapshot.get(name, {})
        now  = self._stow_current.get(name, {})
        self._stow_build_card(name, snap, now)

    def _stow_build_card(self, name, snap, now):
        card = self._stow_card
        for w in card.winfo_children():
            w.destroy()

        ctk.CTkLabel(card, text=name,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT, wraplength=200).pack(
            anchor="w", padx=12, pady=(10, 2))

        zone    = snap.get("zone")    or now.get("zone",    "")
        station = snap.get("station") or now.get("station", "")
        ctk.CTkLabel(card,
                     text=f"Floor: {zone or '—'}   Station: {station or '—'}",
                     text_color=MUTED, font=ctk.CTkFont(size=10)).pack(
            anchor="w", padx=12, pady=(0, 8))

        metrics = [
            ("Rate (u/hr)",  "rate",       True,  150,  None),
            ("Cycle Time",   "cycle_time", False, None, 12),
            ("Units / Face", "upf",        True,  6,    None),
        ]

        hdr = ctk.CTkFrame(card, fg_color=BORDER, corner_radius=4)
        hdr.pack(fill="x", padx=10, pady=(0, 2))
        for col_txt, w in [("Metric", 90), ("Snapshot", 70),
                            ("Current", 70), ("Δ", 50)]:
            ctk.CTkLabel(hdr, text=col_txt, text_color=MUTED,
                         font=ctk.CTkFont(size=9, weight="bold"),
                         width=w).pack(side="left", padx=4, pady=3)

        for label, key, higher_better, mn, mx in metrics:
            sv = snap.get(key); nv = now.get(key)
            fmt = lambda v: (f"{v:.0f}" if v is not None else "—")

            d_text = d_color = None
            if sv is not None and nv is not None:
                d = nv - sv
                improved = (d > 0) == higher_better
                d_text  = ("+" if d > 0 else "") + f"{d:.0f}"
                d_color = C_DGR if improved else C_RED

            def val_color(v):
                if v is None: return MUTED
                if mn is not None: return C_DGR if v >= mn else C_RED
                if mx is not None: return C_DGR if v <= mx else C_RED
                return TEXT

            row = ctk.CTkFrame(card, fg_color=CARD, corner_radius=4)
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=label, text_color=MUTED,
                         font=ctk.CTkFont(size=10), width=90).pack(
                side="left", padx=4, pady=4)
            ctk.CTkLabel(row, text=fmt(sv), text_color=MUTED,
                         font=ctk.CTkFont(size=11), width=70).pack(side="left")
            ctk.CTkLabel(row, text=fmt(nv),
                         text_color=val_color(nv),
                         font=ctk.CTkFont(size=11, weight="bold"),
                         width=70).pack(side="left")
            ctk.CTkLabel(row, text=d_text or "—",
                         text_color=d_color or MUTED,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         width=50).pack(side="left")

        # Target legend
        ctk.CTkLabel(card,
                     text="Targets: Rate ≥150  CT ≤12  UPF ≥6",
                     text_color=MUTED, font=ctk.CTkFont(size=9)).pack(
            anchor="w", padx=12, pady=(6, 10))


    def _on_fetch(self):
        date  = self._date_var.get().strip()
        shift = self._shift_var.get()
        wh    = self._wh_var.get().strip().upper()
        if not date or not wh:
            messagebox.showwarning("Missing Info", "Please enter a date and warehouse ID.")
            return
        self._fetch_btn.configure(state="disabled", text="Fetching…")
        self._set_status("Connecting to FCLM…")
        self._current_wh = wh
        threading.Thread(target=self._fetch_thread,
                         args=(date, shift, wh, self._finish_main),
                         daemon=True).start()

    def _fetch_thread(self, date, shift, wh, callback):
        result = fclm.fetch(date, shift, wh,
                            status_cb=lambda m: self.after(0, self._set_status, m))
        if result['ok']:
            data = processor.process(result['rows'])
            self._data[f"{date}|{shift}|{wh}"] = data
            self._last_url = result['url']
            self.after(0, callback, date, shift, data, None)
        else:
            self.after(0, callback, date, shift, None, result['error'])

    def _finish_main(self, date, shift, data, error):
        if error:
            self._fetch_btn.configure(state="normal", text="Get Data")
            self._set_status(f"Error: {error}")
            messagebox.showerror("FCLM Error", error)
            if getattr(self, '_autorefresh_on', False):
                self._autorefresh_job = self.after(15 * 60 * 1000, self._on_fetch)
            return
        self._render(data, date, shift)
        # Chain to BMI fetch
        if _bmi:
            self._set_status("FCLM done · Fetching BMI metrics...")
            wh = getattr(self, '_current_wh', 'CLE3')
            threading.Thread(target=self._bmi_thread, args=(wh,), daemon=True).start()
        else:
            self._fetch_btn.configure(state="normal", text="Get Data")
            if getattr(self, '_autorefresh_on', False):
                self._autorefresh_job = self.after(15 * 60 * 1000, self._on_fetch)

    def _bmi_thread(self, wh):
        result = _bmi.fetch(wh, status_cb=lambda m: self.after(0, self._set_status, m))
        self.after(0, self._finish_bmi, result)

    def _finish_bmi(self, result):
        if result.get('ok'):
            self._build_cards_bmi(result)
            pt = result['metrics'].get('Productive Time')
            self._set_status(self._status_var.get() + f" · BMI PT: {pt}%")
        else:
            self._set_status(self._status_var.get() + f" · BMI unavailable")
        self._fetch_btn.configure(state="normal", text="Get Data")
        if getattr(self, '_autorefresh_on', False):
            self._autorefresh_job = self.after(15 * 60 * 1000, self._on_fetch)

    def _on_wow_compare(self):
        d1    = self._wow_d1.get().strip()
        d2    = self._wow_d2.get().strip()
        shift = self._wow_shift.get()
        wh    = self._wh_var.get().strip().upper()
        if not d1 or not d2: return
        self._wow_btn.configure(state="disabled", text="Fetching…")
        self._set_status(f"Fetching {d1} and {d2}…")
        threading.Thread(target=self._wow_thread,
                         args=(d1, d2, shift, wh), daemon=True).start()

    def _wow_thread(self, d1, d2, shift, wh):
        results = []
        for date in (d1, d2):
            key = f"{date}|{shift}|{wh}"
            if key in self._data:
                results.append(self._data[key])
            else:
                r = fclm.fetch(date, shift, wh,
                               status_cb=lambda m: self.after(0, self._set_status, m))
                if r['ok']:
                    d = processor.process(r['rows'])
                    self._data[key] = d
                    results.append(d)
                else:
                    results.append(None)
        self.after(0, self._render_wow, d1, d2, *results)

    # ─────────────────────────────────────────────────────────
    # Rendering
    # ─────────────────────────────────────────────────────────
    def _render(self, data, date, shift):
        self._build_cards(data)
        self._render_am(data)
        self._refresh_flagged(data)
        lbl = shift.split('(')[0].strip()
        self._set_status(
            f"{lbl} · {date} · Overall PT: {pt_str(data['overall_pt'])} · "
            f"{data['aa_count']} AAs · {data['flagged']} flagged")

    def _build_cards(self, data):
        """Temporary FCLM cards shown while BMI is loading."""
        for w in self._cards_frame.winfo_children():
            w.destroy()
        cards = [
            ("Overall PT",    pt_str(data['overall_pt']), pt_color(data['overall_pt'])),
            ("Associates",    str(data['aa_count']),       TEXT),
            ("Flagged <84%",  str(data['flagged']),        C_ORA if data['flagged'] else C_DGR),
            ("≥ 90%",         str(data['above_90']),       C_DGR),
            ("Managers",      str(len(data['managers'])),  TEXT),
            ("Inferred Hrs",  str(data['total_inferred']), C_ORA),
        ]
        for i, (lbl, val, color) in enumerate(cards):
            card = ctk.CTkFrame(self._cards_frame, fg_color=CARD, corner_radius=8,
                                border_width=1, border_color=BORDER)
            card.grid(row=0, column=i, padx=(0,10), sticky="ew")
            self._cards_frame.columnconfigure(i, weight=1)
            ctk.CTkLabel(card, text=lbl, text_color=MUTED,
                         font=ctk.CTkFont(size=10)).pack(pady=(10,2), padx=10)
            ctk.CTkLabel(card, text=val, text_color=color,
                         font=ctk.CTkFont(size=24, weight="bold")).pack()
            ctk.CTkLabel(card, text=" ", font=ctk.CTkFont(size=6)).pack(pady=(0,8))

    def _build_cards_bmi(self, bmi_data):
        """Replace summary cards with live BMI facility metrics."""
        for w in self._cards_frame.winfo_children():
            w.destroy()
        metrics = bmi_data.get('metrics', {})
        rolling = bmi_data.get('rolling_7', {})
        mtype   = bmi_data.get('metric_type', {})

        # (label, key, use_rolling, invert_color)
        card_defs = [
            ("PT% Today",      "Productive Time", False, False),
            ("PT% Rolling 7",  "Productive Time", True,  False),
            ("Unknown Idle",   "Unknown Idle",    False, True),
            ("Indirect",       "Indirect",        False, True),
            ("Labor Move",     "Labor Move",      False, True),
            ("Fast Start",     "Fast Start",      False, True),
            ("Break",          "Break",           False, True),
            ("Strong Finish",  "Strong Finish",   False, True),
        ]

        def _col(val, invert):
            if val is None: return MUTED
            if not invert:  # PT% higher = better
                return C_DGR if val >= 70 else C_LGR if val >= 65 else C_ORA if val >= 58 else C_RED
            else:           # hours lost lower = better
                return C_DGR if val <= 3 else C_LGR if val <= 10 else C_ORA if val <= 20 else C_RED

        for i, (lbl, key, use_roll, invert) in enumerate(card_defs):
            val     = rolling.get(key) if use_roll else metrics.get(key)
            val_str = f"{val}%" if val is not None else "—"
            color   = _col(val, invert)
            sub     = mtype.get(key, '')
            card = ctk.CTkFrame(self._cards_frame, fg_color=CARD, corner_radius=8,
                                border_width=1, border_color=BORDER)
            card.grid(row=0, column=i, padx=(0,6), sticky="ew")
            self._cards_frame.columnconfigure(i, weight=1)
            ctk.CTkLabel(card, text=lbl, text_color=MUTED,
                         font=ctk.CTkFont(size=10)).pack(pady=(10,2), padx=8)
            ctk.CTkLabel(card, text=val_str, text_color=color,
                         font=ctk.CTkFont(size=20, weight="bold")).pack()
            if sub:
                ctk.CTkLabel(card, text=sub, text_color=MUTED,
                             font=ctk.CTkFont(size=8)).pack(pady=(0,2))
            ctk.CTkLabel(card, text=" ", font=ctk.CTkFont(size=4)).pack(pady=(0,6))
    def _render_am(self, data):
        tree = self._am_tree
        tree.delete(*tree.get_children())
        for i, mg in enumerate(data['managers']):
            medal = ["🥇","🥈","🥉"][i] if i < 3 else str(i+1)
            tag   = pt_tag(mg['pt'])
            am_id = tree.insert("", "end", values=(
                medal, mg['name'], pt_str(mg['pt']),
                f"{mg['inferred']:.2f}", f"{mg['total']:.2f}",
                mg['aa_count'], mg['flagged']
            ), tags=(tag,))

            # Child rows: associates
            for aa in mg['associates']:
                atag = pt_tag(aa['pt'])
                tree.insert(am_id, "end", values=(
                    "", aa['name'],
                    pt_str(aa['pt']),
                    f"{aa['inferred']:.2f}", f"{aa['total']:.2f}",
                    f"Badge: {aa['id']}", ""
                ), tags=(atag, "assoc"))

    def _stow_match_name(self, fclm_name):
        """
        Try to find a Vantage stow record matching an FCLM associate name.
        FCLM uses "Last, First"; Vantage format is unknown until tested.
        Tries exact match, then normalized word-set match.
        """
        if not getattr(self, '_stow_current', {}):
            return {}
        import re
        def norm(s):
            return set(re.sub(r"[^a-z0-9]", " ", s.lower()).split())
        target = norm(fclm_name)
        # Exact key match
        if fclm_name in self._stow_current:
            return self._stow_current[fclm_name]
        # Normalized word-set match (handles "Last, First" vs "First Last")
        for key, rec in self._stow_current.items():
            if norm(key) == target:
                return rec
        # Partial match: all words in target appear in key or vice versa
        for key, rec in self._stow_current.items():
            kw = norm(key)
            if target and kw and (target <= kw or kw <= target):
                return rec
        return {}

    def _refresh_flagged(self, data=None):
        if data is None:
            key = self._last_data_key()
            if not key: return
            data = self._data.get(key)
            if not data: return

        tree = self._flag_tree
        tree.delete(*tree.get_children())
        threshold  = float(self._thresh_var.get())
        filter_mgr = getattr(self, '_flag_mgr_var', None)
        filter_mgr = filter_mgr.get() if filter_mgr else "All Managers"
        search     = getattr(self, '_flag_search_var', None)
        search     = search.get().strip().lower() if search else ""

        # Apply PT threshold + optional name/badge search
        flagged = [a for a in data['associates']
                   if a['pt'] is not None and a['pt'] < threshold
                   and (not search
                        or search in a['name'].lower()
                        or search in a['id'].lower())]

        if not flagged:
            tree.insert("", "end", values=(
"✓ No associates flagged", "", "", "", "", ""), tags=("detail",))
            return

        from collections import defaultdict
        by_mgr = defaultdict(list)
        for aa in flagged:
            by_mgr[aa['manager']].append(aa)

        sorted_mgrs = sorted(
            by_mgr.keys(),
            key=lambda m: sum(a['pt'] for a in by_mgr[m]) / len(by_mgr[m]))

        all_opts = ["All Managers"] + sorted_mgrs
        if hasattr(self, '_flag_mgr_menu'):
            self._flag_mgr_menu.configure(values=all_opts)
        if filter_mgr not in all_opts:
            if hasattr(self, '_flag_mgr_var'):
                self._flag_mgr_var.set("All Managers")
            filter_mgr = "All Managers"

        for mgr_name in sorted_mgrs:
            if filter_mgr != "All Managers" and mgr_name != filter_mgr:
                continue

            aa_list = sorted(by_mgr[mgr_name], key=lambda a: a['pt'])
            avg_pt  = sum(a['pt'] for a in aa_list) / len(aa_list)
            mgr_id  = tree.insert("", "end", open=True,
                values=(mgr_name, "", f"{len(aa_list)} flagged",
                        "", "", f"avg {avg_pt:.1f}%"),
                tags=("mgr_header",))

            for aa in aa_list:
                gap      = round(threshold - aa['pt'], 1)
                vantage  = self._stow_match_name(aa['name'])
                station  = vantage.get('station', '—')
                floor    = vantage.get('zone',    '—')
                tree.insert(mgr_id, "end",
                    iid=f"aa_{aa['id']}",
                    values=(aa['id'], aa['name'], pt_str(aa['pt']),
                            f"{aa['inferred']:.2f}", f"{aa['total']:.2f}",
                            f"−{gap}%", station, floor),
                    tags=(pt_tag(aa['pt']),))

    def _render_wow(self, d1, d2, data1, data2):
        self._wow_btn.configure(state="normal", text="Compare")
        label_map = {0: d1, 1: d2}
        other_map = {0: data2, 1: data1}

        for idx, data in enumerate([data1, data2]):
            t = self._wow_trees[idx]
            t.delete(*t.get_children())
            if not data:
                t.insert("", "end", values=("No data","””","””","””"))
                continue
            other = other_map[idx]
            other_by_name = {m['name']: m['pt'] for m in other['managers']} if other else {}
            for mg in data['managers']:
                tag   = pt_tag(mg['pt'])
                other_pt = other_by_name.get(mg['name'])
                if other_pt is not None and mg['pt'] is not None:
                    delta = round(mg['pt'] - other_pt, 1)
                    delta_str = f"+{delta}%" if delta >= 0 else f"{delta}%"
                    delta_tag = "lgreen" if delta > 0 else ("red" if delta < 0 else "na")
                else:
                    delta_str = "””"
                    delta_tag = "na"
                row_id = t.insert("", "end", values=(
                    mg['name'], pt_str(mg['pt']), mg['aa_count'], delta_str
                ), tags=(tag,))
            # Summary overall row
            if data.get('overall_pt') is not None:
                other_overall = other['overall_pt'] if other else None
                if other_overall:
                    delta = round(data['overall_pt'] - other_overall, 1)
                    ds = f"+{delta}%" if delta >= 0 else f"{delta}%"
                else:
                    ds = "””"
                t.insert("", "end", values=(
                    f"── OVERALL ({label_map[idx]})",
                    pt_str(data['overall_pt']), data['aa_count'], ds
                ), tags=(pt_tag(data['overall_pt']),))

        self._set_status(f"Week-over-Week: {d1} vs {d2}")

    # ─────────────────────────────────────────────────────────
    # Events & Helpers
    # ─────────────────────────────────────────────────────────
    def _on_flag_click(self, event):
        item = self._flag_tree.identify_row(event.y)
        if not item: return

        # Only act on AA child rows (parent = a manager header row)
        parent = self._flag_tree.parent(item)
        if not parent:
            return   # clicked a manager header ”” just expand/collapse, do nothing extra

        vals = self._flag_tree.item(item, "values")
        if not vals or not vals[0]:
            return
        badge = vals[0]
        name  = vals[1] if len(vals) > 1 else badge

        wh  = self._wh_var.get().strip().upper() or "CLE3"
        url = f"https://fclm-portal.amazon.com/employee/timeDetails?employeeId={badge}&warehouseId={wh}"
        webbrowser.open(url)
        self._set_status(f"Opened time card for {name}  (badge: {badge})")

    # ─────────────────────────────────────────────────────────
    # Feature: Auto-refresh
    # ─────────────────────────────────────────────────────────
    def _toggle_autorefresh(self):
        if getattr(self, '_autorefresh_on', False):
            self._autorefresh_on = False
            if hasattr(self, '_autorefresh_job'):
                self.after_cancel(self._autorefresh_job)
            self._auto_btn.configure(text="⟳ Auto", fg_color=BORDER, text_color=MUTED)
            self._set_status("Auto-refresh off.")
        else:
            self._autorefresh_on = True
            self._auto_btn.configure(text="◉ Live", fg_color="#1a3a1a", text_color=C_LGR)
            self._set_status("Auto-refresh on ”” fetching now…")
            self._on_fetch()

    # ─────────────────────────────────────────────────────────
    # Feature: Copy flagged list to clipboard
    # ─────────────────────────────────────────────────────────
    def _copy_flagged(self):
        key = self._last_data_key()
        if not key:
            return
        data = self._data.get(key)
        if not data:
            return
        threshold = float(self._thresh_var.get())
        date_str, shift_str = key.split("|")[0], key.split("|")[1]

        flagged = [a for a in data['associates']
                   if a['pt'] is not None and a['pt'] < threshold]
        if not flagged:
            self._set_status("Nothing to copy ”” no flagged associates.")
            return

        from collections import defaultdict
        by_mgr = defaultdict(list)
        for aa in flagged:
            by_mgr[aa['manager']].append(aa)
        sorted_mgrs = sorted(by_mgr,
            key=lambda m: sum(a['pt'] for a in by_mgr[m]) / len(by_mgr[m]))

        lines = [
            f"CLE3 Flagged Associates ”” {shift_str.split('(')[0].strip()} · {date_str}",
            "─" * 52,
        ]
        for mgr in sorted_mgrs:
            aa_list = sorted(by_mgr[mgr], key=lambda a: a['pt'])
            avg_pt  = sum(a['pt'] for a in aa_list) / len(aa_list)
            lines.append("")
            lines.append(f"{mgr}  ({len(aa_list)} flagged, avg {avg_pt:.1f}%)")
            for aa in aa_list:
                gap  = round(threshold - aa['pt'], 1)
                parts = aa['name'].strip().split()
                login = (parts[0][0] + parts[-1]).lower() if len(parts) >= 2 else aa['id']
                lines.append(
                    f"  · {aa['name']:<28} {login:<12} {pt_str(aa['pt']):<8} −{gap}%")
        lines += [
            "─" * 52,
            f"Total: {len(flagged)} flagged  ·  Threshold: {int(threshold)}%",
        ]

        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status(f"Copied {len(flagged)} flagged associates to clipboard.")

    # ─────────────────────────────────────────────────────────
    # Feature: Right-click context menu on flagged rows
    # ─────────────────────────────────────────────────────────
    def _on_flag_rightclick(self, event):
        item = self._flag_tree.identify_row(event.y)
        if not item: return
        if not self._flag_tree.parent(item): return   # manager header

        self._flag_tree.selection_set(item)
        vals  = self._flag_tree.item(item, "values")
        if not vals: return
        badge = item.replace("aa_", "")
        name  = vals[1] if len(vals) > 1 else badge

        menu = tk.Menu(self, tearoff=0,
                       bg=CARD, fg=TEXT, activebackground=BORDER,
                       activeforeground=TEXT, relief="flat", bd=0)
        menu.add_command(label=f"📈  View history for {name}",
                         command=lambda: self._show_history_popup(badge, name))
        menu.add_separator()
        menu.add_command(label="🌐  Open in FCLM",
                         command=lambda: self._on_flag_click_badge(badge, name))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ─────────────────────────────────────────────────────────
    # Feature: Associate history drill-down popup
    # ─────────────────────────────────────────────────────────
    def _show_history_popup(self, badge, name):
        hist_path = os.path.join(os.path.expanduser("~"),
                                 ".pt_dashboard", "associate_history.json")
        try:
            with open(hist_path) as fh:
                all_hist = json.load(fh)
            entries = all_hist.get(badge, {}).get("entries", [])
        except FileNotFoundError:
            entries = []
        except Exception:
            entries = []

        win = tk.Toplevel(self)
        win.title(f"History ”” {name}")
        win.configure(bg=BG)
        win.geometry("480x400")
        win.resizable(True, True)

        tk.Label(win, text=name, bg=BG, fg=ACCENT,
                 font=("Segoe UI", 14, "bold")).pack(pady=(14, 2))
        tk.Label(win, text=f"Badge: {badge}", bg=BG, fg=MUTED,
                 font=("Segoe UI", 10)).pack(pady=(0, 10))

        if not entries:
            tk.Label(win,
                     text="No history yet.\nHistory is recorded after 7 PM reports run.",
                     justify="center",
                     bg=BG, fg=MUTED, font=("Segoe UI", 11)).pack(pady=30)
            tk.Button(win, text="Close", command=win.destroy,
                      bg=BORDER, fg=TEXT, relief="flat",
                      font=("Segoe UI", 10)).pack(pady=10)
            return

        cols = ("Date", "Shift", "PT%")
        vsb  = ttk.Scrollbar(win, orient="vertical")
        vsb.pack(side="right", fill="y", padx=(0, 6))
        tree = ttk.Treeview(win, columns=cols, show="headings",
                            style="Dark.Treeview", yscrollcommand=vsb.set,
                            height=min(len(entries), 12))
        vsb.configure(command=tree.yview)
        for col, w in zip(cols, [120, 180, 90]):
            tree.heading(col, text=col)
            tree.column(col, width=w, anchor="center")
        for tag, color in [("red", C_RED), ("orange", C_ORA),
                           ("lgreen", C_LGR), ("dgreen", C_DGR)]:
            tree.tag_configure(tag, foreground=color)

        for e in entries:
            pt = e.get("pt")
            tree.insert("", "end",
                values=(e.get("date",""), e.get("shift",""), pt_str(pt)),
                tags=(pt_tag(pt),))
        tree.pack(fill="both", expand=True, padx=10)
        tk.Button(win, text="Close", command=win.destroy,
                  bg=BORDER, fg=TEXT, relief="flat",
                  font=("Segoe UI", 10)).pack(pady=10)


    # helper used by right-click menu's "Open in FCLM"
    def _on_flag_click_badge(self, badge, name):
        wh  = self._wh_var.get().strip().upper() or "CLE3"
        url = f"https://fclm-portal.amazon.com/employee/timeDetails?employeeId={badge}&warehouseId={wh}"
        webbrowser.open(url)
        self._set_status(f"Opened time card for {name}")

    def _open_fclm(self):
        url = self._last_url or 'https://fclm-portal.amazon.com'
        webbrowser.open(url)

    def _last_data_key(self):
        if self._data:
            return list(self._data.keys())[-1]
        return None

    def _sort_am(self, col):
        tree = self._am_tree
        # Only sort top-level rows
        items = [(tree.set(k, col), k) for k in tree.get_children("")]
        def key(x):
            v = x[0].replace('%','').replace('🥇','0').replace('🥈','1').replace('🥉','2').strip()
            try: return (0, float(v))
            except: return (1, v.lower())
        rev = getattr(tree, f'_sort_rev_{col}', False)
        items.sort(key=key, reverse=rev)
        for _, k in items:
            tree.move(k, "", "end")
        setattr(tree, f'_sort_rev_{col}', not rev)

    def _set_status(self, msg):
        self._status_var.set(msg)

# ─────────────────────────────────────────────────────────────

    def _check_for_updates(self):
        if not _updater:
            return
        def _on_update(new_ver):
            self.after(0, lambda: self._status_var.set(
                f'Updated to v{new_ver} — restart the app to apply.'))
        _updater.check(on_update_available=_on_update)

# Entry Point
# ─────────────────────────────────────────────────────────────
def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()



