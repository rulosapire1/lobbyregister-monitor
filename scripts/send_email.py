"""
send_email.py
=============
Erzeugt eine wöchentliche HTML-Mail im Outlook-kompatiblen Tabellenlayout
und versendet sie über Resend.

Layout:
- Table-based (kein flexbox, kein gap)
- Inline-CSS (Outlook-kompatibel)
"""

import json
import os
import requests
from datetime import date, timedelta
from pathlib import Path
from collections import defaultdict

RESEND_API_KEY = os.environ["RESEND_API_KEY"]
EMAIL_RECIPIENT = os.environ["EMAIL_RECIPIENT"]

# ──────────────────────────────────────────────────────────────
# Daten laden
# ──────────────────────────────────────────────────────────────

def load_data():
    path = Path("docs/data.json")
    if not path.exists():
        raise FileNotFoundError("docs/data.json nicht gefunden")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_week_statements(statements):
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    return [
        s for s in statements
        if (s.get("upload_date") or s.get("sending_date") or "0000-00-00") >= cutoff
    ]


def format_date(iso_date):
    if not iso_date:
        return "–"
    try:
        return date.fromisoformat(iso_date).strftime("%d.%m.%Y")
    except:
        return iso_date


# ──────────────────────────────────────────────────────────────
# Rendering: einzelne Einträge
# ──────────────────────────────────────────────────────────────

def render_badges(items):
    html = ""
    for item in items:
        html += f"""
        <span style="
            display:inline-block;
            font-size:10px;
            padding:2px 6px;
            margin-right:6px;
            margin-bottom:4px;
            background:#dbeafe;
            color:#1e3a8a;
            border:1px solid #bfdbfe;
            border-radius:3px;
        ">{item}</span>
        """
    return html or "–"


def render_fields(fields):
    html = ""
    for f in fields:
        label = f.get("label", "")
        html += f"""
        <span style="
            display:inline-block;
            margin-right:6px;
            margin-bottom:4px;
        ">{label}</span>
        """
    return html or "–"


def render_entry(stmt):
    title = stmt["regulatory_project_title"]
    org = stmt["org_name"]
    sending = format_date(stmt.get("sending_date"))
    upload = format_date(stmt.get("upload_date"))
    recipients = stmt.get("recipients", [])
    fields = stmt.get("fields", [])
    summary = stmt.get("summary") or "Keine Beschreibung verfügbar."

    stmt_url = stmt.get("statement_url", "")
    pdf_url = stmt.get("pdf_url", "")
    pdf_pages = stmt.get("pdf_pages", 0)

    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #d0d8e4;margin-bottom:14px;font-family:Arial,Helvetica,sans-serif;">
    
    <!-- Zeile 1: Titel -->
    <tr>
        <td colspan="2" style="background:#eef3f9;padding:10px 12px;font-weight:bold;color:#003366;">
            {title}
        </td>
    </tr>

    <!-- Zeile 2 -->
    <tr>
        <td width="65%" style="padding:8px 12px;vertical-align:top;">
            <div style="font-size:10px;color:#888;font-weight:bold;">Bereitgestellt von</div>
            <div>{org}</div>
        </td>
        <td width="35%" style="padding:8px 12px;vertical-align:top;">
            <div style="font-size:10px;color:#888;font-weight:bold;">Stellungnahme</div>
            <div>{sending}</div>
            <div style="font-size:10px;color:#888;font-weight:bold;margin-top:4px;">Hochgeladen</div>
            <div>{upload}</div>
        </td>
    </tr>

    <!-- Zeile 3 -->
    <tr>
        <td style="padding:8px 12px;vertical-align:top;">
            <div style="font-size:10px;color:#888;font-weight:bold;">Adressaten</div>
            {render_badges(recipients)}
        </td>
        <td style="padding:8px 12px;vertical-align:top;">
            <div style="font-size:10px;color:#888;font-weight:bold;">Themenfelder</div>
            {render_fields(fields)}
        </td>
    </tr>

    <!-- Zeile 4 -->
    <tr>
        <td colspan="2" style="padding:8px 12px;">
            <div style="font-size:10px;color:#888;font-weight:bold;">Inhalt</div>
            <div style="line-height:1.5;">{summary}</div>
        </td>
    </tr>

    <!-- Zeile 5 -->
    <tr>
        <td style="padding:8px 12px;">
            {"<a href='" + stmt_url + "' style='color:#004B87;text-decoration:none;'>↗ Stellungnahme im Register</a>" if stmt_url else ""}
        </td>
        <td style="padding:8px 12px;">
            {"<a href='" + pdf_url + "' style='color:#004B87;text-decoration:none;'>↗ PDF (" + str(pdf_pages) + " S.)</a>" if pdf_url else ""}
        </td>
    </tr>

</table>
"""


# ──────────────────────────────────────────────────────────────
# Gesamt-Mail
# ──────────────────────────────────────────────────────────────

def build_email(statements):
    week_stmts = get_week_statements(statements)

    if not week_stmts:
        return "<p>Keine neuen Einträge diese Woche.</p>"

    entries_html = "".join(render_entry(s) for s in week_stmts)

    return f"""
<html>
<body style="background:#f5f5f5;margin:0;padding:20px;font-family:Arial,Helvetica,sans-serif;">
    <div style="max-width:700px;margin:auto;background:#ffffff;padding:16px;">
        
        <h2 style="color:#003366;margin-top:0;">
            Lobbyregister-Monitor – Wochenübersicht
        </h2>

        <p style="font-size:12px;color:#555;">
            Neue Stellungnahmen der letzten 7 Tage
        </p>

        {entries_html}

    </div>
</body>
</html>
"""


# ──────────────────────────────────────────────────────────────
# Versand
# ──────────────────────────────────────────────────────────────

def send_email(html):
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": "Lobbyregister Monitor <onboarding@resend.dev>",
            "to": EMAIL_RECIPIENT,
            "subject": "Lobbyregister-Monitor – Wochenupdate",
            "html": html,
        },
    )

    if response.status_code >= 300:
        raise RuntimeError(f"E-Mail Versand fehlgeschlagen: {response.text}")


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    data = load_data()
    html = build_email(data["statements"])
    send_email(html)
    print("E-Mail erfolgreich versendet.")


if __name__ == "__main__":
    main()
