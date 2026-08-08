CLE3 PT Dashboard
=================

First-time setup (each machine, one time only):
  1. Double-click setup.bat
  2. Wait for it to finish (installs Python packages + browser, ~2 min)

Every day:
  1. Double-click run.bat
  2. Firefox opens automatically at http://localhost:5050
  3. A Chromium window may pop up briefly for FCLM login - click through it once

Updates:
  The dashboard checks for updates automatically every time you run run.bat.
  When the AM pushes an update, you will get it the next time you open the app.
  Your data (history, actions) is never affected by updates.

Notes:
  - Keep the terminal window open while using the dashboard (closing it stops the server)
  - The dashboard auto-refreshes every 3 minutes from FCLM
  - Night shift = 6 PM - 6 AM, Day shift = 6 AM - 6 PM
  - PT threshold: green >= 88%, yellow 84-88%, red < 84%
