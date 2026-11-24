import json
from pathlib import Path

import pytest

from complainerr import Case, CaseType, Category, Requester, SispaaClient, SispaaError
from complainerr.client import ADD, CHECK, LOGIN_PAGE, SITES, UPLOAD_PAGE, parse_form

FIXTURES = Path(__file__).parent / "fixtures"
ADD_URL, CHECK_URL, LOGIN_PAGE_URL = (SITES["jpa"] + p for p in (ADD, CHECK, LOGIN_PAGE))
MBSJ_ADD_URL = SITES["mbsj"] + ADD
PAGES = {
    MBSJ_ADD_URL: (FIXTURES / "mbsj_add.html").read_text(encoding="latin-1"),
    SITES["mbsj"] + UPLOAD_PAGE: (FIXTURES / "mbsj_upload.html").read_text(encoding="latin-1"),
    ADD_URL: (FIXTURES / "add.html").read_text(encoding="latin-1"),
    LOGIN_PAGE_URL: (FIXTURES / "publicLogin.html").read_text(encoding="latin-1"),
    CHECK_URL: (FIXTURES / "check.html").read_text(encoding="latin-1"),
}
TOKEN = "5ea58c51441bba7643d9cad8a4748ac3"
REQUESTER = Requester("ALI BIN ABU", "NRIC", "900101145555", "CTZ", "0123456789", "ali@example.com")


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    """Serves saved pages for GETs and records POSTs; never touches the network."""

    def __init__(self, post_text="", get_text=None):
        self.posts, self.gets = [], []
        # post_text: one reply for every POST, or {url: reply}
        self.post_text, self.get_text = post_text, get_text or {}

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, params))
        return FakeResponse(self.get_text.get(url) or PAGES[url])

    def post(self, url, data=None, files=None, timeout=None):
        self.posts.append((url, data))
        self.files = {k: (name, f.read()) for k, (name, f) in (files or {}).items()} or getattr(self, "files", {})
        text = self.post_text
        return FakeResponse(text.get(url, "") if isinstance(text, dict) else text)


def client(site="jpa", **kw):
    c = SispaaClient(site)
    c.session = FakeSession(**kw)
    return c


def test_parse_form_scrapes_hidden_fields_and_action():
    form = parse_form(PAGES[ADD_URL])
    assert form.action == "/eApps/sdmscasepool/SdmsCasePool/save.do;jsessionid=CxpANBO7a-I7+6U9wIZPS0bp"
    f = form.fields
    assert f["org.apache.struts.taglib.html.TOKEN"] == TOKEN
    assert (f["strutsAction"], f["cpTargetHost"], f["newLogin"], f["google_recaptcha"]) == ("1", "28349", "N", "Y")
    assert (f["cpTyp"], f["cpDetail"], f["cpTarget"]) == ("", "", "")
    assert "agreeTnc" not in f  # unchecked checkbox is not a successful control


def test_top_level_categories_from_add_page():
    cats = client().categories()
    assert len(cats) == 14
    assert cats[0] == Category(
        "2012",
        "Dasar Perkhidmatan, Penempatan / Pertukaran Pegawai Gunasama, Kenaikan Pangkat, "
        "Peperiksaan Dalam Perkhidmatan dan Tatatertib",
        False,
    )
    assert cats[3] == Category("2013", "Gaji, Elaun, Kemudahan Cuti & Perubatan", True)


def test_child_categories_drop_placeholder_and_mark_groups():
    body = json.dumps([
        {"label": "- Pilih -", "value": "", "selected": ""},
        {"label": "Peperiksaan", "value": "2034", "selected": ""},
        {"label": "Hal-hal Perkhidmatan Pegawai Bukan Gunasama", "value": "2032:N", "selected": ""},
    ])
    c = client(post_text=body)
    assert c.categories("2012:N") == [
        Category("2034", "Peperiksaan", True),
        Category("2032", "Hal-hal Perkhidmatan Pegawai Bukan Gunasama", False),
    ]
    assert c.session.posts == [(
        "https://jpa.spab.gov.my/eApps/sdmscasepool/SdmsCasePool/loadChildListAjax.do",
        {"parentId": "2012", "dbComn": "N", "level": "2"},
    )]


def test_leaf_category_empty_body_has_no_children():
    assert client(post_text="").categories("2013") == []


@pytest.mark.parametrize("case_type,cp_typ", [
    (CaseType.ADUAN, "15"),
    (CaseType.APPEAL, "2044"),
    (CaseType.CADANGAN, "22"),
    (CaseType.PENGHARGAAN, "23"),
    (CaseType.PERTANYAAN, "21"),
])
def test_build_payload_per_case_type(case_type, cp_typ):
    c = client()
    p = c.build_payload(Case(case_type, "Gaji lewat", "Gaji bulan Oktober belum masuk.", "2013", REQUESTER))
    assert {k: p[k] for k in (
        "cpTyp", "cpSubject", "cpDetail", "cpCategory", "cpTarget", "cpTargetHost",
        "org.apache.struts.taglib.html.TOKEN", "strutsAction", "google_recaptcha",
        "rqName", "rqDocTyp", "rqDocNo", "rqTyp", "rqMobile", "rqEmail", "agreeTnc",
    )} == {
        "cpTyp": cp_typ, "cpSubject": "Gaji lewat", "cpDetail": "Gaji bulan Oktober belum masuk.",
        "cpCategory": "2013", "cpTarget": "28349", "cpTargetHost": "28349",
        "org.apache.struts.taglib.html.TOKEN": TOKEN, "strutsAction": "1", "google_recaptcha": "Y",
        "rqName": "ALI BIN ABU", "rqDocTyp": "NRIC", "rqDocNo": "900101145555", "rqTyp": "CTZ",
        "rqMobile": "0123456789", "rqEmail": "ali@example.com", "agreeTnc": "true",
    }
    assert c.session.posts == []


@pytest.mark.parametrize("category_id", ["2012:N", "2012", "2017"])
def test_build_payload_rejects_group_category(category_id):
    with pytest.raises(SispaaError, match=f"category {category_id} is a group"):
        client().build_payload(Case(CaseType.ADUAN, "s", "d", category_id, REQUESTER))


def test_submit_dry_run_sends_nothing():
    c = client()
    result = c.submit(Case(CaseType.ADUAN, "s", "d", "2013", REQUESTER), recaptcha_token="tok")
    assert result.response is None
    assert result.payload["g-recaptcha-response"] == "tok"
    assert c.session.posts == []
    assert c.session.gets == [(ADD_URL, {})]


def test_submit_send_without_token_refuses_before_posting():
    c = client()
    with pytest.raises(SispaaError, match="needs a reCAPTCHA token"):
        c.submit(Case(CaseType.ADUAN, "s", "d", "2013", REQUESTER), send=True)
    assert c.session.posts == []


def test_submit_send_stops_when_site_rejects_token():
    c = client(get_text={"https://jpa.spab.gov.my/eApps/system/ajaxverifyrecaptcha.do": "false"})
    with pytest.raises(SispaaError, match="rejected the reCAPTCHA token"):
        c.submit(Case(CaseType.ADUAN, "s", "d", "2013", REQUESTER), recaptcha_token="junk", send=True)
    assert c.session.posts == []


def test_submit_send_posts_payload_to_save():
    c = client(post_text="<html><body><p>No. Rujukan: JPA/123</p></body></html>",
               get_text={"https://jpa.spab.gov.my/eApps/system/ajaxverifyrecaptcha.do": "true"})
    result = c.submit(Case(CaseType.ADUAN, "s", "d", "2013", REQUESTER), recaptcha_token="good", send=True)
    assert result.response == "No. Rujukan: JPA/123"
    [(url, data)] = c.session.posts
    assert url == "https://jpa.spab.gov.my/eApps/sdmscasepool/SdmsCasePool/save.do"
    assert (data["g-recaptcha-response"], data["cpTarget"]) == ("good", "28349")


def test_login_posts_credentials_with_fresh_token():
    c = client(post_text="<html>Selamat datang</html>")
    c.login("ali", "secret")
    [(url, data)] = c.session.posts
    assert url == "https://jpa.spab.gov.my/eApps/sdmscasepool/SdmsCasePool/publicLoginCheck.do"
    assert (data["org.apache.struts.taglib.html.TOKEN"], data["rqLoginId"], data["rqLoginPwd"]) == (
        "c57634f4c140426d7fd6d2806ef6c11c", "ali", "secret")


def test_login_failure_when_form_comes_back():
    with pytest.raises(SispaaError, match="login failed"):
        client(post_text=PAGES[LOGIN_PAGE_URL]).login("ali", "wrong")


def test_status_posts_check_form():
    c = client(post_text="<html><b>Status:</b> Dalam Tindakan</html>")
    assert c.status("JPA123", "pw", "900101145555") == "Status: Dalam Tindakan"
    [(url, data)] = c.session.posts
    assert url == "https://jpa.spab.gov.my/eApps/sdmscasepool/SdmsCasePool/check.do?showOwnerData=Y"
    assert {k: data[k] for k in ("org.apache.struts.taglib.html.TOKEN", "strutsAction", "caseId", "cpId",
                                 "cpPwd", "rqDocTyp", "rqDocNo")} == {
        "org.apache.struts.taglib.html.TOKEN": "11e2130020c770e3cf41fa184964da95", "strutsAction": "0",
        "caseId": "JPA123", "cpId": "JPA123", "cpPwd": "pw", "rqDocTyp": "NRIC", "rqDocNo": "900101145555",
    }


def test_logged_in_form_omits_requester_fields():
    logged_in = PAGES[ADD_URL].replace('name="rqName"', 'name="xName"')
    p = client(get_text={ADD_URL: logged_in}).build_payload(Case(CaseType.CADANGAN, "s", "d", "2013"))
    assert (p["cpTyp"], p["cpCategory"], "rqName" in p) == ("22", "2013", False)


def test_anonymous_form_needs_requester():
    with pytest.raises(SispaaError, match="needs a requester"):
        client().build_payload(Case(CaseType.ADUAN, "s", "d", "2013"))


MBSJ = "https://mbsj.spab.gov.my/eApps/sdmscasepool/SdmsCasePool"
MBSJ_CASE = Case(CaseType.ADUAN, "Kereta di petak motosikal", "Butiran.", requester=REQUESTER,
                 location="No 1-19, Kompleks Utama, Jalan PU 7/2")


def test_mbsj_payload_has_location_and_no_category():
    p = client("mbsj").build_payload(MBSJ_CASE)
    assert {k: p[k] for k in ("cpTyp", "cpTarget", "cpTargetHost", "cpLocation", "rqEmail", "agreeTnc")} == {
        "cpTyp": "15", "cpTarget": "42148", "cpTargetHost": "42148",
        "cpLocation": "No 1-19, Kompleks Utama, Jalan PU 7/2", "rqEmail": "ali@example.com", "agreeTnc": "true",
    }
    assert "cpCategory1" not in p and "google_recaptcha" not in p


def test_mbsj_needs_location():
    with pytest.raises(SispaaError, match="needs a location"):
        client("mbsj").build_payload(Case(CaseType.ADUAN, "s", "d", requester=REQUESTER))


def test_type_not_on_site_is_rejected():
    with pytest.raises(SispaaError, match="no case type appeal"):
        client("mbsj").build_payload(Case(CaseType.APPEAL, "s", "d", requester=REQUESTER, location="x"))


def test_mbsj_send_without_otp_callback_refuses_before_posting():
    c = client("mbsj")
    with pytest.raises(SispaaError, match="needs an email OTP"):
        c.submit(MBSJ_CASE, send=True)
    assert c.session.posts == []


def test_mbsj_send_requests_and_verifies_otp_then_saves():
    c = client("mbsj", post_text={f"{MBSJ}/ajaxsendOTP.do": '"1"', f"{MBSJ}/ajaxverifyOTP.do": '"1"',
                                  f"{MBSJ}/save.do": "<p>Terima kasih</p>"})
    asked = []
    result = c.submit(MBSJ_CASE, otp=lambda email: asked.append(email) or " 123456 ", send=True)
    assert asked == ["ali@example.com"]
    assert result.response == "Terima kasih"
    (u1, d1), (u2, d2), (u3, d3) = c.session.posts
    assert (u1, d1) == (f"{MBSJ}/ajaxsendOTP.do", {"4012295": "ali@example.com", "3844929": "", "2731397": "2947068"})
    assert (u2, d2) == (f"{MBSJ}/ajaxverifyOTP.do", {"OTPUser": "123456"})
    assert u3 == f"{MBSJ}/save.do"
    assert (d3["OTPhidden"], d3["OTPUserHidden"], d3["OTPReqMethod"]) == ("1", "123456", "E")


def test_mbsj_wrong_otp_stops_before_save():
    c = client("mbsj", post_text={f"{MBSJ}/ajaxsendOTP.do": "1", f"{MBSJ}/ajaxverifyOTP.do": "0"})
    with pytest.raises(SispaaError, match="rejected the OTP"):
        c.submit(MBSJ_CASE, otp=lambda email: "000000", send=True)
    assert [u for u, _ in c.session.posts] == [f"{MBSJ}/ajaxsendOTP.do", f"{MBSJ}/ajaxverifyOTP.do"]


def test_attachment_uploads_before_otp_and_save(tmp_path):
    photo = tmp_path / "parking.png"
    photo.write_bytes(b"PNG")
    c = client("mbsj", post_text={f"{MBSJ}/ajaxsendOTP.do": "1", f"{MBSJ}/ajaxverifyOTP.do": "1"})
    c.submit(MBSJ_CASE, otp=lambda email: "123456", attachments=[photo], send=True)
    (url, data), *rest = c.session.posts
    assert url == "https://mbsj.spab.gov.my/eApps/atchmgmt/FileAtch/upload.do"
    assert (data["src"], data["org.apache.struts.taglib.html.TOKEN"]) == ("SDMSPOOL", "d29c5e79690abac41c43ae97f259ef46")
    assert c.session.files == {"faDocName": ("parking.png", b"PNG")}
    assert [u for u, _ in rest][-1] == f"{MBSJ}/save.do"
