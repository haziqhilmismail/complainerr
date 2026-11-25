import json
from pathlib import Path

import pytest

from complainerr import Case, CaseType, Category, Requester, SispaaClient, SispaaError
from complainerr.client import ADD, CHECK, SITES, UPLOAD_PAGE, parse_form

FIXTURES = Path(__file__).parent / "fixtures"
ADD_URL, CHECK_URL = (SITES["jpa"] + p for p in (ADD, CHECK))
MBSJ_ADD_URL = SITES["mbsj"] + ADD
KKR_ADD_URL = SITES["kkr"] + ADD
PAGES = {
    SITES["jpj"] + ADD: (FIXTURES / "jpj_add.html").read_text(encoding="latin-1"),
    SITES["mbpj"] + ADD: (FIXTURES / "mbpj_add.html").read_text(encoding="latin-1"),
    KKR_ADD_URL: (FIXTURES / "kkr_add.html").read_text(encoding="latin-1"),
    MBSJ_ADD_URL: (FIXTURES / "mbsj_add.html").read_text(encoding="latin-1"),
    SITES["mbsj"] + UPLOAD_PAGE: (FIXTURES / "mbsj_upload.html").read_text(encoding="latin-1"),
    ADD_URL: (FIXTURES / "add.html").read_text(encoding="latin-1"),
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
        self.posts, self.gets, self.files = [], [], {}
        # post_text: one reply for every POST, or {url: reply}
        self.post_text, self.get_text = post_text, get_text or {}

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, params))
        return FakeResponse(self.get_text.get(url) or PAGES[url])

    def post(self, url, data=None, files=None, timeout=None):
        self.posts.append((url, data))
        if files:
            self.files = {k: (name, f.read()) for k, (name, f) in files.items()}
        text = self.post_text
        return FakeResponse(text.get(url, "") if isinstance(text, dict) else text)


def client(site="jpa", **kw):
    c = SispaaClient(site)
    c.session = FakeSession(**kw)
    return c


def test_parse_form_scrapes_hidden_fields():
    form = parse_form(PAGES[ADD_URL])
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
    p = c.build_payload(Case(case_type, "Gaji lewat", "Gaji bulan Oktober belum masuk.", REQUESTER, "2013"))
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
        client().build_payload(Case(CaseType.ADUAN, "s", "d", REQUESTER, category_id))


def test_submit_dry_run_sends_nothing():
    c = client()
    result = c.submit(Case(CaseType.ADUAN, "s", "d", REQUESTER, "2013"), recaptcha_token="tok")
    assert result.response is None
    assert result.payload["g-recaptcha-response"] == "tok"
    assert c.session.posts == []
    assert c.session.gets == [(ADD_URL, {})]


def test_submit_send_without_token_refuses_before_posting():
    c = client()
    with pytest.raises(SispaaError, match="needs a reCAPTCHA token"):
        c.submit(Case(CaseType.ADUAN, "s", "d", REQUESTER, "2013"), send=True)
    assert c.session.posts == []


def test_submit_send_stops_when_site_rejects_token():
    c = client(get_text={"https://jpa.spab.gov.my/eApps/system/ajaxverifyrecaptcha.do": "false"})
    with pytest.raises(SispaaError, match="rejected the reCAPTCHA token"):
        c.submit(Case(CaseType.ADUAN, "s", "d", REQUESTER, "2013"), recaptcha_token="junk", send=True)
    assert c.session.posts == []


def test_submit_send_posts_payload_to_save():
    c = client(post_text="<html><body><p>No. Rujukan: JPA/123</p></body></html>",
               get_text={"https://jpa.spab.gov.my/eApps/system/ajaxverifyrecaptcha.do": "true"})
    result = c.submit(Case(CaseType.ADUAN, "s", "d", REQUESTER, "2013"), recaptcha_token="good", send=True)
    assert result.response == "No. Rujukan: JPA/123"
    [(url, data)] = c.session.posts
    assert url == "https://jpa.spab.gov.my/eApps/sdmscasepool/SdmsCasePool/save.do"
    assert (data["g-recaptcha-response"], data["cpTarget"]) == ("good", "28349")






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
    with pytest.raises(SispaaError, match="also needs cpLocation; give --location$"):
        client("mbsj").build_payload(Case(CaseType.ADUAN, "s", "d", REQUESTER))


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


def test_cli_takes_requester_from_profile(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from complainerr import cli

    profile = tmp_path / "profile.toml"
    profile.write_text('name = "ALI BIN ABU"\ndoc_no = "900101145555"\nmobile = "0123456789"\nemail = "ali@example.com"\n')
    monkeypatch.setattr(cli, "PROFILE", profile)
    monkeypatch.setattr(cli, "SispaaClient", lambda site: client(site))
    result = CliRunner().invoke(cli.main, ["--site", "mbsj", "submit", "--type", "aduan", "--subject", "s",
                                           "--detail", "d", "--location", "x"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout[result.stdout.index("{"):])
    assert (payload["rqName"], payload["rqDocNo"], payload["rqEmail"]) == ("ALI BIN ABU", "900101145555", "ali@example.com")


KKR = SITES["kkr"] + "/sdmscasepool/SdmsCasePool"
KKR_CASE = Case(CaseType.ADUAN, "Lubang di jalan", "Butiran.", requester=REQUESTER,
                location="Jalan Puchong, KM 12", agency="50407")


@pytest.mark.parametrize("case_type,cp_typ", [
    (CaseType.ADUAN, "2005"),
    (CaseType.CADANGAN, "2016"),
    (CaseType.PENGHARGAAN, "2017"),
    (CaseType.PERTANYAAN, "2015"),
    (CaseType.INTEGRITI, "2007"),
])
def test_kkr_maps_case_types_to_its_own_ids(case_type, cp_typ):
    p = client("kkr").build_payload(Case(case_type, "s", "d", requester=REQUESTER, location="x"))
    assert p["cpTyp"] == cp_typ


def test_kkr_payload_has_agency_location_and_recaptcha():
    p = client("kkr").build_payload(KKR_CASE)
    assert {k: p[k] for k in ("cpTyp", "cpTarget", "cpTargetHost", "cpLocation", "google_recaptcha")} == {
        "cpTyp": "2005", "cpTarget": "50407", "cpTargetHost": "28309",
        "cpLocation": "Jalan Puchong, KM 12", "google_recaptcha": "Y",
    }


def test_kkr_without_agency_goes_to_the_ministry():
    p = client("kkr").build_payload(Case(CaseType.ADUAN, "s", "d", requester=REQUESTER, location="x"))
    assert p["cpTarget"] == "28309"


def test_agency_on_a_site_without_agencies_is_rejected():
    with pytest.raises(SispaaError, match="no agency choice"):
        client().build_payload(Case(CaseType.ADUAN, "s", "d", REQUESTER, "2013", agency="1"))


def test_kkr_agencies_lists_children_of_the_ministry():
    reply = json.dumps([{"label": "- Please Select -", "value": ""}, {"label": "works Department", "value": "28245"},
                        {"label": "Pusat Khidmat Kontraktor", "value": "41678:N"}])
    c = client("kkr", post_text=reply)
    assert c.agencies() == [Category("28245", "works Department", True),
                            Category("41678", "Pusat Khidmat Kontraktor", False)]
    assert c.session.posts == [(f"{KKR}/loadTargetList.do", {"parentId": "28309", "dbComn": "N", "level": "2"})]


def test_kkr_agencies_of_a_parent_starts_the_session_first():
    c = client("kkr", post_text="")
    assert c.agencies("50396") == []
    assert c.session.gets == [(KKR_ADD_URL, {})]
    assert c.session.posts == [(f"{KKR}/loadTargetList.do", {"parentId": "50396", "dbComn": "N", "level": "2"})]


def test_agencies_on_jpa_is_rejected():
    with pytest.raises(SispaaError, match="no agency choice"):
        client().agencies()


JPJ_DETAILS = {"rqAddr": "1 Jalan X, Puchong", "rqPostcode": "47100", "rqAge": "2630", "rqGender": "M"}


def jpj_case(**fields):
    return Case(CaseType.ADUAN, "s", "d", REQUESTER, agency="30010", fields=fields)


def test_jpj_names_every_required_field_that_is_empty():
    with pytest.raises(SispaaError, match="also needs rqAddr, rqAge, rqGender, rqPostcode; give --field rqAddr=VALUE, "
                                          "--field rqAge=VALUE, --field rqGender=VALUE, --field rqPostcode=VALUE$"):
        client("jpj").build_payload(jpj_case())


def test_jpj_payload_with_its_extra_fields():
    p = client("jpj").build_payload(jpj_case(**JPJ_DETAILS))
    assert {k: p[k] for k in ("cpTyp", "cpTarget", "rqPhone", "rqTyp", "rqCountry", *JPJ_DETAILS)} == {
        "cpTyp": "986", "cpTarget": "30010", "rqPhone": "0123456789",
        "rqTyp": "",  # JPJ has only IND, so the requester's CTZ is not sent
        "rqCountry": "8", **JPJ_DETAILS,
    }


def test_field_value_must_be_one_of_the_choices():
    with pytest.raises(SispaaError, match=r"rqAge=25 is not a choice; pick one of: 18 \(<18\), 1825 \(18-25\)"):
        client("jpj").build_payload(jpj_case(**JPJ_DETAILS | {"rqAge": "25"}))


def test_field_must_exist_on_the_site():
    with pytest.raises(SispaaError, match="this site has no field rqPostcode"):
        client().build_payload(Case(CaseType.ADUAN, "s", "d", REQUESTER, "2013", fields={"rqPostcode": "1"}))


MBPJ_CASE = Case(CaseType.ADUAN, "s", "d", REQUESTER, "2048", location="Jalan SS 2/24")


def test_mbpj_needs_a_zone():
    with pytest.raises(SispaaError, match="also needs cpLocation2;"):
        client("mbpj").build_payload(MBPJ_CASE)


def test_mbpj_payload_with_zone():
    case = Case(CaseType.ADUAN, "s", "d", REQUESTER, "2048", location="Jalan SS 2/24", fields={"cpLocation2": "2669"})
    p = client("mbpj").build_payload(case)
    assert {k: p[k] for k in ("cpTyp", "cpCategory", "cpLocation", "cpLocation2", "google_recaptcha")} == {
        "cpTyp": "15", "cpCategory": "2048", "cpLocation": "Jalan SS 2/24", "cpLocation2": "2669",
        "google_recaptcha": "Y",
    }


MBPJ_ZONES = SITES["mbpj"] + "/sdmscasepool/SdmsCasePool/ajaxloadcplocation.do"


def test_mbpj_zones_by_name():
    c = client("mbpj", post_text=json.dumps([{"label": "ZON 8 > SS 2", "value": "2669"}]))
    assert c.zones("ss 2") == [Category("2669", "ZON 8 > SS 2", True)]
    assert c.session.posts == [(MBPJ_ZONES, {"cpLocation2Disp": "ss 2"})]


def test_mbpj_zones_skip_the_not_found_row():
    c = client("mbpj", post_text=json.dumps([{"label": "Sorry, record not found...", "value": ""}]))
    assert c.zones("zzz") == []


def test_zones_on_a_site_without_zones_is_rejected():
    c = client("mbsj")
    with pytest.raises(SispaaError, match="no zone choice"):
        c.zones("ss")
    assert c.session.posts == []


def test_jpa_needs_a_category():
    with pytest.raises(SispaaError, match="also needs cpCategory; give --category$"):
        client().build_payload(Case(CaseType.ADUAN, "s", "d", REQUESTER))


@pytest.mark.parametrize("name,option", [("cpTarget", "--agency"), ("rqEmail", "--email"), ("agreeTnc", "the client")])
def test_field_cannot_override_what_the_client_sets(name, option):
    with pytest.raises(SispaaError, match=f"{name} comes from {option}, not from --field"):
        client("jpj").build_payload(jpj_case(**JPJ_DETAILS | {name: "x"}))


@pytest.mark.parametrize("bad", ["rqAddr", "=x"])
def test_cli_rejects_a_field_that_is_not_name_value(bad):
    from click.testing import CliRunner
    from complainerr.cli import main
    result = CliRunner().invoke(main, ["--site", "jpj", "submit", "--type", "aduan", "--subject", "s", "--detail", "d",
                                       "--name", "A", "--doc-no", "1", "--mobile", "1", "--email", "a@b.c",
                                       "--field", bad])
    assert result.exit_code == 2
    assert f"'{bad}' is not NAME=VALUE" in result.output
