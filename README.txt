PT Dashboard — Quick Start
==========================

FIRST TIME SETUP (do this once)
--------------------------------
1. Unzip this folder anywhere on your computer (e.g. Desktop or Documents).
2. Double-click setup.bat and let it run (~2-3 minutes).
   - It installs Python packages and downloads the browser engine.
   - It creates a "PT Dashboard" shortcut on your Desktop.
3. Done. Use the Desktop shortcut from now on.

DAILY USE
---------
1. Double-click "PT Dashboard" on your Desktop.
2. Enter the shift date (defaults to today) and click Fetch.
3. The first Fetch will open a browser for your FCLM login (Midway).
   After logging in once, future fetches run silently — no visible browser.

CONFIGURE FOR YOUR FC
----------------------
Open config.json in Notepad and edit:
  - "warehouse_id"  — your FC code (e.g. "CMH2", "IND9")
  - "process_id"    — your FC's stow process ID (find it in the FCLM URL)
  - "pt_target"     — your PT% goal (default 84)

TABS
----
- AM Rankings       — ranked list of managers by team PT%
- Flagged Associates — associates below the PT target, grouped by manager
  - Click a name → opens their FCLM time card
  - Right-click   → view history or add a note
- Week over Week    — compare two dates side by side

QUESTIONS / ISSUES
------------------
Contact: neszbeqi (CLE3)
