---
name: complainerr
description: File a public complaint, suggestion, compliment or enquiry (aduan, cadangan, penghargaan, pertanyaan) with a Malaysian agency through its SISPAA site, using the complainerr CLI. Use this whenever the user describes a local problem they want reported to the authorities (illegal parking, cars in motorcycle bays, potholes, clogged drains, rubbish, broken street lights, noise, stray animals in Subang Jaya / Puchong / USJ / Petaling Jaya), a JPJ matter (licence, road tax, vehicle registration), an overpricing or trader complaint for KPDN, a federal road or highway problem for KKR / JKR / LLM (the MyJalan app's job), or a civil-service matter for JPA, even if they never say "SISPAA" or "complainerr" — e.g. "report this to MBSJ", "lapor kepada MBPJ", "this shop overcharged me", "report this pothole on the federal road to JKR", "buat aduan", "complain to the majlis about this photo".
---

# Complainerr

Turn what the user tells you in chat into a filed SISPAA case. The user should only have to describe the problem (and maybe send a photo); you handle the agency choice, the wording, the CLI and the one-time code.

A filed case goes to a real government officer and cannot be withdrawn. That is why the flow below has a dry run and an explicit confirmation before anything is sent.

## 0. Find the CLI and the profile

- CLI: `command -v complainerr`, else `~/complainerr/.venv/bin/complainerr`. If neither exists, tell the user to run the install in the repo README and stop.
- Personal details (name, IC, mobile, email) come from `~/.config/complainerr/profile.toml` (or `$COMPLAINERR_PROFILE`). Read it once so you can show the user what will be sent. If it is missing, ask for the details and offer to create it from `profile.example.toml` in the repo (chmod 600). Never commit it.

## 1. Pick the agency (`--site`)

| Site | Use for | Extra field | Send step |
|---|---|---|---|
| `mbsj` | Majlis Bandaraya Subang Jaya area: Subang Jaya, USJ, Puchong, Seri Kembangan (if you are not sure an address is in this area, say so). Parking, roads, drains, rubbish, lights, hawkers, noise | `--location` (required) | Email OTP |
| `kkr` | Federal roads and Ministry of Works bodies: JKR (federal roads, e.g. a "FT" route number), LLM (tolled highways), CIDB. This replaces the MyJalan app for complaints | `--location` (required), `--agency` (pick the office) | reCAPTCHA token from the user's browser |
| `mbpj` | Majlis Bandaraya Petaling Jaya area: PJ, Damansara, Kelana Jaya, SS and PJU sections, Sunway. The same kinds of local problems as MBSJ | `--category`, `--location`, and the zone `--field cpLocation2=ID` | reCAPTCHA token from the user's browser |
| `jpj` | Road Transport Department: licences, road tax, vehicle registration, JPJ counters and officers, unsafe commercial vehicles | `--agency` (the state JPJ office), and `--field` for `rqAddr`, `rqPostcode`, `rqAge` (an age band) and `rqGender` | reCAPTCHA token from the user's browser |
| `kpdn` | Domestic Trade: overpricing, short weight, fake goods, petrol stations, controlled items | none | Email OTP |
| `jpa` | Public Service Department matters only: civil-service pay, pension, HR, exams, INTAN, scholarships | `--category` (required) | reCAPTCHA token from the user's browser |

If the problem belongs to another agency (another council, PDRM, TNB, Syabas/Air Selangor), say which body it belongs to and that complainerr does not support that site yet. Do not file it with another site just because that site works: a misrouted case wastes an officer's time and the user's report goes nowhere.

For MBPJ, find the zone with `complainerr --site mbpj zones <name>` (e.g. `zones "ss 2"`), and the category under `complainerr --site mbpj categories 2041`. For KKR and JPJ, list offices with `complainerr --site <site> agencies [PARENT]` and pick the most specific one (KKR: state JKR offices are under `50396`, highway offices under `28246`). For JPA, list categories with `complainerr --site jpa categories [PARENT]` and pick a selectable leaf (rows marked `[group]` need a child).

## 2. Gather the facts

You need: **type** (default `aduan` for a complaint), **what happens**, **where** (exact address or landmark), **when / how often**, and optionally a **photo** path. Ask only for what is missing, in one short message. Do not invent addresses, postcodes, house numbers, times or frequencies (leave out what you were not told); if you infer something (e.g. from a photo), say so when you show the draft.

## 3. Draft and confirm

Write:
- **Subject**: one line in Malay, under 100 characters, naming the problem and the place (the site upper-cases it).
- **Detail**: the Malay text first, then `---`, then `English:` and the same text in English. Plain and factual: what, where, when, what you ask the agency to do. If the problem only happens at certain times, ask them to check at those times — otherwise an officer checks at noon and closes the case.

Show the user the subject, both texts, the location, the photo name, and the personal details from the profile. Then ask them to reply "send" or to tell you what to change. Do not send until they confirm in their own words in this conversation.

## 4. Dry run

Write the command into a script so it is reproducible, e.g. `~/complainerr/cases/<yyyy-mm-dd>-<slug>.sh` (the `cases/` folder is git-ignored because it holds personal data):

```sh
#!/bin/sh
exec complainerr --site mbsj submit --type aduan \
  --subject "..." --detail "..." --location "..." --attach /path/photo.png "$@"
```

Run it without `--send` and check the printed payload: `cpTyp`, `cpSubject`, `cpLocation` or `cpCategory`, and the `rq*` fields. Fix any error it prints (missing location, group category, wrong type for the site) before going on. If it says `this site also needs <fields>`, ask the user for those values (JPJ: address, postcode, age band, gender) and add each as `--field NAME=VALUE`; never invent them.

## 5. Send

Only after the user's "send".

**MBSJ and KPDN (email OTP).** The CLI uploads the photo, asks the site to email a code, then waits for the code on stdin. Feed it through a pipe so you can pass the code in later:

```sh
mkfifo "$TMP/otp.fifo"
./case.sh --send <> "$TMP/otp.fifo" > "$TMP/send.log" 2>&1; echo "exit=$?" >> "$TMP/send.log"   # run in background
# wait until send.log contains "OTP sent to" (or an error / exit=)
```

Then ask the user for the 6-digit code from their email (in T3 Code use `request_secret` with file delivery; otherwise ask in chat). Write it plus a newline into the fifo within 5 minutes, wait for `exit=` in the log, and delete the fifo.

**JPA, KKR, MBPJ and JPJ (reCAPTCHA).** Complainerr does not solve or bypass the captcha, and you should not try to (no AI solvers, no `claude -p`): it is the site's anti-bot control. Ask the user to open the site's new-case page (`https://<site>.spab.gov.my/eApps/sdmscasepool/SdmsCasePool/add.do`) in their browser, tick "I'm not a robot", run `grecaptcha.getResponse()` in DevTools and send you the string. Then run the script with `--recaptcha-token <token> --send` within about 2 minutes.

## 6. Report

The reply page says "… <SITE>.<number> is your feedback reference ID". Give the user that reference ID first, the agency's reply window if the page states one, and that the ticket (with a password for status checks) was emailed to them. Guest cases do not appear on any account dashboard; they are checked with `complainerr --site <site> status <ID> --case-password <pw> --doc-no <IC>` or on the site's "Semak Aduan/Maklum Balas" page.

If the send fails, show the cause from the log and do not resend automatically: a second send can create a duplicate case.
