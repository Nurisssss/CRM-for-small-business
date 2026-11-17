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
Demo customer phones: `+7 700 000 01 01` ... `+7 700 000 01 04` (fictional)

## Test it
`python test_app.py` runs 15 tests (successful and unsuccessful cases). Each line shows ok or FAIL.

## Files
| File | What it is | Main owner for explaining it |
|---|---|---|
| schema.sql | tables, keys and rules (Task 9 design) | Inkar |
| data.sql | fictional sample data | Inkar |
| index.html | the screen the user sees | Almas |
| app.py - login, roles, passwords, transaction | security and the "record a purchase" transaction | Nurislam |
| test_app.py | 15 automated tests | Akbota |
| acceptance criteria of the main process | what "works" means | Aknur |

## What is NOT built yet (honest list)
- Registering a new customer and customer notes (next team milestone)
- Merging duplicate customers; the points rule is a proposal (1 point per whole currency unit) and must be confirmed
- Login protection against repeated wrong passwords; HTTPS; running on another computer (deployment guide)

## AI use (the team must keep this paragraph true)
The first version of the prototype code and the 15 tests was created with the help of an AI assistant (Claude) from our Task 9
database design. The team must be able to explain every part, run the tests themselves, and list what each person changed.
