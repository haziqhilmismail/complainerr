"""Talk to SISPAA agency sites by replaying the website's own form posts."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path

import requests

# Each agency runs its own copy of SISPAA. The paths are the same on every copy.
SITES = {
    "jpa": "https://jpa.spab.gov.my/eApps",
    "mbsj": "https://mbsj.spab.gov.my/eApps",
    "kkr": "https://kkr.spab.gov.my/eApps",
    "mbpj": "https://mbpj.spab.gov.my/eApps",
    "jpj": "https://jpj.spab.gov.my/eApps",
    "kpdn": "https://kpdn.spab.gov.my/eApps",
}
CASEPOOL = "/sdmscasepool/SdmsCasePool"
ADD = f"{CASEPOOL}/add.do"
SAVE = f"{CASEPOOL}/save.do"
CHILDREN = f"{CASEPOOL}/loadChildListAjax.do"
AGENCIES = f"{CASEPOOL}/loadTargetList.do"
ZONES = f"{CASEPOOL}/ajaxloadcplocation.do"
CHECK = f"{CASEPOOL}/check.do"
SEND_OTP = f"{CASEPOOL}/ajaxsendOTP.do"
VERIFY_OTP = f"{CASEPOOL}/ajaxverifyOTP.do"
VERIFY_RECAPTCHA = "/system/ajaxverifyrecaptcha.do"
UPLOAD_PAGE = "/atchmgmt/FileAtch/uploadNew.do?src=SDMSPOOL&fcntElementId=fileCnt&flstElementId=fileList"
UPLOAD = "/atchmgmt/FileAtch/upload.do"
# The OTP request uses parameter names that change on every page load, e.g.
# data:'6419724=' + rqEmail +'&4710612='+rqMobile+'&492842=6187537'. Empty names mean no OTP.
# A field that the page JS checks before submit: var field = "rqPhone"; var value = "Y";
REQUIRED = re.compile(r'var field = "(\w+)";\s*var value = "Y"')
# Fields that build_payload fills from the typed Case; `fields` may not override them.
OWN_FIELDS = {"cpTyp": "--type", "cpSubject": "--subject", "cpDetail": "--detail", "cpTarget": "--agency",
              "cpCategory": "--category", "cpLocation": "--location", "agreeTnc": "",
              "rqName": "--name", "rqDocTyp": "--doc-type", "rqDocNo": "--doc-no", "rqTyp": "--requester-type",
              "rqMobile": "--mobile", "rqPhone": "--mobile", "rqEmail": "--email"}
OTP_PARAMS = re.compile(r"data:'(\d+)=' \+ rqEmail \+'&(\d+)='\+rqMobile\+'&(\d+)=(\d+)'")


class SispaaError(Exception):
    pass


class CaseType(Enum):
    """The labels of the type on the form. Each site uses its own ids, e.g. aduan is 15 on JPA, 2005 on KKR."""

    ADUAN = ("Aduan", "Complaint")
    APPEAL = ("Appeal",)
    CADANGAN = ("Cadangan", "Suggestion")
    PENGHARGAAN = ("Penghargaan", "Appreciation")
    PERTANYAAN = ("Pertanyaan", "Inquiry")
    PERMOHONAN = ("Permohonan", "Application")
    INTEGRITI = ("Integriti", "Integrity")  # KKR


@dataclass(frozen=True)
class Category:
    """One choice in a lookup list: a category, an agency or a zone."""

    id: str
    label: str
    selectable: bool

    @classmethod
    def parse(cls, value: str, label: str) -> Category:
        # The site marks a group (pick a child instead) as "<id>:N".
        id_, _, flag = value.partition(":")
        return cls(id_, label, flag != "N")


@dataclass(frozen=True)
class Requester:
    name: str
    doc_type: str  # NRIC, PASS, COMP or OTH
    doc_no: str
    type: str  # GS, GP, STD or CTZ
    mobile: str
    email: str


@dataclass(frozen=True)
class Case:
    type: CaseType
    subject: str
    detail: str
    requester: Requester
    category_id: str | None = None  # when the form has categories (cpCategory1)
    location: str | None = None  # when the form has cpLocation: where the problem is
    agency: str | None = None  # when the form has cpTarget1: a sub-agency id; default is the site's own
    fields: dict[str, str] = field(default_factory=dict)  # other form fields a site asks for, e.g. JPJ rqPostcode


@dataclass(frozen=True)
class Submission:
    payload: dict[str, str]
    response: str | None  # None on a dry run


@dataclass
class Form:
    """The successful controls of the first <form>, as a browser would post them."""

    fields: dict[str, str] = field(default_factory=dict)
    options: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.form = Form()
        self._in_form = False
        self._done = False
        self._select: str | None = None
        self._option: str | None = None
        self._textarea: str | None = None
        self._text = ""

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            self._in_form = True
        if not self._in_form:
            return
        name = a.get("name")
        if tag == "input" and name:
            kind = a.get("type", "text").lower()
            if kind in ("checkbox", "radio"):
                if "checked" in a:
                    self.form.fields[name] = a.get("value", "on")
            elif kind not in ("submit", "button", "image", "reset", "file"):
                self.form.fields[name] = a.get("value", "")
        elif tag == "select" and name:
            self._select = name
            self.form.options[name] = []
        elif tag == "option" and self._select:
            self._option, self._text = a.get("value", ""), ""
            if "selected" in a or not self.form.options[self._select]:
                self.form.fields[self._select] = self._option
        elif tag == "textarea" and name:
            self._textarea, self._text = name, ""

    def handle_data(self, data):
        self._text += data

    def handle_endtag(self, tag):
        if tag == "form" and self._in_form:
            self._in_form, self._done = False, True
        elif tag == "option" and self._select and self._option is not None:
            self.form.options[self._select].append((self._option, self._text.strip()))
            self._option = None
        elif tag == "select":
            self._select = None
        elif tag == "textarea" and self._textarea:
            self.form.fields[self._textarea] = self._text
            self._textarea = None


def parse_form(page: str) -> Form:
    parser = _FormParser()
    parser.feed(page)
    return parser.form


def page_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


class SispaaClient:
    """A cookie session (JSESSIONID) against one agency's SISPAA site."""

    def __init__(self, site: str = "jpa", timeout: float = 30) -> None:
        if site not in SITES:
            raise SispaaError(f"unknown site {site!r}; known: {', '.join(SITES)}")
        self.base = SITES[site]
        self.session = requests.Session()
        self.timeout = timeout
        self._otp_params: tuple[str, str, str, str] | None = None  # from the last add.do page

    def url(self, path: str) -> str:
        return self.base + path

    def _get(self, path: str, **params) -> requests.Response:
        r = self.session.get(self.url(path), params=params, timeout=self.timeout)
        r.raise_for_status()
        return r

    def _post(self, path: str, data: dict[str, str], files=None) -> requests.Response:
        r = self.session.post(self.url(path), data=data, files=files, timeout=self.timeout)
        r.raise_for_status()
        return r

    def categories(self, parent_id: str | None = None) -> list[Category]:
        """Top-level categories from add.do, or the children of `parent_id`."""
        if parent_id is None:
            options = parse_form(self._get(ADD).text).options.get("cpCategory1", [])
            return [Category.parse(value, label) for value, label in options if value]
        return self._children(CHILDREN, parent_id)

    def agencies(self, parent_id: str | None = None) -> list[Category]:
        """Sub-agencies under `parent_id`, or under the site's own agency."""
        # The site answers with an HTML page instead of JSON until add.do has started the session.
        form = self._form_with("cpTarget1", "agency")
        return self._children(AGENCIES, parent_id or form.fields["cpTargetHost"])

    def zones(self, term: str) -> list[Category]:
        """MBPJ: the zones (field cpLocation2) whose name contains `term`, e.g. "ss" or "damansara"."""
        self._form_with("cpLocation2", "zone")  # also starts the session; the site redirects without one
        r = self._post(ZONES, {"cpLocation2Disp": term})
        # No match answers [{"label": "Sorry, record not found...", "value": ""}].
        return [Category(i["value"], i["label"], True) for i in json.loads(r.text or "[]") if i["value"]]

    def _form_with(self, name: str, what: str) -> Form:
        form = parse_form(self._get(ADD).text)
        if name not in form.fields and name not in form.options:
            raise SispaaError(f"this site has no {what} choice")
        return form

    def _children(self, path: str, parent_id: str) -> list[Category]:
        # shortcut: level is fixed at 2; the live sites returned the same list for 2 and 3.
        r = self._post(path, {"parentId": parent_id.split(":")[0], "dbComn": "N", "level": "2"})
        # A leaf answers with an empty body, not "[]".
        return [Category.parse(i["value"], i["label"]) for i in json.loads(r.text or "[]") if i["value"]]

    def build_payload(self, case: Case) -> dict[str, str]:
        """Fetch a fresh add.do form and fill it in for `case`. Sends nothing."""
        page = self._get(ADD).text
        form = parse_form(page)
        cp_typ = next((v for v, label in form.options["cpTyp"] if v and label in case.type.value), None)
        if cp_typ is None:
            raise SispaaError(f"this site has no case type {case.type.name.lower()}")
        m = OTP_PARAMS.search(page)
        self._otp_params = m.groups() if m else None
        fields = form.fields | {
            "cpTyp": cp_typ,
            "cpSubject": case.subject,
            "cpDetail": case.detail,
            "cpTarget": form.fields["cpTargetHost"],  # the page JS copies this before submit
            "agreeTnc": "true",  # setAgreeTnc() sets the checkbox value to "true"
        }
        if "cpCategory1" in form.options and case.category_id:
            # shortcut: only top-level groups are known here; a deeper group id passed without ":N" gets through.
            top_groups = {v.split(":")[0] for v, _ in form.options["cpCategory1"] if v.endswith(":N")}
            if ":" in case.category_id or case.category_id in top_groups:
                raise SispaaError(f"category {case.category_id} is a group; pick one of its children")
            fields["cpCategory"] = case.category_id
        if "cpLocation" in form.fields and case.location:
            fields["cpLocation"] = case.location
        if case.agency:
            if "cpTarget1" not in form.options:
                raise SispaaError("this site has no agency choice")
            # shortcut: a group id (shown as [group] by `agencies`) is not rejected here; check it if one gets misrouted.
            fields["cpTarget"] = case.agency
        r = case.requester
        requester = {
            "rqName": r.name,
            "rqDocTyp": r.doc_type,
            "rqDocNo": r.doc_no,
            "rqMobile": r.mobile,
            "rqPhone": r.mobile,  # KKR and JPJ ask for a "Telephone" too
            "rqEmail": r.email,
        }
        if r.type in {v for v, _ in form.options.get("rqTyp", [])}:  # each site offers its own types
            requester["rqTyp"] = r.type
        fields |= {k: v for k, v in requester.items() if k in form.fields}
        for name, value in case.fields.items():
            if name in OWN_FIELDS:
                raise SispaaError(f"{name} comes from {OWN_FIELDS[name] or 'the client'}, not from --field")
            if name not in form.fields:
                raise SispaaError(f"this site has no field {name}")
            choices = [v for v, _ in form.options.get(name, []) if v]
            if choices and value not in choices:
                labels = ", ".join(f"{v} ({label})" for v, label in form.options[name] if v)
                raise SispaaError(f"{name}={value} is not a choice; pick one of: {labels}")
            fields[name] = value
        missing = sorted({f for f in REQUIRED.findall(page) if f in form.fields and not fields[f]})
        if missing:
            how = ", ".join(OWN_FIELDS.get(f) or f"--field {f}=VALUE" for f in missing)
            raise SispaaError(f"this site also needs {', '.join(missing)}; give {how}")
        return fields

    def submit(
        self,
        case: Case,
        recaptcha_token: str | None = None,
        otp: Callable[[str], str] | None = None,
        attachments: Iterable[Path] = (),
        send: bool = False,
    ) -> Submission:
        """Build the payload; post it to save.do only when `send` is True.

        If the form asks for reCAPTCHA (google_recaptcha=Y), `recaptcha_token` must be a
        token from a real browser solve. This library never solves or skips it.
        If the form asks for an email OTP (MBSJ), the site emails a code and `otp(email)`
        must return it.
        The save.do reply comes back as page text; the reference ID is not extracted.
        """
        payload = self.build_payload(case)
        captcha = payload.get("google_recaptcha") == "Y"
        if captcha and recaptcha_token:
            payload["g-recaptcha-response"] = recaptcha_token
        if not send:
            return Submission(payload, None)
        if captcha:
            if not recaptcha_token:
                raise SispaaError("this form needs a reCAPTCHA token; solve it in a browser and pass it in")
            ok = self._get(VERIFY_RECAPTCHA, **{"g-recaptcha-response": recaptcha_token}).text
            if "true" not in ok:
                raise SispaaError("the site rejected the reCAPTCHA token")
        if self._otp_params and otp is None:
            raise SispaaError("this form needs an email OTP; pass an otp callback")
        for path in attachments:
            self.upload(path)
        if self._otp_params:
            payload |= self._verify_otp(payload["rqEmail"], otp)
        return Submission(payload, page_text(self._post(SAVE, payload).text))

    def upload(self, path: Path) -> None:
        """Attach a file (max 10 MB) to the case in this session."""
        form = parse_form(self._get(UPLOAD_PAGE).text)
        with open(path, "rb") as f:
            self._post(UPLOAD, form.fields | {"faKeyword": ""}, files={"faDocName": (path.name, f)})

    def _verify_otp(self, email: str, otp: Callable[[str], str]) -> dict[str, str]:
        email_key, mobile_key, extra_key, extra_value = self._otp_params
        sent = self._post(SEND_OTP, {email_key: email, mobile_key: "", extra_key: extra_value}).text.strip()
        if sent.strip('"') != "1":
            raise SispaaError(f"the site did not send the OTP (reply {sent!r})")
        code = otp(email).strip()
        ok = self._post(VERIFY_OTP, {"OTPUser": code}).text.strip()
        if ok.strip('"') != "1":
            raise SispaaError("the site rejected the OTP")
        # verifyOTP() and requestOTP() set these before the page submits the form.
        return {"OTPhidden": "1", "OTPUserHidden": code, "OTPReqMethod": "E"}

    def status(self, case_id: str, case_pwd: str, doc_no: str, doc_type: str = "NRIC") -> str:
        """Check a case. UNVERIFIED: returns the check.do result page as plain text."""
        form = parse_form(self._get(CHECK).text)
        data = form.fields | {
            "caseId": case_id,
            "cpId": case_id,
            "cpPwd": case_pwd,
            "rqDocTyp": doc_type,
            "rqDocNo": doc_no,
        }
        return page_text(self._post(f"{CHECK}?showOwnerData=Y", data).text)
