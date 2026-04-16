"""
fetch_and_build.py
==================
Ruft Stellungnahmen direkt vom Lobbyregister ab.

Strategie: sucheDetailJson mit allen Filtern direkt –
inklusive filter[active][true]=true für aktive Regelungsvorhaben.
Das reduziert die Ergebnismenge drastisch auf relevante Einträge.
"""

import json
import os
import requests
from datetime import datetime, date
from collections import defaultdict
from pathlib import Path

# ── Konfiguration ──────────────────────────────────────────────────────────────

LIST_URL = "https://www.lobbyregister.bundestag.de/sucheDetailJson"
DETAIL_URL = "https://www.lobbyregister.bundestag.de/sucheJson"
SITE_URL = "https://bmwe-iiia4.github.io/lobbyregister-monitor"
START_DATE = date(2026, 1, 1)
PAGE_SIZE = 100

TARGET_RECIPIENTS = {"BMWE", "Bundestag", "BT"}

TARGET_FIELD_CODES = {
    "FOI_ENERGY", "FOI_ENERGY_RENEWABLE", "FOI_ENERGY_ELECTRICITY",
    "FOI_ENERGY_GAS", "FOI_ENERGY_HYDROGEN",
    "FOI_ENVIRONMENT_CLIMATE", "FOI_EU_DOMESTIC_MARKET", "FOI_EU_LAWS",
    "FOI_BUNDESTAG", "FOI_ECONOMY_COMPETITION_LAW",
    "FOI_POLITICAL_PARTIES", "FOI_OTHER",
}

FIELD_PRIORITY = {
    "FOI_ENERGY": 1, "FOI_ENERGY_RENEWABLE": 1, "FOI_ENERGY_ELECTRICITY": 1,
    "FOI_ENERGY_GAS": 1, "FOI_ENERGY_HYDROGEN": 1,
    "FOI_ENVIRONMENT_CLIMATE": 2, "FOI_EU_DOMESTIC_MARKET": 2,
    "FOI_EU_LAWS": 2, "FOI_BUNDESTAG": 2,
    "FOI_ECONOMY_COMPETITION_LAW": 3, "FOI_POLITICAL_PARTIES": 3, "FOI_OTHER": 3,
}

FIELD_LABELS = {
    "FOI_ENERGY": "Energie", "FOI_ENERGY_RENEWABLE": "Erneuerbare Energie",
    "FOI_ENERGY_ELECTRICITY": "Strom", "FOI_ENERGY_GAS": "Gas",
    "FOI_ENERGY_HYDROGEN": "Wasserstoff", "FOI_ENVIRONMENT_CLIMATE": "Klimaschutz",
    "FOI_EU_DOMESTIC_MARKET": "EU-Binnenmarkt", "FOI_EU_LAWS": "EU-Gesetzgebung",
    "FOI_BUNDESTAG": "Bundestag", "FOI_ECONOMY_COMPETITION_LAW": "Wettbewerbsrecht",
    "FOI_POLITICAL_PARTIES": "Politisches Leben, Parteien",
    "FOI_OTHER": "Sonstige Interessenbereiche",
}

# Filter-Parameter direkt von der Such-URL übernommen
FILTER_PARAMS = {
    "filter[circleofrecipients][21. Wahlperiode Bundesregierung|Bundesministerium für Wirtschaft und Energie (BMWE)]": "true",
    "filter[circleofrecipients][21. Wahlperiode Bundestag]": "true",
    "filter[fieldsofinterest][FOI_BUNDESTAG]": "true",
    "filter[fieldsofinterest][FOI_ECONOMY|FOI_ECONOMY_COMPETITION_LAW]": "true",
    "filter[fieldsofinterest][FOI_ENERGY]": "true",
    "filter[fieldsofinterest][FOI_ENVIRONMENT|FOI_ENVIRONMENT_CLIMATE]": "true",
    "filter[fieldsofinterest][FOI_EUROPEAN_UNION|FOI_EU_DOMESTIC_MARKET]": "true",
    "filter[fieldsofinterest][FOI_EUROPEAN_UNION|FOI_EU_LAWS]": "true",
    "filter[fieldsofinterest][FOI_OTHER]": "true",
    "filter[fieldsofinterest][FOI_POLITICAL_PARTIES]": "true",
    "filter[active][true]": "true",
    "sort": "FIRSTPUBLICATION_DESC",
}

SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json, text/plain, */*"})


# ── Schritt 1: Kandidaten mit Filtern holen ────────────────────────────────────

def fetch_candidates():
    """
    Holt gefilterte Registereinträge. Der active-Filter reduziert
    die Menge auf Einträge mit aktiven Regelungsvorhaben.
    """
    candidates = []
    page = 0
    total_fetched = 0

    print("Schritt 1: Gefilterte Kandidaten holen...")

    while True:
        params = {**FILTER_PARAMS, "pageSize": PAGE_SIZE, "page": page}

        try:
            resp = SESSION.get(LIST_URL, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  FEHLER Seite {page}: {e}")
            # Fallback: ohne Filter versuchen
            print("  Versuche ohne active-Filter...")
            fallback_params = {k: v for k, v in params.items()
                             if k != "filter[active][true]"}
            resp = SESSION.get(LIST_URL, params=fallback_params, timeout=60)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            break

        total_fetched += len(results)
        total_count = data.get("resultCount", data.get("totalResultCount", 0))

        if page == 0:
            print(f"  Gesamt laut API: {total_count} Einträge")

        for entry in results:
            if not isinstance(entry, dict):
                continue
            reg_num = entry.get("registerNumber", "")
            details = entry.get("registerEntryDetails", {})
            entry_id = details.get("registerEntryId", "") if isinstance(details, dict) else ""
            pub_date = ""
            acc = entry.get("accountDetails", {})
            if isinstance(acc, dict):
                pub_date = acc.get("firstPublicationDate", "")

            if reg_num and entry_id:
                candidates.append({
                    "registerNumber": reg_num,
                    "entryId": entry_id,
                    "firstPublicationDate": pub_date,
                })

        if page % 5 == 0 and page > 0:
            print(f"  Seite {page}: {total_fetched}/{total_count}, {len(candidates)} Kandidaten...")

        if total_fetched >= total_count or len(results) < PAGE_SIZE:
            break

        page += 1

    print(f"  {len(candidates)} Kandidaten gefunden.")
    return candidates


# ── Schritt 2: Einzelabrufe ────────────────────────────────────────────────────

def fetch_all_statements(candidates):
    all_statements = []
    total = len(candidates)
    print(f"Schritt 2: {total} Einträge einzeln abrufen...")

    for i, cand in enumerate(candidates):
        reg_num = cand["registerNumber"]
        entry_id = cand["entryId"]
        pub_date_str = cand.get("firstPublicationDate", "")

        upload_date = None
        if pub_date_str:
            try:
                upload_date = date.fromisoformat(pub_date_str[:10])
            except ValueError:
                pass

        try:
            resp = SESSION.get(
                f"{DETAIL_URL}/{reg_num}/{entry_id}",
                timeout=30
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            detail = resp.json()
        except Exception as e:
            if i < 3:
                print(f"  FEHLER {reg_num}: {e}")
            continue

        stmts_data = detail.get("statements", {})
        if not isinstance(stmts_data, dict) or not stmts_data.get("statementsPresent", False):
            continue

        org = extract_org_name(detail)

        for stmt in stmts_data.get("statements", []):
            result = process_statement(stmt, reg_num, org, upload_date)
            if result:
                all_statements.append(result)

        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{total} abgerufen, {len(all_statements)} Stellungnahmen...")

    print(f"  {len(all_statements)} relevante Stellungnahmen gefunden.")
    return all_statements


def extract_org_name(detail):
    identity = detail.get("lobbyistIdentity", {})
    if isinstance(identity, dict):
        name = identity.get("name", "")
        if name:
            return name
    return "Unbekannte Organisation"


def process_statement(stmt, register_number, org_name, upload_date):
    if not isinstance(stmt, dict):
        return None

    sending_date = None
    for rg in stmt.get("recipientGroups", []):
        sd = rg.get("sendingDate", "")
        if sd:
            try:
                sending_date = date.fromisoformat(str(sd)[:10])
                break
            except ValueError:
                pass

    check_date = upload_date or sending_date
    if check_date and check_date < START_DATE:
        return None

    recipients = []
    for rg in stmt.get("recipientGroups", []):
        recips = rg.get("recipients", {})
        if isinstance(recips, dict):
            for fg in recips.get("federalGovernment", []):
                dept = fg.get("department", {})
                short = dept.get("shortTitle", "")
                if short:
                    recipients.append(short)
            for p in recips.get("parliament", []):
                if p.get("de", ""):
                    recipients.append("Bundestag")
                    break

    recipients = list(dict.fromkeys(recipients))
    if not any(r in TARGET_RECIPIENTS for r in recipients):
        return None

    fields = []
    for f in stmt.get("fieldsOfInterest", []):
        if isinstance(f, dict):
            code = f.get("code", "")
            label = FIELD_LABELS.get(code) or f.get("de", "") or code
            if code:
                fields.append({"code": code, "label": label})

    field_codes = {f["code"] for f in fields}
    if not field_codes & TARGET_FIELD_CODES:
        return None

    priority = min((FIELD_PRIORITY.get(c, 99) for c in field_codes), default=99)
    text_obj = stmt.get("text", {})
    summary = text_obj.get("text", "") if isinstance(text_obj, dict) else ""

    return {
        "statement_number": str(stmt.get("statementNumber", "")),
        "register_number": str(register_number),
        "regulatory_project_title": str(stmt.get("regulatoryProjectTitle", "Kein Titel")),
        "org_name": str(org_name),
        "sending_date": sending_date.isoformat() if sending_date else None,
        "upload_date": upload_date.isoformat() if upload_date else None,
        "pdf_url": str(stmt.get("pdfUrl", "")),
        "pdf_pages": int(stmt.get("pdfPageCount", 0) or 0),
        "summary": str(summary)[:600],
        "recipients": recipients,
        "fields": fields,
        "priority": priority,
    }


# ── HTML-Generierung ───────────────────────────────────────────────────────────

def build_url(stmt):
    sn = stmt.get("statement_number", "")
    rn = stmt.get("register_number", "")
    base = "https://www.lobbyregister.bundestag.de/inhalte-der-interessenvertretung/stellungnahmengutachtensuche"
    if sn and rn:
        return f"{base}/{sn}/{rn}"
    return base


def format_date_de(iso_date):
    if not iso_date:
        return "–"
    try:
        d = date.fromisoformat(iso_date)
        return d.strftime("%d.%m.%Y")
    except ValueError:
        return iso_date


def get_weekday_de(iso_date):
    days = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
    months = ["","Januar","Februar","März","April","Mai","Juni",
              "Juli","August","September","Oktober","November","Dezember"]
    try:
        d = date.fromisoformat(iso_date)
        return f"{days[d.weekday()]}, {d.day}. {months[d.month]} {d.year}"
    except Exception:
        return iso_date


def render_entry_card(stmt):
    title = stmt["regulatory_project_title"].replace('"','&quot;').replace('<','&lt;').replace('>','&gt;')
    org = stmt["org_name"].replace('<','&lt;').replace('>','&gt;')
    sending = format_date_de(stmt.get("sending_date"))
    upload = format_date_de(stmt.get("upload_date"))
    summary = (stmt.get("summary","") or "Kein Beschreibungstext verfügbar.")
    summary = summary.replace('<','&lt;').replace('>','&gt;')
    recipients = stmt.get("recipients",[])
    fields = stmt.get("fields",[])
    pdf_url = stmt.get("pdf_url","")
    pdf_pages = stmt.get("pdf_pages",0)
    stmt_url = build_url(stmt)
    stmt_number = stmt.get("statement_number","")

    recip_badges = "".join(f'<span class="abadge">{r}</span>' for r in recipients)
    field_tags = "".join(f'<span class="tag">{f["label"]}</span>' for f in fields)
    pdf_link = (f'<a href="{pdf_url}" target="_blank">↗ PDF herunterladen ({pdf_pages} Seiten)</a>'
                if pdf_url else '<span style="color:#999">Kein PDF verfügbar</span>')

    return f"""
    <div class="entry-card" data-vorhaben="{title}">
      <div class="row-title">{title}</div>
      <div class="meta-row">
        <div class="mc grow"><strong>Bereitgestellt von</strong>{org}</div>
        <div class="mc fixd"><strong>Datum Stellungnahme</strong>{sending}</div>
        <div class="mc fixd"><strong>Hochgeladen am</strong>{upload}</div>
      </div>
      <div class="meta-row">
        <div class="mc grow"><strong>Adressaten</strong>{recip_badges}</div>
        <div class="mc grow"><strong>Themen</strong>{field_tags}</div>
      </div>
      <div class="row-full"><strong>Inhalt</strong>{summary}</div>
      <div class="link-row">
        <div class="lc"><a href="{stmt_url}" target="_blank">↗ Lobbyregistereintrag ({stmt_number})</a></div>
        <div class="lc">{pdf_link}</div>
      </div>
    </div>"""


def generate_html(statements, generated_at):
    by_date = defaultdict(list)
    for stmt in statements:
        key = stmt.get("upload_date") or stmt.get("sending_date") or "unbekannt"
        by_date[key].append(stmt)

    vorhaben_counts = defaultdict(int)
    for stmt in statements:
        vorhaben_counts[stmt["regulatory_project_title"]] += 1

    day_sections_html = ""
    for iso_date, day_stmts in sorted(by_date.items(), reverse=True):
        day_stmts_sorted = sorted(day_stmts, key=lambda x: x.get("priority",99))
        day_label = get_weekday_de(iso_date)
        cards = "".join(render_entry_card(s) for s in day_stmts_sorted)
        day_sections_html += f"""
        <div class="day-section" data-date="{iso_date}">
          <div class="day-header">{day_label}</div>
          {cards}
        </div>"""

    filter_items = "".join(
        f'<li data-v="{v.replace(chr(34),chr(39))}">'
        f'<span>{v}</span><span class="filter-count">{c}</span></li>'
        for v, c in sorted(vorhaben_counts.items(), key=lambda x: -x[1])
    )

    gen_dt = datetime.fromisoformat(generated_at)
    months_de = ["","Januar","Februar","März","April","Mai","Juni",
                 "Juli","August","September","Oktober","November","Dezember"]
    gen_str = f"{gen_dt.day}. {months_de[gen_dt.month]} {gen_dt.year}, {gen_dt.strftime('%H:%M')} Uhr"
    fields_subtitle = ("Energie &amp; Wasserstoff, Klimaschutz, EU-Binnenmarkt, EU-Gesetzgebung, "
                       "Bundestag, Wettbewerbsrecht, Politisches Leben/Parteien, Sonstige")

    with open("scripts/template.html","r",encoding="utf-8") as f:
        template = f.read()

    html = template.replace("{{DAY_SECTIONS}}", day_sections_html)
    html = html.replace("{{FILTER_ITEMS}}", filter_items)
    html = html.replace("{{GENERATED_AT}}", gen_str)
    html = html.replace("{{TOTAL_COUNT}}", str(len(statements)))
    html = html.replace("{{FIELDS_SUBTITLE}}", fields_subtitle)
    html = html.replace("{{SITE_URL}}", SITE_URL)
    return html


# ── Hauptprogramm ──────────────────────────────────────────────────────────────

def main():
    print("=== Lobbyregister Monitor – Seitengenerierung ===")

    candidates = fetch_candidates()
    statements = fetch_all_statements(candidates)

    print(f"Relevante Stellungnahmen gesamt: {len(statements)}")
    if not statements:
        print("WARNUNG: Keine Einträge. Seite wird trotzdem generiert.")

    Path("docs").mkdir(exist_ok=True)
    generated_at = datetime.now().isoformat()

    with open("docs/data.json","w",encoding="utf-8") as f:
        json.dump({
            "generated_at": generated_at,
            "statements": sorted(statements,
                key=lambda x: (x.get("upload_date") or "0000-00-00"), reverse=True)
        }, f, ensure_ascii=False, indent=2)

    html = generate_html(statements, generated_at)
    with open("docs/index.html","w",encoding="utf-8") as f:
        f.write(html)

    print(f"Seite generiert: docs/index.html ({len(statements)} Einträge)")
    print("=== Fertig ===")


if __name__ == "__main__":
    main()
