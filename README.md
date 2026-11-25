<p align="center"><img src="logo.svg" width="128" alt="Complainerr logo: an angry blond woman with a short bob and a fringe over one eye"></p>

# Complainerr

Complainerr is a CLI (and a Python library) that files complaints on SISPAA, the Malaysian public complaint portal. Each agency runs its own copy of SISPAA. This library supports these copies:

| `--site` | Agency | URL | Before a submit |
|---|---|---|---|
| `jpa` (default) | Jabatan Perkhidmatan Awam | <https://jpa.spab.gov.my/eApps> | A category, and a reCAPTCHA token that you get in a browser |
| `mbsj` | Majlis Bandaraya Subang Jaya | <https://mbsj.spab.gov.my/eApps> | A location, and a one-time code (OTP) that the site sends to your email |
| `kkr` | Kementerian Kerja Raya (Ministry of Works: JKR, LLM, CIDB) | <https://kkr.spab.gov.my/eApps> | A location, an agency (optional), and a reCAPTCHA token that you get in a browser |
| `mbpj` | Majlis Bandaraya Petaling Jaya | <https://mbpj.spab.gov.my/eApps> | A category, a location, a zone (`--field cpLocation2=ID`), and a reCAPTCHA token |
| `jpj` | Jabatan Pengangkutan Jalan (road transport) | <https://jpj.spab.gov.my/eApps> | An agency (optional), your address, postcode, age band and gender (`--field`), and a reCAPTCHA token |
| `kpdn` | Kementerian Perdagangan Dalam Negeri dan Kos Sara Hidup (prices, traders) | <https://kpdn.spab.gov.my/eApps> | An email OTP, as on MBSJ |

## Fields that only some sites ask for

Each site sets its own required fields. Before a dry run prints the payload, the client reads the required fields from the page JavaScript. If one is empty, it stops and names each one. Give each such field with `--field NAME=VALUE`. If the field is a drop-down list, the error names each valid choice. The "Telephone" field (`rqPhone`) gets your mobile number.

```sh
# JPJ: address, postcode, age band (2630 = 26-30) and gender
complainerr --site jpj submit ... --field "rqAddr=1 Jalan X, Puchong" --field rqPostcode=47100 \
  --field rqAge=2630 --field rqGender=M

# MBPJ: find the zone id, then give it with the category and location
complainerr --site mbpj zones "ss 2"       # 2669  ZON 8 > SS 2
complainerr --site mbpj categories 2041   # the council's categories, e.g. 2048 parking
complainerr --site mbpj submit ... --category 2048 --location "..." --field cpLocation2=2669
```

A dry run on 2026-11-25 against the real MBPJ, JPJ and KPDN sites gave the expected payload. No real case was sent to these 3 sites yet.

## MBSJ

The MBSJ form has no categories and no case type `appeal`. It has the case type `permohonan` (2941). It needs `--location`. Its submit button does not use reCAPTCHA. The page function `verifyReCaptcha()` calls `saverecNoRecaptcha()` directly.

1. The client reads the form from `add.do`. The page also holds the parameter names for the OTP request. These names change on each page load, so the client reads them each time.
2. With `--send`, the client uploads each `--attach` file to `/atchmgmt/FileAtch/upload.do` (maximum 10 MB for each file).
3. The client posts your email to `ajaxsendOTP.do`. The site sends a code to that email.
4. The CLI asks for the code. The client posts it to `ajaxverifyOTP.do`. If the reply is not `1`, the client stops before `save.do`.
5. The client posts the form to `save.do`.

```sh
complainerr --site mbsj submit --type aduan --subject "..." --detail "..." --location "..." \
  --attach photo.png --name "..." --doc-no 900101145555 --mobile 0123456789 --email you@example.com
```

## KKR

KKR is the public complaint site of the Ministry of Works. The MyJalan web site (`myjalan.kkr.gov.my`) is for staff only, and the public uses the MyJalan mobile app. Use this site for federal roads instead.

The KKR form has no categories. It needs `--location`. Its case types have other IDs than JPA and MBSJ (for example, `aduan` is 2005), and it has the case type `integriti`. The client finds each ID by the label on the form.

`--agency` sends the case to one office. If you do not give it, the case goes to the ministry. List the offices with `agencies`:

```sh
complainerr --site kkr agencies          # JKR (28245), LLM (28246), CIDB, ...
complainerr --site kkr agencies 50396    # the state JKR offices, e.g. 50407 JKR Selangor
complainerr --site kkr submit --type aduan --subject "..." --detail "..." --location "..." \
  --agency 50407 --recaptcha-token TOKEN --send
```

The KKR submit uses reCAPTCHA, like JPA. A dry run on 2026-11-25 against the real site gave the expected payload. No real case was sent to KKR yet.

Verified on MBSJ on 2026-11-24 with a real case: the upload, the OTP request and check, and `save.do`. The `save.do` page says "Your feedback is successfully submited. MBSJ.<number> is your feedback reference ID." The client returns that page as text and does not extract the ID yet.

SISPAA has no public API. This library sends the same HTTP form posts as the website. It keeps one cookie session (`JSESSIONID`) for all calls.

## Safety rule

A case that you submit goes to a government agency. You cannot take it back.

- `complainerr submit` does a dry run by default. It prints the form payload and sends nothing.
- `complainerr submit` posts the case only when you add `--send`.
- `SispaaClient.submit()` also sends nothing unless you give `send=True`.

## Personal details (profile)

Put your personal details in `~/.config/complainerr/profile.toml` (or the file that `$COMPLAINERR_PROFILE` names). Copy `profile.example.toml` to start. The values become the defaults of `submit`, so you do not type them each time. Do not put the real file in git. It holds your ID number.

## Install

```sh
uv venv && uv pip install -e '.[test]'
```

## Commands

```sh
complainerr categories                # top-level categories
complainerr categories 2012           # children of category 2012
complainerr categories 2012 --json
complainerr --site kkr agencies [PARENT]  # offices that a case can go to (KKR)

complainerr submit --type aduan --subject "Gaji lewat" --detail "..." --category 2013 \
  --name "ALI BIN ABU" --doc-no 900101145555 --mobile 0123456789 --email ali@example.com
# Add --recaptcha-token TOKEN --send to really submit.

complainerr submit ...                # with these set, submit logs in first

complainerr status CASE_ID --case-password PW --doc-no 900101145555
```

Case types: `aduan` (complaint), `appeal`, `cadangan` (suggestion), `penghargaan` (compliment), `pertanyaan` (enquiry), `permohonan` (MBSJ), `integriti` (KKR). Each site has its own IDs for them.

A category marked `[group]` is not selectable. Run `complainerr categories <id>` and pick one of its children.

## Library

```python
from complainerr import Case, CaseType, Requester, SispaaClient

client = SispaaClient()
cats = client.categories()            # list[Category(id, label, selectable)]
case = Case(CaseType.ADUAN, "Gaji lewat", "...", "2013",
            Requester("ALI BIN ABU", "NRIC", "900101145555", "CTZ", "0123456789", "ali@example.com"))
result = client.submit(case)          # dry run: result.payload, result.response is None
```

## How a submit works

1. The client sends `GET /eApps/sdmscasepool/SdmsCasePool/add.do`. The site sets `JSESSIONID` and returns the new-case form.
2. The client reads every form control from the page. This includes the Struts token `org.apache.struts.taglib.html.TOKEN`, which is new for each form, and the agency id `cpTargetHost`.
3. The client sets the case fields and the requester fields. It copies `cpTargetHost` into `cpTarget`, as the page JavaScript does.
4. If `--send` is not given, the client stops here and prints the payload.
5. If the form has `google_recaptcha=Y`, the client sends `GET /eApps/system/ajaxverifyrecaptcha.do` with your token. If the site does not reply `true`, the client stops.
6. The client posts the payload to `save.do` and returns the response page as plain text.

## Guest cases only

Complainerr files every case as a guest (`newLogin=N`). It does not log in to a SISPAA account. A guest case is linked to the name, ID number and email in the form, not to an account, so it does not show on an account dashboard. To see a guest case, use the reference ID and the ticket password that the site sends by email (`complainerr status`).

## The reCAPTCHA limit

The JPA new-case form uses Google reCAPTCHA v2 (site key `6LdhqcEUAAAAAHJ2qBB1S_PswJpXWZsLBdJKnvE4`). This library does not solve reCAPTCHA and does not go around it. To send a case, solve the captcha in a browser and give the token with `--recaptcha-token`. A token is valid for approximately two minutes and for one use only. If you do not give a token, `--send` stops with an error before it posts.

## Verified and unverified

Verified against the live site (read-only):

- `add.do` returns the form, a fresh Struts token, `cpTargetHost=28349` and `google_recaptcha=Y`.
- `loadChildListAjax.do` returns the child categories as JSON. A value such as `2032:N` is a group. The `level` value did not change the result for parent 2012, so the client always sends `level=2`.
- `ajaxverifyrecaptcha.do` replies `false` for a junk token.

Not verified, because a test would submit a real case:

- The response of `save.do`. The client returns the page as plain text and does not find the case number in it.
- That `save.do` accepts the payload. The browser also sends `cpCategory1`, `cpCategory2` and so on with the cascade values. The client sends only `cpCategory` with the final id, and `cpCategory1` stays empty.
- The response of `check.do`. `status` returns the page as plain text.
- The `agreeTnc` value. The page JavaScript sets it to `true`, so the client sends `true`.
- A deeper group id (below the top level) given without `:N` is not rejected by the client.

## Tests

```sh
.venv/bin/pytest -q
```

The tests run offline against pages saved from the site in `tests/fixtures/`.
