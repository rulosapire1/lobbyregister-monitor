# Lobbyregister-Monitor BMWE

Automatische Übersicht neuer Stellungnahmen und Gutachten aus dem [Lobbyregister des Deutschen Bundestages](https://www.lobbyregister.bundestag.de), gefiltert nach Relevanz für das Bundesministerium für Wirtschaft und Energie (BMWE) und den Bundestag.

## Was macht dieses System?

**Täglich** läuft automatisch ein Skript, das:

1. Alle Registereinträge über die [Lobbyregister API V2](https://api.lobbyregister.bundestag.de/rest/v2/swagger-ui/) abruft
2. Stellungnahmen nach Empfänger (BMWE/BMWK/Bundestag), Themenfeldern und Datum filtert
3. Eine öffentlich zugängliche **Übersichtsseite** auf GitHub Pages aktualisiert

Zusätzlich **jeden Montag**:

4. Eine **wöchentliche Zusammenfassungs-Mail** an das Büropostfach versendet
5. Einen **Statusbericht** an die Admin-Adresse schickt (Selbsttest: API, E-Mail-Dienst, Seitenverfügbarkeit, API-Versionsänderungen)

## Links

| | |
|---|---|
| **Übersichtsseite** | https://bmwe-iiia4.github.io/lobbyregister-monitor |
| **Nutzungsanleitung** | https://bmwe-iiia4.github.io/lobbyregister-monitor/hilfe.html |
| **Wartungsdokumentation** | https://bmwe-iiia4.github.io/lobbyregister-monitor/wartung.html |
| **GitHub Actions (Logs)** | https://github.com/BMWE-IIIA4/lobbyregister-monitor/actions |

## Gefilterte Inhalte

**Empfänger:** BMWE (21. Wahlperiode), BMWK (20. Wahlperiode) und Bundestag

**Themenfelder:** Energie (allgemein, erneuerbar, fossil, Netze, Atom, Strom, Gas, Wasserstoff) · Klimaschutz · EU-Binnenmarkt · EU-Gesetzgebung · Wettbewerbsrecht · Politisches Leben/Parteien · Sonstige

**Zeitraum:** Stellungnahmen ab 1. Januar 2026

## Architektur

Das System nutzt die offizielle Lobbyregister API V2 in zwei Schritten:

1. **Alle Registereinträge laden** per `/registerentries` mit Cursor-Pagination
2. **Jeden Eintrag einzeln abrufen** per `/registerentries/{registerNumber}` und clientseitig filtern nach Themenfeldern (`activitiesAndInterests.fieldsOfInterest`), Empfängern (`statements[].recipientGroups`) und Datum

Beschreibungstexte kommen aus `regulatoryProjects[].description` (Vorhabenbeschreibung der Organisation).

## Dateien

```
.github/workflows/update.yml   – Automatischer Ablauf (GitHub Actions)
scripts/fetch_and_build.py     – Datenabruf (V2 API) und HTML-Generierung
scripts/send_email.py          – Wöchentlicher E-Mail-Versand (Resend)
scripts/health_check.py        – Wöchentlicher Selbsttest und Admin-Bericht
scripts/template.html          – HTML-Vorlage für die Übersichtsseite
docs/                          – Generierte Seiten (werden automatisch überschrieben)
```

## Wartung und Übergabe

Alle Informationen zur Wartung, zu Zugangsdaten, Fehlerbehebung und zur vollständigen Neueinrichtung durch eine dritte Person stehen in der [Wartungsdokumentation](https://bmwe-iiia4.github.io/lobbyregister-monitor/wartung.html).

**Ansprechpartner:** Martin Jahn, BMWE Unterabteilung IIIA4 · martin.jahn@bmwe.bund.de

## Datenquelle

Alle Daten stammen direkt aus dem Lobbyregister des Deutschen Bundestages und werden unverändert weitergegeben. Rechtsgrundlage der Veröffentlichungspflicht: [Lobbyregistergesetz (LobbyRG)](https://www.lobbyregister.bundestag.de/informationen-und-hilfe/rechtsvorschriften-parlamentarische-materialien-gl-2022--863566).
