import json
from pathlib import Path
from dataclasses import asdict

import click

from .client import SITES, Case, CaseType, Requester, SispaaClient, SispaaError

login_id_opt = click.option("--login-id", envvar="SISPAA_LOGIN_ID", help="Or set SISPAA_LOGIN_ID.")
password_opt = click.option("--password", envvar="SISPAA_PASSWORD", help="Or set SISPAA_PASSWORD.")


@click.group()
@click.option("--site", default="jpa", type=click.Choice(list(SITES)), help="Which agency's SISPAA site.")
@click.pass_context
def main(ctx, site):
    """SISPAA public complaint sites (JPA, MBSJ) from the command line."""
    ctx.obj = site


@main.command()
@click.argument("parent", required=False)
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
def categories(site, parent, as_json):
    """List top-level categories, or the children of PARENT."""
    cats = SispaaClient(site).categories(parent)
    if as_json:
        click.echo(json.dumps([asdict(c) for c in cats], ensure_ascii=False, indent=2))
        return
    for c in cats:
        click.echo(f"{c.id}\t{'' if c.selectable else '[group] '}{c.label}")


@main.command()
@login_id_opt
@password_opt
@click.pass_obj
def login(site, login_id, password):
    """Test a registered-user login (UNVERIFIED response handling)."""
    if not (login_id and password):
        raise click.UsageError("set SISPAA_LOGIN_ID and SISPAA_PASSWORD")
    try:
        SispaaClient(site).login(login_id, password)
    except SispaaError as e:
        raise click.ClickException(str(e))
    click.echo("OK")


@main.command()
@click.option("--type", "case_type", required=True, type=click.Choice([t.name.lower() for t in CaseType]))
@click.option("--subject", required=True)
@click.option("--detail", required=True)
@click.option("--category", help="JPA: a selectable category id (see `complainerr categories`).")
@click.option("--location", help="MBSJ: where the problem is.")
@click.option("--attach", multiple=True, type=click.Path(exists=True, dir_okay=False), help="A file to attach (max 10 MB).")
@click.option("--name", help="Anonymous only.")
@click.option("--doc-type", default="NRIC", type=click.Choice(["NRIC", "PASS", "COMP", "OTH"]))
@click.option("--doc-no", help="Anonymous only.")
@click.option("--requester-type", default="CTZ", type=click.Choice(["GS", "GP", "STD", "CTZ"]))
@click.option("--mobile", help="Anonymous only.")
@click.option("--email", help="Anonymous only.")
@click.option("--recaptcha-token", help="A token from a reCAPTCHA you solved in a browser.")
@login_id_opt
@password_opt
@click.option("--send", is_flag=True, help="Really submit the case. Without it, only print the payload.")
@click.pass_obj
def submit(site, case_type, subject, detail, category, location, attach, name, doc_type, doc_no, requester_type,
           mobile, email, recaptcha_token, login_id, password, send):
    """Build a new case. Prints the form payload; posts it only with --send.

    If SISPAA_LOGIN_ID and SISPAA_PASSWORD are set, log in first as that user.
    """
    case = Case(
        CaseType[case_type.upper()], subject, detail, category,
        Requester(name, doc_type, doc_no, requester_type, mobile, email) if name else None,
        location,
    )
    client = SispaaClient(site)
    try:
        if login_id and password:
            client.login(login_id, password)
        result = client.submit(
            case, recaptcha_token, otp=lambda email: click.prompt(f"OTP sent to {email}"),
            attachments=[Path(a) for a in attach], send=send,
        )
    except SispaaError as e:
        raise click.ClickException(str(e))
    if result.response is None:
        click.echo("DRY RUN: nothing was sent. Add --send to submit this payload to save.do.", err=True)
        click.echo(json.dumps(result.payload, ensure_ascii=False, indent=2))
    else:
        click.echo(result.response)


@main.command()
@click.argument("case_id")
@click.option("--case-password", required=True)
@click.option("--doc-no", required=True)
@click.option("--doc-type", default="NRIC", type=click.Choice(["NRIC", "PASS", "COMP", "OTH"]))
@click.pass_obj
def status(site, case_id, case_password, doc_no, doc_type):
    """Check a case (UNVERIFIED response handling)."""
    click.echo(SispaaClient(site).status(case_id, case_password, doc_no, doc_type))
