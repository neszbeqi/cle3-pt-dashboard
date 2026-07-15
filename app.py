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
    import updater as _updater
except ImportError:
    _updater = None
try:
    import bmi as _bmi
except ImportError:
    _bmi = None

_CFG = fclm._CONFIG  # shared config (warehouse, pt_target, etc.)

# â”€â”€ Colors â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
    return f"{pt:.1f}%" if pt is not None else "â€”"

# â”€â”€ ttk dark style â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

# â”€â”€ Main App â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        self._data       = {}   # date_key â†’ processed data
        self._last_url   = ""
        self._build_ui()
        self._check_for_updates()

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Auto-load last 7 PM report snapshot
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # UI Construction
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build_ui(self):
        self._build_topbar()
        self._build_controls()
        self._cards_frame = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._cards_frame.pack(fill="x", padx=18, pady=(12, 0))
        self._build_tabs()

    def _build_topbar(self):
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=52)
        bar.pack(fill="x"); bar.pack_propagate(False)
        ctk.CTkLabel(bar, text="â—", text_color=ACCENT,
                     font=ctk.CTkFont(size=20)).pack(side="left", padx=(14,6), pady=0)
        ctk.CTkLabel(bar, text="CLE3 Â· Productive Time Dashboard",
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

        self._auto_btn = ctk.CTkButton(bar, text="âŸ³ Auto",
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
        for color, label in [(C_DGR,"â‰¥90%"),(C_LGR,"85-89%"),(C_ORA,"80-84%"),(C_RED,"<80%")]:
            ctk.CTkLabel(bar, text="â– ", text_color=color,
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

        for name in ["AM Rankings", "Flagged Associates", "Week-over-Week"]:
            self._tab.add(name)
            self._tab.tab(name).configure(fg_color=BG)

        self._build_am_tab()
        self._build_flagged_tab()
        self._build_wow_tab()

    # â”€â”€ AM Rankings Tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build_am_tab(self):
        parent = self._tab.tab("AM Rankings")
        cols = ("Rank", "Area Manager", "Team PT%", "Inferred Hrs", "Total Hrs", "AAs", "Flagged")

        f = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        f.pack(fill="both", expand=True, padx=4, pady=4)

        hint = ctk.CTkLabel(f, text="â–¶ Click an AM row to expand their associates",
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

    # â”€â”€ Flagged Associates Tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build_flagged_tab(self):
        parent = self._tab.tab("Flagged Associates")
        cols = ("Badge ID", "Associate Name", "PT%", "Inferred Hrs", "Total Hrs", "Gap to Target")

        f = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        f.pack(fill="both", expand=True, padx=4, pady=4)

        # â”€â”€ Filter bar: manager dropdown + search + copy button â”€â”€â”€
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
                     placeholder_text="name or badgeâ€¦").pack(side="left", padx=(0, 10))

        self._copy_btn = ctk.CTkButton(mgr_bar, text="ðŸ“‹ Copy List",
                                        command=self._copy_flagged,
                                        width=100, height=28,
                                        fg_color=BORDER, hover_color="#3a3d4a",
                                        text_color=TEXT, font=ctk.CTkFont(size=11))
        self._copy_btn.pack(side="left")

        hint = ctk.CTkLabel(f,
            text="â–¶ Click name â†’ FCLM  Â·  Right-click â†’ History",
            text_color=MUTED, font=ctk.CTkFont(size=11))
        hint.pack(anchor="w", padx=4, pady=(4, 4))

        vsb = ttk.Scrollbar(f, orient="vertical")
        vsb.pack(side="right", fill="y")

        self._flag_tree = ttk.Treeview(f, columns=cols, show="tree headings",
                                        style="Dark.Treeview", yscrollcommand=vsb.set)
        vsb.configure(command=self._flag_tree.yview)

        self._flag_tree.column("#0", width=22, stretch=False)
        widths = [110, 200, 85, 100, 90, 95]
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

    # â”€â”€ Week-over-Week Tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

            cols = ("Manager", "PT%", "AAs", "Î” vs other")
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

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Data Fetching
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _on_fetch(self):
        date  = self._date_var.get().strip()
        shift = self._shift_var.get()
        wh    = self._wh_var.get().strip().upper()
        if not date or not wh:
            messagebox.showwarning("Missing Info", "Please enter a date and warehouse ID.")
            return
        self._fetch_btn.configure(state="disabled", text="Fetchingâ€¦")
        self._set_status("Connecting to FCLMâ€¦")
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
        self._wow_btn.configure(state="disabled", text="Fetchingâ€¦")
        self._set_status(f"Fetching {d1} and {d2}â€¦")
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

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Rendering
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _render(self, data, date, shift):
        self._build_cards(data)
        self._render_am(data)
        self._refresh_flagged(data)
        lbl = shift.split('(')[0].strip()
        self._set_status(
            f"{lbl} Â· {date} Â· Overall PT: {pt_str(data['overall_pt'])} Â· "
            f"{data['aa_count']} AAs Â· {data['flagged']} flagged")

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
            medal = ["ðŸ¥‡","ðŸ¥ˆ","ðŸ¥‰"][i] if i < 3 else str(i+1)
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
"âœ“ No associates flagged", "", "", "", "", ""), tags=("detail",))
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
                gap   = round(threshold - aa['pt'], 1)
                tree.insert(mgr_id, "end",
                    iid=f"aa_{aa['id']}",
                    values=(aa['id'], aa['name'], pt_str(aa['pt']),
                            f"{aa['inferred']:.2f}", f"{aa['total']:.2f}",
                            f"âˆ’{gap}%"),
                    tags=(pt_tag(aa['pt']),))

    def _render_wow(self, d1, d2, data1, data2):
        self._wow_btn.configure(state="normal", text="Compare")
        label_map = {0: d1, 1: d2}
        other_map = {0: data2, 1: data1}

        for idx, data in enumerate([data1, data2]):
            t = self._wow_trees[idx]
            t.delete(*t.get_children())
            if not data:
                t.insert("", "end", values=("No data","â€”","â€”","â€”"))
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
                    delta_str = "â€”"
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
                    ds = "â€”"
                t.insert("", "end", values=(
                    f"â”€â”€ OVERALL ({label_map[idx]})",
                    pt_str(data['overall_pt']), data['aa_count'], ds
                ), tags=(pt_tag(data['overall_pt']),))

        self._set_status(f"Week-over-Week: {d1} vs {d2}")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Events & Helpers
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _on_flag_click(self, event):
        item = self._flag_tree.identify_row(event.y)
        if not item: return

        # Only act on AA child rows (parent = a manager header row)
        parent = self._flag_tree.parent(item)
        if not parent:
            return   # clicked a manager header â€” just expand/collapse, do nothing extra

        vals = self._flag_tree.item(item, "values")
        if not vals or not vals[0]:
            return
        badge = vals[0]
        name  = vals[1] if len(vals) > 1 else badge

        wh  = self._wh_var.get().strip().upper() or "CLE3"
        url = f"https://fclm-portal.amazon.com/employee/timeDetails?employeeId={badge}&warehouseId={wh}"
        webbrowser.open(url)
        self._set_status(f"Opened time card for {name}  (badge: {badge})")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Feature: Auto-refresh
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _toggle_autorefresh(self):
        if getattr(self, '_autorefresh_on', False):
            self._autorefresh_on = False
            if hasattr(self, '_autorefresh_job'):
                self.after_cancel(self._autorefresh_job)
            self._auto_btn.configure(text="âŸ³ Auto", fg_color=BORDER, text_color=MUTED)
            self._set_status("Auto-refresh off.")
        else:
            self._autorefresh_on = True
            self._auto_btn.configure(text="â—‰ Live", fg_color="#1a3a1a", text_color=C_LGR)
            self._set_status("Auto-refresh on â€” fetching nowâ€¦")
            self._on_fetch()

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Feature: Copy flagged list to clipboard
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
            self._set_status("Nothing to copy â€” no flagged associates.")
            return

        from collections import defaultdict
        by_mgr = defaultdict(list)
        for aa in flagged:
            by_mgr[aa['manager']].append(aa)
        sorted_mgrs = sorted(by_mgr,
            key=lambda m: sum(a['pt'] for a in by_mgr[m]) / len(by_mgr[m]))

        lines = [
            f"CLE3 Flagged Associates â€” {shift_str.split('(')[0].strip()} Â· {date_str}",
            "â”€" * 52,
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
                    f"  Â· {aa['name']:<28} {login:<12} {pt_str(aa['pt']):<8} âˆ’{gap}%")
        lines += [
            "â”€" * 52,
            f"Total: {len(flagged)} flagged  Â·  Threshold: {int(threshold)}%",
        ]

        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status(f"Copied {len(flagged)} flagged associates to clipboard.")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Feature: Right-click context menu on flagged rows
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        menu.add_command(label=f"ðŸ“ˆ  View history for {name}",
                         command=lambda: self._show_history_popup(badge, name))
        menu.add_separator()
        menu.add_command(label="ðŸŒ  Open in FCLM",
                         command=lambda: self._on_flag_click_badge(badge, name))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Feature: Associate history drill-down popup
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        win.title(f"History â€” {name}")
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
            v = x[0].replace('%','').replace('ðŸ¥‡','0').replace('ðŸ¥ˆ','1').replace('ðŸ¥‰','2').strip()
            try: return (0, float(v))
            except: return (1, v.lower())
        rev = getattr(tree, f'_sort_rev_{col}', False)
        items.sort(key=key, reverse=rev)
        for _, k in items:
            tree.move(k, "", "end")
        setattr(tree, f'_sort_rev_{col}', not rev)

    def _set_status(self, msg):
        self._status_var.set(msg)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _check_for_updates(self):
        if not _updater:
            return
        def _on_update(new_ver):
            self.after(0, lambda: self._status_var.set(
                f'Updated to v{new_ver} — restart the app to apply.'))
        _updater.check(on_update_available=_on_update)

# Entry Point
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()



