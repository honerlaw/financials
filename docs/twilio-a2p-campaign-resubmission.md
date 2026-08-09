# Twilio A2P 10DLC — campaign registration

**Current target: a Low-Volume Standard brand registered to Onerlaw LLC under its EIN.**
The Sole Proprietor path was abandoned after four failures; the last one was not fixable
by rewording. History is preserved in the appendix so the same ground is not re-walked.

| # | Error | Verdict | Outcome |
|---|-------|---------|---------|
| 1 | [30896](https://www.twilio.com/docs/api/errors/30896) | *"rejected because of provided Opt-in information"* | Fixed — public policy/terms/unsubscribe pages, real keywords, real consent description |
| 2 | [30914](https://www.twilio.com/docs/api/errors/30914) | *"sole proprietor campaign title does not match sole proprietor name"* | Moot under a Standard brand — rule is sole-prop-only |
| 3 | pre-submission check | *"campaign description doesn't match the use case type you selected"* | Moot — a real use case is now selectable |
| 4 | pre-submission check | *"reads as personal, person-to-person texting rather than business (A2P) messaging"* | **Root cause.** Drove the move to Onerlaw LLC |

## Why the sole proprietor path was abandoned

Failure 4 is a finding about eligibility, not phrasing:

> "Your description reads as personal, person-to-person texting rather than business (A2P)
> messaging. Describe the software or platform that sends the messages and how it serves
> your customers. Personal messaging between individuals isn't eligible for 10DLC."

The description said, accurately, that an individual sends texts to his own household.
That is very close to the definition of P2P, and 10DLC does not cover it. Rewriting it to
*sound* commercial while the registrant stayed an individual messaging his own household
would have been dressing up the same facts — the kind of thing that survives a checker and
fails at vetting, or later at audit.

Registering the entity that actually operates the software changes the facts rather than
the adjectives. Onerlaw LLC operates the dashboard; the dashboard sends the messages; the
recipients are opted-in registered users of it. All three statements are true, and
together they describe A2P messaging.

**This is only legitimate because the LLC really does operate this software.** If that
ever stops being true, the registration stops being accurate — do not keep it alive on
momentum.

### What the switch fixes for free

- **[30915](https://www.twilio.com/docs/api/errors/30915) exposure gone.** A corporate
  suffix in `brand_name` is a defect *for a sole proprietor brand* and correct for a
  Standard one. The old brand carried `Onerlaw LLC` on a `SOLE_PROPRIETOR` registration —
  a latent rejection that had not yet fired.
- **30914 gone.** The campaign-title-must-match-the-proprietor's-name rule applies only to
  sole proprietor brands. The title becomes `Onerlaw LLC`.
- **A use case that fits.** Sole prop brands get exactly one generic `SOLE_PROPRIETOR`
  bucket. A Standard brand can select `Account Notification`, which is what this traffic
  actually is.
- **Limits lift.** Sole prop caps at 1 campaign, 1 phone number, 1 MPS.

## Before registering

- [x] **EIN and legal business name.** The brand's legal business name must match how the
      entity is registered with the tax agency — Twilio's guidance is that it should
      "match how you registered with your country's tax agency". Copy it from the IRS EIN
      letter (CP 575) character for character, including whether it is `LLC` or `L.L.C.`.
      A near-miss here fails vetting.
- [x] **Business address, business website, business contact.** The website must be live
      and must describe the same thing the campaign describes.
- [x] **Public pages rewritten off "household."** Done in `onerlaw-www` — /terms,
      /privacy and /unsubscribe now describe Onerlaw LLC operating a dashboard for its
      registered users. Verified by grepping the *rendered* HTML after `npm run build`
      (`.next/server/app/*.html`), which is the check that repo's knowledge entry
      prescribes; zero "household" hits, all load-bearing A2P phrases still present.
      **⚠️ Must be deployed before submitting** — a reviewer reads the live site.
- [x] **Consent script republished.** The script in this doc and the blockquote on
      /terms are byte-identical. Reword one, reword the other in the same change.
- [ ] **A *business* primary customer profile.** ⚠️ *This is the real blocker.* The
      account's only Trust Hub profile is `BU705b57ee2280eb0909e27e39a73b0843` — labelled
      "Onerlaw LLC" but running policy `RNffcb02a20420c81caf596ffc44f69712`, which is
      **"Primary customer profile for individual"**. A Standard brand needs a *business*
      primary profile carrying the EIN, and Twilio's docs say an Individual profile's type
      cannot be changed after creation. Expect to create a new business profile, and to
      need Twilio support if the console will not let a second primary profile exist. Do
      this first — everything else is blocked behind it.
- [ ] **Retire or leave the old brand.** `BN7b34ddf2893d6ed15ea72161bc5d8ba8` (sole prop,
      APPROVED) has no campaign attached and can simply be left dormant. Do not attach the
      new campaign to it.

Rough costs, to confirm in console rather than trust here: Low-Volume Standard brand
registration is a small one-time fee (~$4.50), campaign vetting is a one-time fee (~$15),
and the campaign carries a monthly fee in the ~$1.50–$10 range depending on use case.

---

# Setting it up in Twilio

Everything happens on the [A2P onboarding page](https://console.twilio.com/us1/develop/sms/regulatory-compliance/a2p-onboarding);
the tabs run left to right in the order below.

## 1. Business primary customer profile — *Create Customer Profile* tab

The blocker above. The existing profile is an individual one and cannot be converted, so a
business profile has to exist before a Standard brand can be registered. Fields and the
rules that actually fail vetting:

| Field | Value | Rule |
|---|---|---|
| Legal business name | `Onerlaw LLC` | Must match the EIN letter (CP 575) exactly — `LLC` vs `L.L.C.` matters |
| Business type | `LLC` | |
| Industry / vertical | `TECHNOLOGY` | Matches the vertical already on the old brand |
| Tax ID | the EIN, formatted `00-0000000` | Use the EIN, never a DUNS number |
| Website | `https://onerlaw.com` | Verified by automated screenshot — must be live, not parked, no login wall, no redirect elsewhere |
| Address | the LLC's registered address | One address can back at most 10 TCR registrations |
| Authorized rep | name, job title, `derek@onerlaw.com`, phone in E.164 | Business email, not a free provider |

Approval takes **up to 72 hours**, but you can continue to the next step while it is
pending.

**If the EIN was issued recently**, expect trouble: IRS records take 30–90 days to
propagate to the vetting vendors, and a lookup miss reads as a name mismatch.

## 2. Register the brand — *Register Brand* tab

Choose **Low-Volume Standard** (suited to under 6,000 message segments/day — this sends
about 7 per user per week). Supply a brand contact email; identity is confirmed by 2FA to
it. TCR usually answers in minutes; anything needing manual review takes seven or more
business days.

Leave the old sole proprietor brand `BN7b34ddf2893d6ed15ea72161bc5d8ba8` alone. It has no
campaign attached and can sit dormant — just do not attach the new campaign to it.

## 3. Messaging service and number — already done

`MG29a7b84c2ca3db80ff108d72534d7254` exists with one 10DLC number in its sender pool,
`+1 980 217 7693` (SMS/MMS/Voice). Reuse it. Every number that will send A2P traffic must
be in the sender pool **before** the campaign is submitted.

## 4. Register the campaign — *Campaign Registration* tab

Select the new brand, pick use case **Account Notification**, link the messaging service,
and paste the field-by-field answers below. Run Twilio's check-campaign tool before
submitting — three of the four failures in the log above were the kind it catches for free.

Campaign review is quoted at **two to three weeks**, currently running 10–15 days.

## 5. After approval

Confirm real traffic still matches the filed samples. `BRAND` in `app/notifications.py` is
the coupling: changing it changes every message, so it means re-filing samples.

---

# Field-by-field answers

`Onerlaw LLC` is the legal business name, the brand name, the campaign title, and the
brand string in message copy. One name everywhere — the two name-mismatch failures in the
appendix both came from that not being true.

## Legal business name / Brand name

```
Onerlaw LLC
```

Must match the EIN letter exactly.

## Campaign title

```
Onerlaw LLC
```

## Use case

```
Account Notification
```

Recurring operational notifications about the state of a user's own account. Not Marketing
(nothing promotional is ever sent), not Customer Care (no support conversation), not 2FA.

## Campaign description

```
Onerlaw LLC operates Onerlaw, a web-based personal finance dashboard. Users link their bank and credit card accounts to the platform through Plaid, and the platform tracks their spending against a weekly budget they set. This campaign sends operational account notifications to registered users of that platform who have opted in to receive them. Each morning the platform sends one message reporting the user's spending so far that week against their budget, followed by the current balance of each linked account. A user can also trigger that same summary for themselves from inside the dashboard. Volume is about seven messages per user per week. The messages are transactional only, contain no marketing or promotional content, identify Onerlaw LLC as the sender, and carry STOP opt-out instructions.
```

Describes the software, who it serves, and what the messages contain — the three things
failure 4 asked for. It does not claim a customer base larger than the real one; a small
user count is not a disqualifier, but an invented one is a misrepresentation.

The on-demand summary is described on purpose. It is real traffic (work unit 017), and
campaign-to-traffic mismatch is a violation even after approval — so it cannot be omitted
just because the description reads more cleanly without it.

## Sample message #1

```
Onerlaw LLC
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
Onerlaw LLC
Good morning — Sat Aug 15

Budget: $1,043 of $1,000 (104%) — $43 OVER
Week of Aug 9

Balances
Truist · Checking ••3390: $4,206.11

Reply STOP to unsubscribe.
```

## Sample message #3

```
Onerlaw LLC
Good morning — Mon Aug 17

Budget: $120 of $1,000 (12%) — $880 left
Week of Aug 16

Balances
Truist · Checking ••3390: $4,206.11 (reconnect needed)

Reply STOP to unsubscribe.
```

Generated from `digest_body` in `app/notifications.py`, not written by hand. `BRAND` there
is `Onerlaw LLC`; changing it means re-filing these samples.

## Content flags

Leave **all four unchecked**:

- [ ] Embedded links — the digest contains none
- [ ] Phone numbers — the digest contains none
- [ ] Direct lending or other loan arrangement — this flag is about loan *offers and
      services*; reporting a balance on a user's own linked loan account is not that
- [ ] Age-gated content

If a link is ever added to the message body, come back and check the first box.

## Privacy policy link

```
https://onerlaw.com/privacy
```

States that **mobile numbers are not shared with third parties or affiliates for marketing
or promotional purposes**, and carries message frequency plus the "message and data rates
may apply" disclosure — all three are explicit requirements.

## Terms of service link

```
https://onerlaw.com/terms
```

## How do end-users consent to receive messages?

```
Onerlaw LLC collects consent verbally and in person before any number is added to the platform's notification list. There is no public sign-up form for SMS and no purchased or imported lists; a number reaches the list only when a user has agreed out loud to receive these messages.

The exact script used is: "I want to add your mobile number to your Onerlaw account so the dashboard can text you. It will send you one message each morning with your spending for the week so far and the balances of your linked accounts — about seven messages a week — and you can request one yourself from the dashboard at any time. Message and data rates may apply. Reply STOP at any time to stop receiving them, or HELP for help. Do you agree to receive these messages?" A number is added only after the user answers yes.

That script is published verbatim, along with the program description, message frequency, and opt-out instructions, at https://onerlaw.com/terms. Opt-out instructions are also at https://onerlaw.com/unsubscribe. Terms: https://onerlaw.com/terms Privacy: https://onerlaw.com/privacy
```

Twilio's requirement for verbal opt-in is that the exact script be described *and hosted
publicly* for reviewer verification — that public copy is what makes verbal consent
checkable. So this block and the terms page must be word-for-word identical. Reword one,
reword the other in the same change.

## Opt-in keywords

```
START, UNSTOP
```

## Opt-in message

```
Onerlaw LLC: You're subscribed to daily budget and account balance summaries, about 7 msgs/week. Msg & data rates may apply. Reply HELP for help, STOP to unsubscribe.
```

## Opt-out keywords

```
STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, QUIT
```

## Opt-out message

```
Onerlaw LLC: You have been unsubscribed and will receive no further messages from this number. Reply START to resubscribe.
```

## Help keywords

```
HELP, INFO
```

## Help message

```
Onerlaw LLC: daily budget and account balance summaries, about 7 msgs/week. For help contact derek@onerlaw.com. Msg & data rates may apply. Reply STOP to unsubscribe.
```

---

# Appendix — the sole proprietor attempt

Kept so the same ground is not re-walked. None of this applies to a Standard brand.

## Failure 1 (30896) — opt-in information

Five mechanical failures and one judgment failure. The literal `[BRAND]` placeholder was
real but the least of them.

1. **Privacy policy link blank** — a named rejection cause.
2. **Terms of service link blank** — same.
3. **Opt-out keywords blank.**
4. **Help keywords blank.**
5. **Opt-in keywords blank** while the opt-out message promised "Reply START to
   resubscribe" — an internal contradiction a vetter will catch.
6. **Consent description described no consent process.** "I am consenting myself by
   entering phone numbers directly into our secrets manager" reads as an absence of
   opt-in.

Also caught at the time: the submitted **sample messages were from the retired
threshold-alert design** (work unit 012, deleted in unit 016), while real traffic was the
daily digest. Campaign-to-traffic mismatch is a violation even after approval.

All six fixes carried forward to the Standard submission above.

## Failure 2 (30914) — three names on one brand

The console's *"friendly name to differentiate this registration"* read `Onerlaw LLC`, but
a friendly name is a local label, not a vetted value. The API showed three different names:

```
GET https://messaging.twilio.com/v1/a2p/BrandRegistrations
  → brand_type: SOLE_PROPRIETOR, status: APPROVED, identity_status: VERIFIED
    sid BN7b34ddf2893d6ed15ea72161bc5d8ba8, tcr_id BBCGKNE
    customer_profile_bundle_sid BU705b57ee2280eb0909e27e39a73b0843
    a2p_profile_bundle_sid       BUc232f3d988c0a02db0a182e744b52c9e

GET https://trusthub.twilio.com/v1/CustomerProfiles/{bundle}/EntityAssignments
GET https://trusthub.twilio.com/v1/EndUsers/{IT…}
  → individual_customer_profile_information: first_name "Derek", last_name "Honerlaw"
  → sole_proprietor_information:             brand_name "Onerlaw LLC"
```

| Name | Where it lives | Vetted as the sole proprietor name? |
|---|---|---|
| `Onerlaw LLC` | console friendly name, and `brand_name` on the sole-proprietor end user | No |
| `Derek Honerlaw` | `first_name` / `last_name` on the individual customer profile | **Yes** |

**Lesson worth keeping: never take a name from the console UI.** Read it from the API.

## Failure 3 — description named a different use case

The description opened with *"Recurring daily account notifications…"* while the selected
use case was `SOLE_PROPRIETOR`. "Account Notification" is the name of a *different* TCR use
case, so the checker saw one thing described and another selected. A sole prop brand is
offered exactly one use case, confirmed against the API:

```
GET https://messaging.twilio.com/v1/Services/{MG…}/Compliance/Usa2p/Usecases\
      ?BrandRegistrationSid=BN7b34ddf2893d6ed15ea72161bc5d8ba8
  → [{"code": "SOLE_PROPRIETOR", "name": "Sole Proprietor",
      "description": "Sole Proprietor campaign for customers with low traffic volumes"}]
```

matching the guide: *"For a Sole Proprietor Brand, there is only a single Sole Proprietor
use case; this will be the one item that can be selected in the dropdown."* Under a
Standard brand this failure cannot recur — `Account Notification` is both selectable and
accurate.

## Sources

- [Error 30896 — Campaign vetting rejection, Opt-in Error](https://www.twilio.com/docs/api/errors/30896)
- [Error 30914 — Sole proprietor campaign title does not match sole proprietor name](https://www.twilio.com/docs/api/errors/30914)
- [Error 30915 — Sole proprietor classification invalid](https://www.twilio.com/docs/api/errors/30915)
- [Error 30925 — Opt-in must be unchecked by default](https://www.twilio.com/docs/api/errors/30925)
- [Direct Sole Proprietor Registration Overview](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/direct-sole-proprietor-registration-overview)
- [Direct Standard and Low-Volume Standard Registration Guide](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/direct-standard-onboarding)
- [A2P 10DLC pricing and fees](https://support.twilio.com/hc/en-us/articles/1260803965530-What-pricing-and-fees-are-associated-with-the-A2P-10DLC-service)
- [Troubleshooting and rectifying A2P Campaigns](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/troubleshooting-a2p-brands/troubleshooting-and-rectifying-a2p-campaigns)
