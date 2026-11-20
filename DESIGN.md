# Snack Counter Automation

## How a refill works

1. Anyone can report an empty counter in company chat. If there is already a refill open for that office, the report points to the same refill. The service offers it to a volunteer who has checked in at that office. Visitors can check in too. I would give the first offer to someone with fewer outstanding reimbursements, then use past refill counts to spread the work.
2. The offer includes a spending cap. The volunteer has 24 hours to accept and another 24 hours to reach checkout. If the offer expires or the volunteer is no longer available, the next eligible person gets it. If nobody is available or the remaining budget is too small for a useful shop, the office coordinator can step in.
3. The volunteer enters the basket total and currency before paying. The service checks the assignment and budget and authorizes one buyer. The buyer pays, fills the counter, and uploads the receipt. If they stop responding after checkout, the coordinator checks whether they paid before giving the job to someone else.
4. The service sends HR the employee ID, amount, currency, description, and receipt. It uses the refill ID to avoid creating a second claim if HR receives a retry. The volunteer can see when HR approves and pays the claim. HR handles payroll conversion. I would flag claims still awaiting approval after 10 days for follow-up.

## What each part keeps

| Component | Data and responsibility |
| --- | --- |
| Company chat | Uses company identity for check-in and refill actions. Sends offers and claim updates privately. |
| Refill service | Stores office, assignee, deadline, volunteers already asked, spending cap, authorized amount and month, receipt reference, and claim ID. Updates assignments and budget in one transaction per office. |
| Claim worker | Keeps the submission job, refill reference, HR claim ID, status, and retry history. Receipt images belong in restricted storage. |
| Monthly report | Shows spending and budget in each office currency. Also shows a combined NOK total and the INR-to-NOK rate used to calculate it. |

Oslo gets 6,000 NOK per month and Bengaluru gets 15,000 INR. The cap is whichever is lower, the remaining budget or the high end of a typical purchase. An unpaid checkout can be released. Once the receipt is recorded, it counts toward the office budget even while HR is processing the claim. I used the office-local month of checkout authorization so a late receipt stays with its original reservation. The combined report uses a finance-supplied monthly rate and rounds once, after conversion.

## What I would keep simple

Check-in is a small extra step for volunteers, but it handles hybrid schedules and visitors without needing access to calendars or location data. To learn what people like, I would start with a short optional list of what was bought and an occasional office poll. Those give us purchase and preference data. Measuring consumption directly would need a different setup. I would leave out sensors, item-level inventory, receipt scanning, a separate app, and direct payouts.

I would confirm the reporting month, exchange rate, and handling of small balances with Finance. I would also ask HR whether the API can look up claims by refill reference and distinguish approval from payment. If a request times out and HR cannot tell us whether it went through, someone should reconcile it before we send it again.

The prototype keeps data in memory and simulates chat and HR. For a rollout I would add persistent storage, authenticated chat actions, expiring check-ins, and a durable queue for claims and notifications.

