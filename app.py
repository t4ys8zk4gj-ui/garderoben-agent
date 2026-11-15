import re
import requests
import streamlit as st
from groq import Groq

# --- 1. SYSTEM-PROMPT & REGELN (NRM 28) ---
TRANSPARENZ_TEXT = (
    "ℹ️ **Transparenzhinweis:** Ich bin ein KI-System zur Unterstützung deiner morgendlichen "
    "Outfit-Wahl. Meine Vorschläge basieren auf Live-Wetterdaten und festen Bekleidungsregeln – "
    "die endgültige Entscheidung triffst immer du selbst."
)

SYSTEM_PROMPT = f"""
Du bist der „Garderoben-Agent: Was ziehe ich an?“. Du unterstützt Studierende und Berufstätige dabei, in unter zwei Minuten eine passende Outfit-Auswahl auf Basis des Wetters am Zielort (inklusive Uhrzeit) und des Tagesanlasses zu treffen.

WICHTIG ZU STICHWORT-EINGABEN:
Nutzende geben ihre Anfrage oft kurz in Stichworten ein. Akzeptiere diese Stichworte vollständig als gültige Eingabe!

SPRACHREGELN:
- Antworte in natürlichem, fehlerfreiem Hochdeutsch.
- Duze die Person durchgehend und freundlich.
- Wiederhole dich nicht.

TRANSPARENZHINWEIS:
Beginne deine allererste Antwort im Chat IMMER zwingend mit folgendem Wortlaut:
„{TRANSPARENZ_TEXT}“

UNTERSCHEIDUNG DAMEN- UND HERRENBEKLEIDUNG (MARKENFREI):
- **Herrenbekleidung:**
  - Freizeit: T-Shirt, Poloshirt, Hoodie, Sweatshirt, Jeans, Cargohose, Shorts, Sneaker, derbe Boots, Windbreaker, Regenjacke, Winterparka.
  - Uni: T-Shirt, Langarmshirt, Strickpullover, Cardigan, Freizeithemd, Jeans, Chino, Sneaker, Chelsea-Boots, Übergangsjacke.
  - Arbeit: Klassisches Hemd, Feinstrickpullover, Sakko, Anzughose, gepflegte Chino, Lederschnürschuhe, Loafer, Trenchcoat, Wollmantel.
- **Damenbekleidung:**
  - Freizeit: T-Shirt, Top, Hoodie, Strickpullover, Jeans, Freizeithose, Leggings, Sommerrock, Sneaker, Schnürboots, Regenjacke, Steppjacke.
  - Uni: Blusenshirt, Rollkragenpullover, Cardigan, Jeans, Stoffhose, Midi-Rock (bei Kälte mit Strumpfhose), Sneaker, Stiefeletten, Trenchcoat/Übergangsjacke.
  - Arbeit: Bluse, Feinstrickoberteil, Blazer, Stoffhose/Bundfaltenhose, Bleistiftrock/Kostümrock (ggf. mit Strumpfhose), Loafer, Stiefeletten, Pumps, Trenchcoat, eleganter Wollmantel.
- **Regel zur Ausgabe:** Wenn Damen oder Herren genannt wurde, schlage NUR diese Kategorie vor. Wurde nichts genannt, führe in jeder Variante beides getrennt auf („👚 Damen: ... | 👔 Herren: ...“).

WORKFLOW & REGELN:
1. Prüfe, ob die 2 Pflichtparameter vorliegen: **Zielort** und **Anlass** (Uni, Arbeit oder Freizeit).
   - Fehlt der Ort? Melde zwingend: „Fehler: Fehlende Ortsangabe. Bitte gib deinen Zielort an.“ Erfinde NIEMALS einen Ort!
   - Fehlt der Anlass? Frage kurz nach dem Anlass (Uni, Arbeit oder Freizeit).
   - WICHTIG: Frage den Nutzer NIEMALS nach Wetterwerten! Das Wetter kommt automatisch aus dem System.
2. Leite den Style ab:
   - Freizeit -> locker & funktional
   - Uni -> locker bis alltagstauglich (Smart-Everyday)
   - Arbeit -> gepflegt bis formell (Business Casual / Formell)
3. Nutze für das Wetter und die Uhrzeit AUSSCHLIESSLICH die übergebenen Open-Meteo-Werte. Erfinde niemals eigene Werte oder Orte.
4. Schlage IMMER genau 3 vollständige, unterschiedliche Outfit-Varianten vor (Variante 1, Variante 2 und Variante 3 – keine Marken). Gib niemals nur eine einzelne Variante aus!
5. Genau 1 Begründungssatz pro Variante: Verknüpfe Zeitpunkt/Wetterwerte (Temperatur, Wind, Regen), Anlass und Style logisch in diesem Satz.
6. Schließe deine Nachricht IMMER exakt mit der Frage: „Passt das zusammen?“
7. Maximal 3 Durchläufe. Übergib danach oder bei Zustimmung die Entscheidung an die Person.

NICHT-ZIELE (STRIKT ABLEHNEN):
1. Keine Marken- oder Kaufberatung (keine Marken, Shops, Preise).
2. Keine Fotos oder Körpermaße/Konfektionsgrößen auswerten.
3. Keine dauerhafte Speicherung über die Sitzung hinaus.
4. Keine Stilberatung außerhalb von Uni, Arbeit und Freizeit (keine Hochzeiten, Galas, Kostüme).

STRUKTUR DER OUTFIT-ANTWORT (WENN ORT UND ANLASS VORLIEGEN):
Kurzüberblick: [Ort] ([Zeitpunkt]) | [Temperatur] °C, [Wind] km/h Wind, [Regen]% Regenrisiko | Anlass: [Anlass] (Style: [Style])

• **Variante 1 (Alltagstauglich / Klassisch):** [Konkrete Teile: Oberteil, Schicht, Beinkleid, Schuhe, Jacke]
*Begründung:* [Genau ein logischer Satz zu Wetter zur genannten Uhrzeit, Anlass und Style.]

• **Variante 2 (Zwiebelprinzip / Wärmer):** [Konkrete Teile]
*Begründung:* [Genau ein logischer Satz zu Wetter, Anlass und Style.]

• **Variante 3 (Funktional / Alternativ):** [Konkrete Teile]
*Begründung:* [Genau ein logischer Satz zu Wetter, Anlass und Style.]

Passt das zusammen?
"""

# --- 2. ZEIT- & ORTSERKENNUNG SOWIE OPEN-METEO API ---
def parse_time_from_text(text: str) -> tuple:
    """Erkennt Zeitangaben auch in kurzen Stichworten (z. B. '8 Uhr', '18:00', 'morgen früh', 'abend')."""
    t = text.lower()
    day_offset = 1 if ("morgen" in t and "heute morgen" not in t and "guten morgen" not in t) else 0
    hour = None

    match = re.search(r'\b([01]?\d|2[0-3])(?::(\d{2}))?\s*uhr\b', t)
    if not match:
        match = re.search(r'\bum\s+([01]?\d|2[0-3])(?::(\d{2}))?\b', t)
    if not match:
        match = re.search(r'\b([01]?\d|2[0-3]):(\d{2})\b', t)
    
    if match:
        hour = int(match.group(1))
    else:
        if any(w in t for w in ["früh", "heute morgen", "morgens", "vormittag", "vormittags"]):
            hour = 8
        elif any(w in t for w in ["mittag", "mittags"]):
            hour = 12
        elif any(w in t for w in ["nachmittag", "nachmittags"]):
            hour = 15
        elif any(w in t for w in ["abend", "abends"]):
            hour = 19
        elif any(w in t for w in ["nacht", "nachts"]):
            hour = 22
        elif day_offset == 1:
            hour = 9

    return day_offset, hour

def get_weather_data(city: str, day_offset: int = 0, hour: int = None) -> dict:
    """Ruft aktuelle Wetterdaten oder stundengenaue Vorhersagen von Open-Meteo ab."""
    try:
        clean_city = city.strip(".,!?:;\"'()[]{}-/")
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={clean_city}&count=1&language=de&format=json"
        geo_res = requests.get(geo_url, timeout=5).json()
        
        if not geo_res.get("results"):
            return {"error": f"Ort '{clean_city}' nicht gefunden."}
            
        lat = geo_res["results"][0]["latitude"]
        lon = geo_res["results"][0]["longitude"]
        resolved_name = geo_res["results"][0]["name"]
        
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,wind_speed_10m"
            f"&hourly=temperature_2m,precipitation_probability,wind_speed_10m"
            f"&daily=precipitation_probability_max"
            f"&timezone=auto&forecast_days=2"
        )
        w_res = requests.get(weather_url, timeout=5).json()
        
        if hour is not None:
            idx = day_offset * 24 + hour
            hourly_temps = w_res["hourly"]["temperature_2m"]
            if idx >= len(hourly_temps):
                idx = len(hourly_temps) - 1
                
            day_str = "Morgen" if day_offset == 1 else "Heute"
            time_label = f"{day_str}, {hour:02d}:00 Uhr"
            
            return {
                "ort": resolved_name,
                "zeitpunkt": time_label,
                "temperatur": w_res["hourly"]["temperature_2m"][idx],
                "wind": w_res["hourly"]["wind_speed_10m"][idx],
                "regen": w_res["hourly"]["precipitation_probability"][idx]
            }
        
        return {
            "ort": resolved_name,
            "zeitpunkt": "Aktuell (Jetzt)",
            "temperatur": w_res["current"]["temperature_2m"],
            "wind": w_res["current"]["wind_speed_10m"],
            "regen": w_res["daily"]["precipitation_probability_max"][0]
        }
    except Exception as e:
        return {"error": f"Fehler beim API-Abruf: {str(e)}"}

def detect_city_name(text: str, client: Groq, model: str) -> str:
    """
    Erkennt ausschließlich tatsächlich im Text genannte Städte.
    Verhindert Halluzinationen durch strikten Abgleich mit dem Eingabetext.
    """
    NON_CITY_WORDS = {
        "ich", "du", "er", "sie", "es", "wir", "ihr", "was", "wie", "wo", "und", "oder", "für", "in", "um",
        "heute", "morgen", "abend", "abends", "mittag", "mittags", "vormittag", "nachmittag", "nacht", "früh",
        "uhr", "uni", "arbeit", "freizeit", "büro", "schule", "outfit", "mann", "frau", "herren", "damen",
        "männer", "frauen", "kleidung", "hörsaal", "ziehe", "anziehen", "bitte", "warm", "kalt", "wärmer",
        "ja", "nein", "passt", "variante", "ok", "danke", "gut", "anders", "formell", "locker", "soll",
        "kann", "muss", "tragen", "gehen", "fahren", "machen", "brauche", "suche", "empfiehlst", "marke",
        "jacke", "hose", "schuhe", "hemd", "bluse", "wetter", "regen", "wind", "grad", "hochzeit", "party"
    }

    try:
        res = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extrahiere ausschließlich den im Text explizit genannten Stadt- oder Ortsnamen. "
                        "Erfinde NIEMALS einen Ort! Wenn im Text kein konkreter geografischer Ort genannt ist, "
                        "antworte zwingend nur mit dem Wort: NONE"
                    )
                },
                {"role": "user", "content": text}
            ],
            temperature=0.0,
            max_tokens=10
        )
        raw = res.choices[0].message.content.strip(".,!?:;\"'()[]{}-/ \n\t")
        
        # Prüfen, ob das Modell 'NONE' geantwortet hat
        if not raw or "none" in raw.lower() or len(raw) > 25 or len(raw) < 2:
            return None

        # Sicherheitsprüfung: Steht das extrahierte Wort wirklich im Eingabetext des Nutzers?
        input_tokens = [w.strip(".,!?:;\"'()[]{}-/").lower() for w in re.split(r'[,;/|\s]+', text)]
        raw_lower = raw.lower()
        
        if raw_lower in NON_CITY_WORDS:
            return None

        if raw_lower not in input_tokens and raw_lower not in text.lower():
            return None

        # Geografische Prüfung über Open-Meteo
        test = get_weather_data(raw)
        if "error" not in test:
            return test["ort"]
    except Exception:
        pass

    return None

def is_non_goal_query(text: str) -> bool:
    """Prüft, ob die Anfrage auf ein Nicht-Ziel (Marken, Kauf, Größen, Fotos, fremde Anlässe) abzielt."""
    t = text.lower()
    non_goal_keywords = [
        "marke", "kaufen", "shop", "preis", "kosten", "bestellen", "link", "zalando", "amazon",
        "foto", "bild", "größe", "konfektionsgröße", "gewicht", "kilo", "cm", "körper",
        "hochzeit", "gala", "party", "kostüm", "speichern"
    ]
    return any(k in t for k in non_goal_keywords)

# --- 3. STREAMLIT SETUP & SICHTBARE PARAMETER-HINWEISE ---
st.set_page_config(page_title="Garderoben-Agent", page_icon="👔", layout="centered")
st.title("👔 Garderoben-Agent: Was ziehe ich an?")
st.caption("Modul Digitalisierung (NRM 28) · Zeitgenaue Open-Meteo API & Damen-/Herren-Auswahl")

with st.container(border=True):
    st.markdown("### 📋 Eingabehilfe: Benötigte Parameter für deine Anfrage")
    st.markdown(
        "Für ein direktes Ergebnis ohne Rückfragen reichen **kurze Stichworte**:\n"
        "- ✅ **Pflichtangaben:** **1. Zielort** (z. B. *Wien, München*) + **2. Anlass** (*Uni*, *Arbeit* oder *Freizeit*)\n"
        "- ➕ **Optional:** **3. Zeitpunkt** (z. B. *8 Uhr*, *heute Abend*, *morgen 14 Uhr*) + **4. Kategorie** (*Damen* oder *Herren*)"
    )
    st.markdown(
        "💡 **Beispiel-Anfragen in Stichworten (einfach kopieren oder eintippen):**\n"
        "- `Wien, Uni, 8 Uhr, Damen`\n"
        "- `München, Arbeit, morgen 9 Uhr, Herren`\n"
        "- `Hamburg, Freizeit, heute 18 Uhr`"
    )

api_key = st.secrets.get("GROQ_API_KEY") if "GROQ_API_KEY" in st.secrets else None

if not api_key:
    with st.sidebar:
        api_key = st.text_input("Groq API Key eingeben:", type="password")

if not api_key:
    st.info("Bitte hinterlege deinen Groq API Key in den Streamlit Secrets.")
    st.stop()

client = Groq(api_key=api_key)

EXCLUDE = ["whisper", "orpheus", "guard", "vision", "canopy", "tts", "embed", "safeguard"]
try:
    all_models = [m.id for m in client.models.list().data]
    valid_models = [m for m in all_models if not any(x in m.lower() for x in EXCLUDE)]
except Exception:
    valid_models = []

PREFERRED_ORDER = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "gemma2-9b-it"
]

default_idx = 0
for pref in PREFERRED_ORDER:
    if pref in valid_models:
        default_idx = valid_models.index(pref)
        break

with st.sidebar:
    st.subheader("🤖 Modell-Status")
    if valid_models:
        selected_model = st.selectbox("Aktives Text-LLM:", valid_models, index=default_idx)
        st.success(f"Aktiv: `{selected_model}`")
    else:
        selected_model = "llama-3.1-8b-instant"
        st.caption("Standardmodell aktiv.")
    
    st.divider()
    if st.button("🔄 Neues Gespräch starten"):
        st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        st.session_state.current_weather = None
        st.session_state.current_city = None
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
if "current_weather" not in st.session_state:
    st.session_state.current_weather = None
if "current_city" not in st.session_state:
    st.session_state.current_city = None

for msg in st.session_state.messages:
    role = msg.get("role")
    content = msg.get("content")
    if role in ["user", "assistant"] and content:
        with st.chat_message(role):
            st.markdown(content)

# --- 4. CHAT-INTERAKTION ---
st.caption("⌨️ **Kurzformat:** `Ort, Anlass (Uni/Arbeit/Freizeit), [Uhrzeit], [Damen/Herren]`")
user_input = st.chat_input("Stichworte eingeben, z. B.: Wien, Uni, 8 Uhr, Damen")

if user_input:
    detected_city = detect_city_name(user_input, client, selected_model)
    day_offset, target_hour = parse_time_from_text(user_input)

    if detected_city:
        st.session_state.current_city = detected_city

    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # HARTE PRÜFUNG: Wenn kein Ort bekannt ist und keine Nicht-Ziel-Frage vorliegt -> Fehlermeldung ohne Halluzination
    if not st.session_state.current_city and not is_non_goal_query(user_input):
        is_first_reply = not any(m["role"] == "assistant" for m in st.session_state.messages)
        prefix = f"{TRANSPARENZ_TEXT}\n\n" if is_first_reply else ""
        error_reply = (
            f"{prefix}⚠️ **Fehler: Fehlende Ortsangabe**\n\n"
            "Damit ich die Live-Wetterdaten abrufen und dir ein passendes Outfit vorschlagen kann, "
            "benötige ich zwingend deinen **Zielort** (z. B. *Wien, Uni* oder *München, Arbeit*).\n\n"
            "Für welchen Ort suchst du ein Outfit?"
        )
        with st.chat_message("assistant"):
            st.error("Fehler: Fehlende Ortsangabe")
            st.markdown(error_reply)
        st.session_state.messages.append({"role": "assistant", "content": error_reply})
    else:
        # Wetterdaten abrufen, falls Stadt vorhanden
        if st.session_state.current_city and (detected_city or target_hour is not None or not st.session_state.current_weather):
            weather = get_weather_data(st.session_state.current_city, day_offset, target_hour)
            if "error" not in weather:
                st.session_state.current_weather = weather
                st.info(
                    f"📡 **Open-Meteo Wetterdaten für {weather['ort']} ({weather['zeitpunkt']}):** "
                    f"{weather['temperatur']} °C | Wind: {weather['wind']} km/h | Regenrisiko: {weather['regen']} %"
                )

        api_messages = []
        for m in st.session_state.messages:
            api_messages.append({"role": m["role"], "content": m["content"]})

        if st.session_state.current_weather:
            w = st.session_state.current_weather
            weather_note = (
                f"\n\n[SYSTEM-HINWEIS: Offizielle Open-Meteo Wetterdaten für {w['ort']} zum Zeitpunkt '{w['zeitpunkt']}': "
                f"Temperatur: {w['temperatur']} °C, Wind: {w['wind']} km/h, Niederschlagsrisiko: {w['regen']}%. "
                f"Verwende genau diese Zahlen und den Zeitpunkt im Kurzüberblick und in den Begründungen! "
                f"WICHTIG: Gib zwingend alle 3 vollständigen Varianten (Variante 1, Variante 2 und Variante 3) mit je 1 Begründungssatz aus und schließe mit 'Passt das zusammen?'.]"
            )
            api_messages[-1]["content"] += weather_note

        with st.chat_message("assistant"):
            with st.spinner("Erstelle Antwort..."):
                try:
                    response = client.chat.completions.create(
                        model=selected_model,
                        messages=api_messages,
                        temperature=0.6,
                        max_tokens=1200,
                        frequency_penalty=0.5,
                        presence_penalty=0.3
                    )
                    final_text = response.choices[0].message.content.strip()
                    st.markdown(final_text)
                    st.session_state.messages.append({"role": "assistant", "content": final_text})
                except Exception as err:
                    st.error(f"⚠️ Fehler: {str(err)}")
