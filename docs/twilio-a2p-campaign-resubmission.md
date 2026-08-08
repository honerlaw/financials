# Twilio A2P 10DLC — campaign resubmission

Rejection received: *"The campaign submission has been reviewed and it was rejected
because of provided Opt-in information."* (Twilio error
[30896](https://www.twilio.com/docs/api/errors/30896).)

## Why it was rejected

Five mechanical failures and one judgment failure. The literal `[BRAND]` placeholder
was real but the least of them.

1. **Privacy policy link blank** — a named rejection cause.
2. **Terms of service link blank** — same.
3. **Opt-out keywords blank.**
4. **Help keywords blank.**
5. **Opt-in keywords blank** while the opt-out message promises "Reply START to
   resubscribe" — an internal contradiction a vetter will catch.
6. **Consent description described no consent process.** "I am consenting myself by
   entering phone numbers directly into our secrets manager" reads to a reviewer as
   an absence of opt-in. Twilio's requirement for verbal opt-in is that you describe
   the exact script *and host it publicly* for reviewer verification.

Additional problem not flagged by the rejection but worth fixing now: the submitted
**sample messages are from the retired threshold-alert design** (work unit 012,
deleted in unit 016). Real traffic is the daily digest with account balances at
~7/week, not "budget alert" threshold texts at 3/week. Twilio treats
campaign-to-traffic mismatch as a violation even after approval.

## Before resubmitting

Status of the prerequisites:

- [x] **Public privacy policy** — https://onerlaw.com/privacy (onerlaw-www). Now carries
      message frequency, a "message and data rates may apply" disclosure, the CTIA
      no-sharing statement, and opt-out instructions.
- [x] **Public terms of service** — https://onerlaw.com/terms (onerlaw-www). Now carries
      the concrete program description and the **exact verbal consent script**, which is
      what satisfies Twilio's "host it publicly for reviewer verification" requirement
      for verbal opt-in.
- [x] **Public unsubscribe page** — https://onerlaw.com/unsubscribe (onerlaw-www), linked
      from the site footer and from both legal pages.
- [x] **Brand line in `digest_body`** (`app/notifications.py`) — the digest now opens with
      `Onerlaw` and closes with `Reply STOP to unsubscribe.`, so the business name and
      opt-out language appear in every message and real traffic matches the samples below.
      The samples below are generated from that code, not written by hand.

All prerequisites are met. The campaign is ready to resubmit once `Onerlaw` is confirmed
consistent with the registered Brand in the console.

---

# Field-by-field answers

`Onerlaw` is the brand string used in message copy; the registered Brand is
**Onerlaw LLC**. Confirm the two are consistent in the console before submitting.

## Campaign description

```
Recurring daily account notifications for a private, non-commercial household finance dashboard. Each morning the account owner and household members who have opted in receive one text summarizing the current week's spending against the household budget, plus the current balance of each linked bank account. Recipients can also request the same summary on demand from inside the dashboard. No marketing or promotional content is ever sent, and the recipient list is limited to the account owner's own household.
```

## Sample message #1

```
Onerlaw
Good morning — Sat Aug 8

Budget: $750 of $1,000 (75%) — $250 left
Week of Aug 2

Balances
Truist · Checking ••3390: $4,880.02
Citi · Double Cash ••1234: $612.40

Reply STOP to unsubscribe.
```

## Sample message #2

```
Onerlaw
Good morning — Sat Aug 15

Budget: $1,043 of $1,000 (104%) — $43 OVER
Week of Aug 9

Balances
Truist · Checking ••3390: $4,206.11

Reply STOP to unsubscribe.
```

## Sample message #3

```
Onerlaw
Good morning — Mon Aug 17

Budget: $120 of $1,000 (12%) — $880 left
Week of Aug 16

Balances
Truist · Checking ••3390: $4,206.11 (reconnect needed)

Reply STOP to unsubscribe.
```

Samples #4 and #5: leave blank.

## Content flags

Leave **all four unchecked**:

- [ ] Embedded links — the digest contains none
- [ ] Phone numbers — the digest contains none
- [ ] Direct lending or other loan arrangement — this flag is about loan *offers and
      services*; reporting a balance on your own linked loan account is not that
- [ ] Age-gated content

If a link is ever added to the message body, come back and check the first box.

## Privacy policy link

```
https://onerlaw.com/privacy
```

Live. States that **mobile numbers are not shared with third parties or affiliates for
marketing or promotional purposes**, and carries message frequency plus the "message and
data rates may apply" disclosure — all three are explicit requirements.

## Terms of service link

```
https://onerlaw.com/terms
```

## How do end-users consent to receive messages?

```
This is a private, non-commercial program. The only recipients are the account owner and members of the account owner's household. There is no public sign-up and no third party is ever messaged.

Consent is collected verbally and in person using this exact script: "I want to add your mobile number to Onerlaw, our household budget dashboard. It will text you once each morning with our weekly spending total and our account balances — about 7 messages a week — and you can request one yourself from the dashboard. Message and data rates may apply. Reply STOP at any time to stop receiving them, or HELP for help. Do you agree to receive these messages?" A number is added to the recipient list only after the person answers yes.

That script is published verbatim, along with the program description, message frequency, and opt-out instructions, at https://onerlaw.com/terms. Opt-out instructions are also at https://onerlaw.com/unsubscribe. Terms: https://onerlaw.com/terms Privacy: https://onerlaw.com/privacy
```

Drop the secrets-manager sentence entirely. The script above is published verbatim at
https://onerlaw.com/terms under "SMS notification program", which is what makes the
verbal opt-in verifiable to a reviewer. Opt-out instructions also live at
https://onerlaw.com/unsubscribe, linked from the footer of every page.

## Opt-in keywords

```
START, UNSTOP
```

## Opt-in message

```
Onerlaw: You're subscribed to daily budget and account balance alerts, about 7 msgs/week. Msg & data rates may apply. Reply HELP for help, STOP to unsubscribe.
```

## Opt-out keywords

```
STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, QUIT
```

## Opt-out message

```
Onerlaw: You have been unsubscribed and will receive no further messages from this number. Reply START to resubscribe.
```

## Help keywords

```
HELP, INFO
```

## Help message

```
Onerlaw: daily budget and account balance alerts, about 7 msgs/week. For help contact derek@onerlaw.com. Msg & data rates may apply. Reply STOP to unsubscribe.
```

---

## Open question

Check what **brand type** you registered. If you filed as Standard / Low-Volume
Standard for what is a personal household app with no business entity, that mismatch
may compound the problem — Twilio's Sole Proprietor path (no EIN, 1 campaign, 1
number, low throughput) is the closer fit. Verify current sole-proprietor opt-in
rules in the console before resubmitting.

## Sources

- [Error 30896 — Campaign vetting rejection, Opt-in Error](https://www.twilio.com/docs/api/errors/30896)
- [Error 30925 — Opt-in must be unchecked by default](https://www.twilio.com/docs/api/errors/30925)
- [Troubleshooting and rectifying A2P Campaigns](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/troubleshooting-a2p-brands/troubleshooting-and-rectifying-a2p-campaigns)
- [Why Was My A2P 10DLC Campaign Registration Rejected?](https://help.twilio.com/articles/15778026827291-Why-Was-My-A2P-10DLC-Campaign-Registration-Rejected-)
