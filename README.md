# Snack Counter Automation

A Python 3.10+ prototype for the Framsikt take-home. It runs with the standard library.

- [DESIGN.md](DESIGN.md) explains how a refill works and where I would draw the line for a first release.
- [snack_counter.py](snack_counter.py) contains the refill service and stand-ins for chat and HR.
- [test_snack_counter.py](test_snack_counter.py) shows how the service behaves when volunteers compete for a refill, an assignment expires, an office runs low on budget, or HR receives a retry.

Run the tests from this directory with `python -m unittest -v`.

For a walkthrough, start with the duplicate-report test, then look at what happens when a volunteer misses their deadline. The HR retry test shows how a receipt becomes a paid claim even if the first submission response is lost.

The tests use fake employees, receipts, and exchange rates. Amounts are stored in minor units, so 30,000 represents 300.00 NOK or INR depending on the office.

