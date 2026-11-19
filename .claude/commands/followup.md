# /followup - Who to Follow Up With, and a Draft for Each

You are checking the application pipeline for follow-ups that are due and drafting short, specific follow-up messages. Silence after applying or interviewing is normal; one or two well-timed, polite nudges measurably help, and more than that hurts.

**This command never sends anything.** It drafts text for the user to send themselves, and only records a follow-up in the tracker after the user confirms they sent it.

Follow these steps **in order**.

---

## Step 0: Parse Input

`$ARGUMENTS` may contain:

- Nothing → show every application with a follow-up due
- A company (optionally with a role) → only that application, due or not
- `--all` → also list open applications that are not yet due, with when they will be
- `--sent <company>` → record that a follow-up (or thank-you note) for that application was sent today, then stop (Step 4 only)

---

## Step 1: Compute What Is Due

```bash
python tools/followup_due.py          # add --all for not-yet-due ones
```

It reads `job_search_tracker.csv` (plus stage dates in `documents/applications/<company>_<role>/outcome.md`) and returns, per open application, the last activity date, days elapsed, follow-ups already sent, and an `action`:

| action | Cadence | What to draft |
|--------|---------|---------------|
| `send_thank_you` | interview in the last day, no thank-you logged | Thank-you note to the interviewer(s) |
| `first_follow_up` | applied, 7+ days of silence | Short polite status check |
| `final_follow_up` | 10+ days after the first follow-up | Last, brief nudge; reaffirm interest |
| `interview_check_in` | 7+ days after an interview stage | Check-in on next steps |
| `interview_second_check_in` | 14+ days after the first check-in | Final check-in |
| `consider_outcome` | two follow-ups, still silent | No draft - suggest `/outcome <company>` to record `no_response` |
| `respond_to_offer` | status is `offer` | No draft - remind the user of any decision deadline |
| `missing_date` | tracker row has no date | Ask the user when they applied and fix the row |

If the tracker does not exist or nothing is due, say so in one line and stop.

---

## Step 2: Present the List

```
Follow-ups due (<today>)

| # | Company | Role | Status | Last activity | Days | Sent | Action |
```

Ask which ones to draft (default: all with a draft-type action).

---

## Step 3: Draft the Messages

For each selected application, read only what is needed:

- the tracker row (`contact_person`, `channel`, `notes`, `source`)
- `documents/applications/<company>_<role>/outcome.md` and `job_posting.md` if they exist (stages, interviewer names, feedback)
- `.claude/skills/job-application-assistant/03-writing-style.md` for tone

Write each draft:

- **Language:** the posting's language (Danish posting → Danish message), unless the application was in another language.
- **Recipient:** the `contact_person` if known; otherwise "Hi <Company> recruiting team". If there is no known email or contact, say so and suggest where to send it (the application portal's message feature, or the recruiter on LinkedIn - the `/scrape` referral links can help find them).
- **Length:** 60-120 words. A subject line for email.
- **Content:** reference the exact role (and requisition ID if the posting has one), the date applied or interviewed, **one** concrete point from the posting or interview that connects to the candidate's real experience, and a clear, low-pressure ask (any update on timeline / next steps). Thank-you notes mention something specific that was discussed.
- **Honesty:** never invent conversations, names, or details that are not in the archive or the profile. If the interviewer's name is unknown, do not guess one.
- **Tone:** confident, not apologetic, no guilt-tripping ("just following up again..."), no em-dashes, no clichés (per `03-writing-style.md`). The final follow-up is shorter than the first.

Save each draft to `documents/applications/<company>_<role>/followup_<YYYY-MM-DD>.md` (create the folder if needed - `documents/applications/` is gitignored personal data) and show it in the chat.

If the user has a mail connector and asks for it, you may create an email **draft** there - never send. Confirm the recipient address with the user first.

---

## Step 4: Record What Was Sent

Only after the user says a message was sent (now, or later via `/followup --sent <company>`):

- Append to the tracker row's `notes` column: `<YYYY-MM-DD> follow-up sent` (or `<YYYY-MM-DD> thank-you sent` for thank-you notes). This exact wording is what `tools/followup_due.py` counts, and the date resets the cadence clock.
- If `outcome.md` exists, append the same dated line under `## Notes`.

Never restructure the CSV, reorder rows, or touch other rows. Never mark something as sent that the user has not confirmed.

---

## Step 5: Wrap Up

One line per application: drafted / skipped / recorded as sent, plus the date the next follow-up would be due. For any `consider_outcome` rows, suggest `/outcome <company>`.
