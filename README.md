# Complainerr

Complainerr is a CLI (and a Python library) that files complaints on SISPAA, the Malaysian public complaint portal. Each agency runs its own copy of SISPAA. This library supports two copies:

| `--site` | Agency | URL | Before a submit |
|---|---|---|---|
| `jpa` (default) | Jabatan Perkhidmatan Awam | <https://jpa.spab.gov.my/eApps> | A category, and a reCAPTCHA token that you get in a browser |
| `mbsj` | Majlis Bandaraya Subang Jaya | <https://mbsj.spab.gov.my/eApps> | A location, and a one-time code (OTP) that the site sends to your email |

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

Verified on MBSJ on 2026-11-24 with a real case: the upload, the OTP request and check, and `save.do`. The `save.do` page says "Your feedback is successfully submited. MBSJ.<number> is your feedback reference ID." The client returns that page as text and does not extract the ID yet.

SISPAA has no public API. This library sends the same HTTP form posts as the website. It keeps one cookie session (`JSESSIONID`) for all calls.

## Safety rule

A case that you submit goes to a government agency. You cannot take it back.

- `complainerr submit` does a dry run by default. It prints the form payload and sends nothing.
- `complainerr submit` posts the case only when you add `--send`.
- `SispaaClient.submit()` also sends nothing unless you give `send=True`.

## Install

```sh
uv venv && uv pip install -e '.[test]'
```

## Commands

```sh
complainerr categories                # top-level categories
complainerr categories 2012           # children of category 2012
complainerr categories 2012 --json

complainerr submit --type aduan --subject "Gaji lewat" --detail "..." --category 2013 \
  --name "ALI BIN ABU" --doc-no 900101145555 --mobile 0123456789 --email ali@example.com
# Add --recaptcha-token TOKEN --send to really submit.

export SISPAA_LOGIN_ID=... SISPAA_PASSWORD=...
complainerr login                     # test the login only
complainerr submit ...                # with these set, submit logs in first

complainerr status CASE_ID --case-password PW --doc-no 900101145555
```

Case types: `aduan` (15, complaint), `appeal` (2044), `cadangan` (22, suggestion), `penghargaan` (23, compliment), `pertanyaan` (21, enquiry).

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

## How login works

1. The client sends `GET /eApps/sdmscasepool/SdmsCasePool/publicLogin.do` and reads the Struts token.
2. The client posts `rqLoginId`, `rqLoginPwd` and the token to `publicLoginCheck.do`. That page has no captcha.
3. If the login is correct, the site redirects to `viewList.do` (the case list). The client keeps the session cookie for the next calls.
4. The logged-in `add.do` form has no name, ID or contact fields. The account supplies them, so `Requester` is not necessary.
5. The logged-in form also has `google_recaptcha=Y`. A logged-in submit needs a reCAPTCHA token too.

## The reCAPTCHA limit

The new-case form uses Google reCAPTCHA v2, for anonymous and logged-in users (site key `6LdhqcEUAAAAAHJ2qBB1S_PswJpXWZsLBdJKnvE4`). This library does not solve reCAPTCHA and does not go around it. To send a case, solve the captcha in a browser and give the token with `--recaptcha-token`. A token is valid for approximately two minutes and for one use only. If you do not give a token, `--send` stops with an error before it posts.

## Verified and unverified

Verified against the live site (read-only):

- `add.do` returns the form, a fresh Struts token, `cpTargetHost=28349` and `google_recaptcha=Y`.
- `loadChildListAjax.do` returns the child categories as JSON. A value such as `2032:N` is a group. The `level` value did not change the result for parent 2012, so the client always sends `level=2`.
- `ajaxverifyrecaptcha.do` replies `false` for a junk token.
- Login: `publicLoginCheck.do` redirects to `viewList.do` when the login is correct.
- The logged-in `add.do` still has `google_recaptcha=Y` and calls `verifyReCaptcha()`. It has no `rqName` and other requester fields.

Not verified, because a test would submit a real case:

- The response of `save.do`. The client returns the page as plain text and does not find the case number in it.
- That `save.do` accepts the payload. The browser also sends `cpCategory1`, `cpCategory2` and so on with the cascade values. The client sends only `cpCategory` with the final id, and `cpCategory1` stays empty.
- The response to a wrong password. The client thinks that the login failed if the response shows the password field again.
- The response of `check.do`. `status` returns the page as plain text.
- The `agreeTnc` value. The page JavaScript sets it to `true`, so the client sends `true`.
- A deeper group id (below the top level) given without `:N` is not rejected by the client.

## Tests

```sh
.venv/bin/pytest -q
```

The tests run offline against pages saved from the site in `tests/fixtures/`.
