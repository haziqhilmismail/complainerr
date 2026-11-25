import json
import os
import tomllib
from dataclasses import asdict
from pathlib import Path

import click

from .client import SITES, Case, CaseType, Requester, SispaaClient, SispaaError

PROFILE = Path(os.environ.get("COMPLAINERR_PROFILE", Path.home() / ".config/complainerr/profile.toml"))


class Cli(click.Group):
    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except SispaaError as e:
            raise click.ClickException(str(e))


@click.group(cls=Cli)
@click.option("--site", default="jpa", type=click.Choice(list(SITES)), help="Which agency's SISPAA site.")
@click.pass_context
def main(ctx, site):
    """SISPAA public complaint sites (JPA, MBSJ, KKR, MBPJ, JPJ, KPDN) from the command line.

    Your personal details (name, doc-no, mobile, email, ...) can live in
    ~/.config/complainerr/profile.toml (or $COMPLAINERR_PROFILE); see profile.example.toml.
    """
    ctx.obj = site
    if PROFILE.is_file():
        profile = tomllib.loads(PROFILE.read_text())
        ctx.default_map = {"submit": profile, "status": profile}


@main.command()
@click.argument("parent", required=False)
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
def categories(site, parent, as_json):
    """List top-level categories, or the children of PARENT."""
    _echo_tree(SispaaClient(site).categories(parent), as_json)


@main.command()
@click.argument("parent", required=False)
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
def agencies(site, parent, as_json):
    """List the sub-agencies of the site's agency, or of PARENT (KKR: JKR, LLM, ...)."""
    _echo_tree(SispaaClient(site).agencies(parent), as_json)


@main.command()
@click.argument("term")
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
def zones(site, term, as_json):
    """MBPJ: find the zone id for --field cpLocation2=ID, e.g. `zones ss` or `zones damansara`."""
    _echo_tree(SispaaClient(site).zones(term), as_json)


def _echo_tree(items, as_json):
    if as_json:
        click.echo(json.dumps([asdict(c) for c in items], ensure_ascii=False, indent=2))
        return
    for c in items:
        click.echo(f"{c.id}\t{'' if c.selectable else '[group] '}{c.label}")


@main.command()
@click.option("--type", "case_type", required=True, type=click.Choice([t.name.lower() for t in CaseType]))
@click.option("--subject", required=True)
@click.option("--detail", required=True)
@click.option("--category", help="A selectable category id, if the site has categories (see `complainerr categories`).")
@click.option("--location", help="Where the problem is, if the site asks for it.")
@click.option("--agency", help="A sub-agency id, e.g. a state office (see `complainerr agencies`).")
@click.option("--field", "extra", multiple=True, metavar="NAME=VALUE",
              help="Another form field that the site asks for, e.g. JPJ --field rqPostcode=47100. Repeatable.")
@click.option("--attach", multiple=True, type=click.Path(exists=True, dir_okay=False), help="A file to attach (max 10 MB).")
@click.option("--name", required=True)
@click.option("--doc-type", default="NRIC", type=click.Choice(["NRIC", "PASS", "COMP", "OTH"]))
@click.option("--doc-no", required=True)
@click.option("--requester-type", default="CTZ", type=click.Choice(["GS", "GP", "STD", "CTZ", "IND"]))
@click.option("--mobile", required=True)
@click.option("--email", required=True)
@click.option("--recaptcha-token", help="A token from a reCAPTCHA you solved in a browser.")
@click.option("--send", is_flag=True, help="Really submit the case. Without it, only print the payload.")
@click.pass_obj
def submit(site, case_type, subject, detail, category, location, agency, extra, attach, name, doc_type, doc_no, requester_type,
           mobile, email, recaptcha_token, send):
    """Build a new case as a guest. Prints the form payload; posts it only with --send."""
    case = Case(
        CaseType[case_type.upper()], subject, detail,
        Requester(name, doc_type, doc_no, requester_type, mobile, email),
        category, location, agency, dict(_name_value(f) for f in extra),
    )
    result = SispaaClient(site).submit(
        case, recaptcha_token, otp=lambda email: click.prompt(f"OTP sent to {email}"),
        attachments=[Path(a) for a in attach], send=send,
    )
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


def _name_value(text):
    name, sep, value = text.partition("=")
    if not sep or not name:
        raise click.BadParameter(f"{text!r} is not NAME=VALUE", param_hint="--field")
    return name, value
