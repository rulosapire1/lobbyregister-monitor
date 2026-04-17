"""
gemini_enrich.py
================
Reichert die Lobbyregister-Daten mit Gemini Flash an:

1. Relevanzfilterung: Stellungnahmen in breiten Kategorien
   (Wettbewerbsrecht, EU-Gesetzgebung, Parteien, Sonstige) werden
   auf Energie/Klima-Relevanz geprüft — irrelevante werden aussortiert.

2. Zusammenfassung: Beschreibungstexte werden auf ~2 Sätze kondensiert.

Wird nach fetch_and_build.py ausgeführt. Liest docs/data.json,
schreibt das Ergebnis zurück nach docs/data.json.

Bei Gemini-Ausfall bleibt der Originalzustand erhalten — der Monitor
funktioniert auch ohne diesen Schritt. Ein Hinweis wird in data.json
gesetzt, damit Webseite und Mail den Ausfall anzeigen können.
"""

import json
import os
import time
import re
import sys
from pathlib import Path

# ── Konfiguration ──────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)

# Rate Limiting: Free Tier = 15 req/min → 4.5 Sekunden Abstand mit Puffer
REQUEST_DELAY = 4.5
MAX_RETRIES = 3
RETRY_DELAY = 12  # Sekunden bei Rate-Limit-Fehler

# Batch-Größe: bewusst klein gehalten (3), damit auch lange
# Beschreibungstexte aus der Lobbyregister-API Platz haben.
BATCH_SIZE = 3

# Prioritäten die gefiltert werden (2 = Klima/EU, 3 = Wettbewerb/Parteien/Sonstige)
FILTER_PRIORITIES = {2, 3}

# Priorität 1 (Energie/Wasserstoff) wird NIE gefiltert
ALWAYS_KEEP_PRIORITY = 1

DATA_PATH = Path("docs/data.json")

# Admin-Benachrichtigung bei Fehler
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")


# ── Relevanzkatalog ────────────────────────────────────────────────────────────
#
# Basiert auf dem Aufgabenportfolio der Unterabteilung IIIA (BMWE).
# Wird dem Gemini-Prompt als Referenz mitgegeben, damit die
# Relevanzentscheidung nachvollziehbar und konsistent ist.

RELEVANZ_KATALOG = """
THEMENFELDER DER UNTERABTEILUNG IIIA (BMWE) – Referenz für Relevanzprüfung:

EU-ENERGIEPOLITIK & ENERGIEGESETZGEBUNG:
- EU-Energieszenarien, EU-Zielarchitektur 2030/2040
- Erneuerbare-Energien-Richtlinie (RED), EU-Notfallverordnungen
- EU-Governance-Verordnung, Energieunion, NECP
- Clean Industrial Deal, EU Green Deal, RePowerEU
- EU-Beihilferecht Erneuerbare Energien, EU-Rahmenbedingungen EE-Fördersysteme
- EU-Rahmenbedingungen erneuerbarer Wasserstoff (RFNBO)
- Grenzüberschreitende EE-Kooperationsprojekte, Offshore-Kooperationen (Nordsee, Ostsee)
- Nordseekooperation, Pentalaterales Energieforum
- EU-Klimapolitik, EU-Klimagesetz, Fit for 55
- EU-Energiepreise, Wettbewerbsfähigkeit im EU-Binnenmarkt, EU-Energiesteuern
- EU-Wasserstoffmarkt, EU-Energieeffizienz, CCS/CCU
- Dekarbonisierung europäische Energieerzeugung

BILATERALE ENERGIEBEZIEHUNGEN:
- Deutsch-Französisches Büro für die Energiewende (DFBEW)
- Energiepolitische Beziehungen zu EU-Mitgliedstaaten, Norwegen, Schweiz, UK, Westbalkan

VERSORGUNGSSICHERHEIT STROM:
- Monitoring Versorgungssicherheit, Kapazitätsreserve, Netzreserve
- Sicherheitsbereitschaft, Systemanalysen

STROMMARKTDESIGN & -REGULIERUNG:
- Kapazitätsmechanismen, Börsenhandel/OTC-Märkte Strom
- Regelenergiemärkte, Bilanzkreise, Ausgleichsenergie
- Stromgebotszonen, Flexibilisierung (system-/netzdienlich)
- REMIT, Marktreformplan, EE-Fördersysteme
- Europäische Netzwerkcodes, Plattform Klimaneutrales Stromsystem
- Redispatch, Netzoptimierung

STROMERZEUGUNG & KRAFTWERKE:
- Kohleausstieg (Braun-/Steinkohle, KVBG)
- Kraftwerksstrategie, KWK (KWKG)
- Genehmigungsrecht Wasserstoffkraftwerke

ERNEUERBARE ENERGIEN (NATIONAL):
- EEG-Finanzierung, Besondere Ausgleichsregelung
- Steuern/Abgaben/Subventionen im Strombereich
- Power Purchase Agreements (PPA), Eigenverbrauch, Marktprämie

WASSERSTOFF:
- Wasserstoffkernnetz, Wasserstoffspeicher
- Wasserstoffbeschaffung, Elektrolyseure
- Farben Wasserstoff (grün, blau etc.), RFNBO, Sektorkopplung

KLIMASCHUTZ & ENERGIEWENDE:
- Klimaschutz- und Energieszenarien, Langfristszenarien
- Systementwicklungsstrategie (SES), Szenariorahmen NEP Strom/Gas/H2
- Projektionsbericht, Politikszenarien, NECP
- Sektorkopplung, gesamtwirtschaftliche Wirkungen
- Auswirkungen auf Industrie und Wirtschaft
- Finanzierungsbedarfe Transformation zur Klimaneutralität
- Reform klimarelevanter Steuern/Abgaben/Umlagen

ENERGIEPREISE & -KOSTEN:
- Großhandelspreise Strom, Marktwerte EE-Strom
- Weltmarktpreise fossile Energieträger
- Endverbraucherpreise (Haushalte und Industrie)
- Internationale Energiepreisvergleiche

ENERGIEMONITORING & -STATISTIK:
- Monitoring-Berichte Energiewende
- Statistik erneuerbare Energien (AGEE-Stat)
- Treibhausgasemissionen: Analysen und Berichterstattung

NICHT RELEVANT (kein Bezug zum Aufgabenportfolio):
- Rein parteipolitische Finanzierung / Parteiorganisation
- Medienrecht, Presserecht ohne Energiebezug
- Datenschutz / IT-Sicherheit ohne Energiebezug
- Arbeitsrecht / Sozialversicherungsrecht ohne Energiebezug
- Wettbewerbsrecht ohne Bezug zu Energiemärkten
- Verbraucherschutz ohne Energiebezug
- Kulturpolitik, Sportpolitik, Bildungspolitik
- Verteidigungspolitik / Rüstung ohne Energiebezug
- Gesundheitspolitik / Pharmarecht
- Verkehrspolitik ohne Bezug zu Sektorkopplung/Elektromobilität/Kraftstoffen
- Bauwesen / Wohnungspolitik ohne Bezug zu Gebäudeenergie/Wärmewende
- Landwirtschaftspolitik ohne Bezug zu Bioenergie/Flächenkonkurrenz
"""


# ── Gemini API ─────────────────────────────────────────────────────────────────

def call_gemini(prompt, retries=MAX_RETRIES):
    """Einzelner Gemini API-Call mit Retry-Logik."""
    import requests

    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }

    for attempt in range(retries):
        try:
            resp = requests.post(
                GEMINI_URL,
                headers=headers,
                params=params,
                json=payload,
                timeout=60,
            )

            if resp.status_code == 429:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"  Rate Limit erreicht, warte {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                print(f"  API-Fehler {resp.status_code}: {resp.text[:200]}")
                if attempt < retries - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                return None

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                print("  Keine Antwort von Gemini")
                return None

            text = (
                candidates[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            if not text:
                return None

            # JSON parsen (Gemini gibt manchmal Markdown-Fences mit)
            text = text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

            return json.loads(text)

        except json.JSONDecodeError as e:
            print(f"  JSON-Parse-Fehler: {e}")
            if attempt < retries - 1:
                time.sleep(REQUEST_DELAY)
                continue
            return None
        except Exception as e:
            print(f"  Fehler: {e}")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY)
                continue
            return None

    return None


# ── Admin-Benachrichtigung ─────────────────────────────────────────────────────

def notify_admin_error(error_summary, stats):
    """Sendet eine Fehler-Mail an den Admin wenn Gemini nicht funktioniert."""
    if not RESEND_API_KEY or not ADMIN_EMAIL:
        print("  Admin-Mail nicht möglich (RESEND_API_KEY oder ADMIN_EMAIL fehlt)")
        return

    import requests
    from datetime import date

    today = date.today().strftime("%d.%m.%Y")
    secrets_url = "https://github.com/BMWE-IIIA4/lobbyregister-monitor/settings/secrets/actions"
    actions_url = "https://github.com/BMWE-IIIA4/lobbyregister-monitor/actions"

    html = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;font-size:14px;color:#222;margin:0;padding:0;background:#f5f5f5">
<div style="max-width:600px;margin:20px auto">
  <div style="background:#004B87;padding:14px 24px">
    <div style="color:#fff;font-size:14px;font-weight:700">Lobbyregister-Monitor · Gemini-Fehler</div>
    <div style="color:#a8c8e8;font-size:11px">{today}</div>
  </div>
  <div style="background:#fff;padding:18px 24px">
    <div style="background:#e65100;color:#fff;padding:8px 14px;font-size:13px;font-weight:700;margin-bottom:14px">
      Gemini-Anreicherung fehlgeschlagen
    </div>
    <p style="font-size:12px;color:#333;margin-bottom:10px">
      <strong>Problem:</strong> {error_summary}
    </p>
    <p style="font-size:12px;color:#333;margin-bottom:10px">
      <strong>Auswirkung:</strong> Die heutige Aktualisierung zeigt alle Einträge ungefiltert an.
      Zusammenfassungen wurden nicht generiert. Ein Hinweis wird auf der Webseite und
      ggf. in der Wochenmail angezeigt.
    </p>
    <p style="font-size:12px;color:#333;margin-bottom:10px">
      <strong>Was zu tun ist:</strong><br>
      1. Prüfe ob der Gemini API-Key noch gültig ist:
         <a href="https://aistudio.google.com/apikey" style="color:#004B87">aistudio.google.com/apikey</a><br>
      2. Falls abgelaufen: neuen Key in GitHub Secrets eintragen:
         <a href="{secrets_url}" style="color:#004B87">Secrets</a><br>
      3. Manuellen Testlauf starten:
         <a href="{actions_url}" style="color:#004B87">Actions</a>
    </p>
    <p style="font-size:11px;color:#888;margin-top:14px">
      API-Fehler: {stats.get('api_errors', 0)} · Verarbeitet: {stats.get('processed_ok', 0)} ·
      Übersprungen: {stats.get('skipped_by_error', 0)}
    </p>
  </div>
</div></body></html>"""

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": "onboarding@resend.dev",
                "to": [ADMIN_EMAIL],
                "subject": f"⚠️ Lobbyregister-Monitor: Gemini-Anreicherung fehlgeschlagen ({today})",
                "html": html,
            },
            timeout=30,
        )
        resp.raise_for_status()
        print(f"  Admin-Fehlermail gesendet an {ADMIN_EMAIL}")
    except Exception as e:
        print(f"  Admin-Mail konnte nicht gesendet werden: {e}")


# ── Batch-Verarbeitung ─────────────────────────────────────────────────────────

def build_batch_prompt(batch):
    """
    Baut einen Prompt für einen Batch von Stellungnahmen.
    Kombiniert Relevanzfilterung und Zusammenfassung in einem Call.
    """
    entries_text = ""
    for i, stmt in enumerate(batch):
        title = stmt.get("regulatory_project_title", "Kein Titel")
        summary = stmt.get("summary", "")
        fields = ", ".join(f["label"] for f in stmt.get("fields", []))
        recipients = ", ".join(stmt.get("recipients", []))

        entries_text += f"""
--- Eintrag {i + 1} ---
Titel: {title}
Themenfelder: {fields}
Adressaten: {recipients}
Beschreibung: {summary}
"""

    prompt = f"""Du bist ein Analyst im Bundesministerium für Wirtschaft und Energie (BMWE),
Unterabteilung IIIA (Energiepolitik). Deine Aufgabe hat zwei Teile:

TEIL 1 – RELEVANZPRÜFUNG:
Prüfe für jeden Eintrag, ob er in das Aufgabenportfolio der Unterabteilung IIIA fällt.
Nutze den folgenden Referenzkatalog als Grundlage für deine Entscheidung:

{RELEVANZ_KATALOG}

Ein Eintrag ist relevant, wenn er mindestens eines der Themenfelder im Katalog
berührt — auch indirekt (z.B. ein Wettbewerbsrecht-Thema das sich auf
Energiemärkte bezieht, oder eine EU-Verordnung die den Strommarkt betrifft).

Ein Eintrag ist NICHT relevant, wenn er keinen erkennbaren Bezug zu einem
der Themenfelder hat. Im Zweifel — also wenn ein Bezug möglich aber unklar
ist — entscheide zugunsten der Relevanz (lieber einen Eintrag zu viel als
einen wichtigen zu wenig).

TEIL 2 – ZUSAMMENFASSUNG:
Fasse die Beschreibung jedes Eintrags in maximal 2 prägnanten Sätzen zusammen.
Sachlich, informativ, ohne Wertung. Fokus auf: Was wird gefordert/vorgeschlagen
und von wem? Falls die Beschreibung leer oder nichtssagend ist, schreibe
"Keine inhaltliche Beschreibung verfügbar."

Hier sind die Einträge:
{entries_text}

Antworte als JSON-Array mit genau {len(batch)} Objekten in dieser Reihenfolge:
[
  {{
    "index": 1,
    "relevant": true,
    "relevanz_grund": "Kurze Begründung (1 Satz)",
    "zusammenfassung": "Zusammenfassung in max. 2 Sätzen"
  }}
]

Antworte NUR mit dem JSON-Array, ohne zusätzlichen Text."""

    return prompt


def process_batch(batch, batch_num, total_batches):
    """Verarbeitet einen Batch und gibt die Ergebnisse zurück."""
    prompt = build_batch_prompt(batch)
    print(f"  Batch {batch_num}/{total_batches} ({len(batch)} Einträge)...")

    result = call_gemini(prompt)
    if result is None:
        print(
            f"  ⚠ Batch {batch_num} fehlgeschlagen – Originaldaten bleiben erhalten"
        )
        return None

    if not isinstance(result, list) or len(result) != len(batch):
        print(
            f"  ⚠ Batch {batch_num}: Unerwartetes Format "
            f"(erwartet {len(batch)} Einträge, "
            f"bekommen {len(result) if isinstance(result, list) else 'kein Array'})"
        )
        return None

    return result


# ── Hauptlogik ─────────────────────────────────────────────────────────────────

def enrich_statements(statements):
    """
    Reichert alle Stellungnahmen an:
    - Priority 1 (Energie): nur Zusammenfassung, immer behalten
    - Priority 2-3: Relevanzprüfung + Zusammenfassung
    """
    if not GEMINI_API_KEY:
        print("WARNUNG: GEMINI_API_KEY nicht gesetzt – Anreicherung übersprungen")
        return statements, {"skipped": True, "reason": "no_api_key"}, []

    # Stellungnahmen in zwei Gruppen teilen
    always_keep = []  # Priority 1 – nur Zusammenfassung
    needs_filter = []  # Priority 2-3 – Filterung + Zusammenfassung

    for stmt in statements:
        prio = stmt.get("priority", 99)
        if prio == ALWAYS_KEEP_PRIORITY:
            always_keep.append(stmt)
        elif prio in FILTER_PRIORITIES:
            needs_filter.append(stmt)
        else:
            always_keep.append(stmt)  # Unbekannte Priorität → behalten

    print(f"\nGemini-Anreicherung:")
    print(f"  {len(always_keep)} Einträge (Energie/Wasserstoff) → nur Zusammenfassung")
    print(
        f"  {len(needs_filter)} Einträge (andere Themen) → Relevanzprüfung + Zusammenfassung"
    )

    stats = {
        "total_input": len(statements),
        "always_keep": len(always_keep),
        "filter_candidates": len(needs_filter),
        "filtered_out": 0,
        "kept_after_filter": 0,
        "summaries_generated": 0,
        "api_errors": 0,
        "processed_ok": 0,
        "skipped_by_error": 0,
        "gemini_failed": False,
    }

    total_api_calls = 0
    failed_api_calls = 0

    # ── Gruppe 1: Energie-Einträge – nur Zusammenfassung ────────────────────

    if always_keep:
        print(f"\nSchritt 1: Zusammenfassungen für Energie-Einträge...")
        batches = [
            always_keep[i : i + BATCH_SIZE]
            for i in range(0, len(always_keep), BATCH_SIZE)
        ]
        total_b = len(batches)

        for bi, batch in enumerate(batches):
            total_api_calls += 1
            result = process_batch(batch, bi + 1, total_b)
            if result:
                stats["processed_ok"] += len(batch)
                for j, item in enumerate(result):
                    zusammenfassung = item.get("zusammenfassung", "")
                    if zusammenfassung and zusammenfassung != batch[j].get(
                        "summary", ""
                    ):
                        batch[j]["original_summary"] = batch[j].get("summary", "")
                        batch[j]["summary"] = zusammenfassung
                        stats["summaries_generated"] += 1
            else:
                failed_api_calls += 1
                stats["api_errors"] += 1
                stats["skipped_by_error"] += len(batch)

            if bi < total_b - 1:
                time.sleep(REQUEST_DELAY)

    # ── Gruppe 2: Andere Themen – Relevanzprüfung + Zusammenfassung ─────────

    kept = []
    filtered_out = []

    if needs_filter:
        print(f"\nSchritt 2: Relevanzprüfung für {len(needs_filter)} Einträge...")
        batches = [
            needs_filter[i : i + BATCH_SIZE]
            for i in range(0, len(needs_filter), BATCH_SIZE)
        ]
        total_b = len(batches)

        for bi, batch in enumerate(batches):
            total_api_calls += 1
            result = process_batch(batch, bi + 1, total_b)

            if result:
                stats["processed_ok"] += len(batch)
                for j, item in enumerate(result):
                    stmt = batch[j]
                    is_relevant = item.get("relevant", True)  # Im Zweifel behalten
                    zusammenfassung = item.get("zusammenfassung", "")
                    grund = item.get("relevanz_grund", "")

                    # Zusammenfassung anwenden
                    if zusammenfassung and zusammenfassung != stmt.get("summary", ""):
                        stmt["original_summary"] = stmt.get("summary", "")
                        stmt["summary"] = zusammenfassung
                        stats["summaries_generated"] += 1

                    if is_relevant:
                        stmt["gemini_relevanz"] = grund
                        kept.append(stmt)
                        stats["kept_after_filter"] += 1
                    else:
                        stmt["gemini_filtered"] = True
                        stmt["gemini_relevanz"] = grund
                        filtered_out.append(stmt)
                        stats["filtered_out"] += 1
            else:
                # Bei API-Fehler: alle behalten (fail-safe)
                failed_api_calls += 1
                stats["api_errors"] += 1
                stats["skipped_by_error"] += len(batch)
                for stmt in batch:
                    kept.append(stmt)
                    stats["kept_after_filter"] += 1

            if bi < total_b - 1:
                time.sleep(REQUEST_DELAY)

    # ── Fehler-Schwelle prüfen ──────────────────────────────────────────────
    # Wenn mehr als die Hälfte der API-Calls fehlschlagen, gilt die
    # Anreicherung insgesamt als gescheitert.

    if total_api_calls > 0 and failed_api_calls > total_api_calls / 2:
        stats["gemini_failed"] = True
        print(
            f"\n⚠ WARNUNG: {failed_api_calls}/{total_api_calls} API-Calls fehlgeschlagen "
            f"– Anreicherung als gescheitert markiert"
        )

    # Ergebnis zusammenführen
    enriched = always_keep + kept
    enriched.sort(
        key=lambda x: (x.get("upload_date") or "0000-00-00"), reverse=True
    )

    stats["total_output"] = len(enriched)

    print(f"\nErgebnis:")
    print(f"  {stats['total_input']} Eingabe → {stats['total_output']} Ausgabe")
    print(f"  {stats['filtered_out']} als nicht energie-/klimarelevant aussortiert")
    print(f"  {stats['summaries_generated']} Zusammenfassungen generiert")
    if stats["api_errors"] > 0:
        print(f"  ⚠ {stats['api_errors']} API-Fehler (Originaldaten beibehalten)")

    return enriched, stats, filtered_out


# ── Hauptprogramm ──────────────────────────────────────────────────────────────

def main():
    print("=== Lobbyregister Monitor – Gemini-Anreicherung ===")

    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY nicht gesetzt – Schritt wird übersprungen.")
        print("Der Monitor funktioniert auch ohne Gemini-Anreicherung.")
        # Hinweis in data.json setzen, damit Webseite/Mail informieren können
        if DATA_PATH.exists():
            with open(DATA_PATH, encoding="utf-8") as f:
                data = json.load(f)
            data["gemini_stats"] = {"skipped": True, "reason": "no_api_key"}
            with open(DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        sys.exit(0)

    if not DATA_PATH.exists():
        print(f"FEHLER: {DATA_PATH} nicht gefunden – fetch_and_build.py zuerst ausführen")
        sys.exit(1)

    # Daten laden
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    statements = data.get("statements", [])
    if not statements:
        print("Keine Stellungnahmen vorhanden – nichts zu tun.")
        sys.exit(0)

    print(f"{len(statements)} Stellungnahmen geladen.")

    # Anreichern
    enriched, stats, filtered_out = enrich_statements(statements)

    # Zurückschreiben
    data["statements"] = enriched
    data["gemini_stats"] = stats
    data["gemini_filtered_out"] = filtered_out  # Für Transparenz

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n{DATA_PATH} aktualisiert ({len(enriched)} Einträge).")

    # Bei signifikanten Fehlern: Admin benachrichtigen
    if stats.get("gemini_failed"):
        error_msg = (
            f"{stats['api_errors']} von {stats['api_errors'] + stats['processed_ok']//BATCH_SIZE} "
            f"API-Calls fehlgeschlagen. {stats['skipped_by_error']} Einträge nicht verarbeitet."
        )
        print(f"\nAdmin-Benachrichtigung wird gesendet...")
        notify_admin_error(error_msg, stats)

    print("=== Fertig ===")


if __name__ == "__main__":
    main()
