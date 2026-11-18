# CRM for Small Business - prototype (Week 10)

Main process: an employee logs in, finds a loyalty customer by phone, adds products, gets the (simulated) card terminal
result, and the purchase is saved in ONE transaction (stock and loyalty points updated, or everything rolled back).
Managers can also open two reports. Only the Python standard library is used: nothing to install except Python 3.9+.

## Run it
1. Put all files in one folder and open a terminal in it.
2. `python app.py`   (on some computers: `python3 app.py`)
3. Open http://localhost:8000 in the browser. The database file `crm.db` is created automatically on first run.
   To reset the demo data, stop the program and delete `crm.db`.

Demo logins (change them before any real use):
- Employee: `aruzhan` / `cashier123`
- Manager:  `daniyar` / `manager123`
Shop code needed to register a new employee: `SHOP-2026` (set your own with `CRM_SHOP_CODE=yourcode python app.py`).
Demo customer phones: `+7 700 000 01 01` ... `+7 700 000 01 04` (fictional)

## Test it
`python test_app.py` runs the main tests (successful and unsuccessful cases). Each line shows ok or FAIL.
`python test_security.py` runs 4 security tests (login lock after 5 wrong attempts, 30-minute session expiry, shop code for registration).
`python test_points_rule.py` runs 7 tests of the points rule (3 % earn, 30 % spend limit, 5,000 cap, rollback, ledger).

## Backup and restore (Inkar)
`python backup_db.py backup` copies `crm.db` to `backups/crm_YYYY-MM-DD_HH-MM-SS.db` (safe while the program is running).
`python backup_db.py list` shows the backups. `python backup_db.py restore` brings back the newest backup
(`restore FILE` for a chosen one; it asks you to type YES, or add `--yes`). Before every restore the current data is saved as
`backups/crm_before_restore_<date>.db`, so a restore can itself be undone. Stop and start `python app.py` after a restore.
Demo: register a customer, run `backup`, then `python backup_db.py delete-customer "+7 777 123 45 67"`, then `restore`: the customer is back.
`python test_backup.py` runs 6 tests on a temporary database (never on your real `crm.db`).

## Files
| File | What it is | Main owner for explaining it |
|---|---|---|
| schema.sql | tables, keys and rules (Task 9 design) | Inkar |
| data.sql | fictional sample data | Inkar |
| index.html | the screen the user sees | Almas |
| app.py - login, roles, passwords, transaction | security and the "record a purchase" transaction | Nurislam |
| backup_db.py, test_backup.py | backup, restore, and their 6 tests | Inkar |
| test_app.py | 15 automated tests | Akbota |
| docs/ERD_6_tables.png, docs/points_rule.md, docs/acceptance_criteria.md, test_points_rule.py | 6-table ERD, points rule, 6-step transaction, 8 acceptance criteria linked to tests | Aknur |

## What is NOT built yet (honest list)
- Customer notes (next team milestone)
- Merging duplicate customers (SQL script only, no screen); the points rule (3 %, 1 point = 1 cent, 30 % limit, 5,000 cap) is in `docs/points_rule.md` and must be confirmed by the team
- HTTPS; running on another computer (deployment guide)

## AI use (the team must keep this paragraph true)
The first version of the prototype code and the 15 tests was created with the help of an AI assistant (Claude) from our Task 9
database design. The team must be able to explain every part, run the tests themselves, and list what each person changed.