import re
import requests
import streamlit as st
from groq import Groq

# --- 1. SYSTEM-PROMPT & REGELN (NRM 28) ---
SYSTEM_PROMPT = """
Du bist der „Garderoben-Agent: Was ziehe ich an?“. Du unterstützt Studierende und Berufstätige dabei, in unter zwei Minuten eine passende Outfit-Auswahl auf Basis des Wetters am Zielort (inklusive Uhrzeit) und des Tagesanlasses zu treffen.

SPRACHREGELN:
- Antworte in natürlichem, fehlerfreiem Hochdeutsch.
- Duze die Person durchgehend und freundlich.
- Wiederhole dich nicht.

TRANSPARENZHINWEIS:
Beginne deine allererste Antwort im Chat IMMER zwingend mit folgendem Wortlaut:
„ℹ️ **Transparenzhinweis:** Ich bin ein KI-System zur Unterstützung deiner morgendlichen Outfit-Wahl. Meine Vorschläge basieren auf Live-Wetterdaten und festen Bekleidungsregeln – die endgültige Entscheidung triffst immer du selbst.“

UNTERSCHEIDUNG DAMEN- UND HERRENBEKLEIDUNG (MARKENFREI):
Berücksichtige die Unterschiede zwischen Damen- und Herrenbekleidung:
- **Herrenbekleidung:**
  - Freizeit: T-Shirt, Poloshirt, Hoodie, Sweatshirt, Jeans, Cargohose, Shorts, Sneaker, derbe Boots, Windbreaker, Regenjacke, Winterparka.
  - Uni: T-Shirt, Langarmshirt, Strickpullover, Cardigan, Freizeithemd, Jeans, Chino, Sneaker, Chelsea-Boots, Übergangsjacke.
  - Arbeit: Klassisches Hemd, Feinstrickpullover, Sakko, Anzughose, gepflegte Chino, Lederschnürschuhe, Loafer, Trenchcoat, Wollmantel.
- **Damenbekleidung:**
  - Freizeit: T-Shirt, Top, Hoodie, Strickpullover, Jeans, Freizeithose, Leggings, Sommerrock, Sneaker, Schnürboots, Regenjacke, Steppjacke.
  - Uni: Blusenshirt, Rollkragenpullover, Cardigan, Jeans, Stoffhose, Midi-Rock (bei Kälte mit Strumpfhose), Sneaker, Stiefeletten, Trenchcoat/Übergangsjacke.
  - Arbeit: Bluse, Feinstrickoberteil, Blazer, Stoffhose/Bundfaltenhose, Bleistiftrock/Kostümrock (ggf. mit Strumpfhose), Loafer, Stiefeletten, Pumps, Trenchcoat, eleganter Wollmantel.
- **Regel zur Ausgabe:** Wenn die Person angibt, ob sie Damen- oder Herrenbekleidung sucht, schlage nur diese Kategorie vor. Macht sie keine Angabe, führe in jeder Variante beides getrennt auf („👚 Damen: ... | 👔 Herren: ...“).

WORKFLOW & REGELN:
1. Prüfe, ob Zielort und Anlass (Uni, Arbeit oder Freizeit) vorliegen.
   - Fehlt der Ort? Frage kurz und gezielt nach dem Ort.
   - Fehlt der Anlass? Frage kurz und gezielt nach dem Anlass.
   - WICHTIG: Frage den Nutzer NIEMALS nach Wetterwerten! Das Wetter kommt automatisch aus dem System.
2. Leite den Style ab:
   - Freizeit -> locker & funktional
   - Uni -> locker bis alltagstauglich (Smart-Everyday)
   - Arbeit -> gepflegt bis formell (Business Casual / Formell)
3. Nutze für das Wetter und die Uhrzeit AUSSCHLIESSLICH die übergebenen Open-Meteo-Werte. Erfinde niemals eigene Werte.
4. Schlage genau 2 bis maximal 3 vollständige Outfit-Varianten vor (keine Marken).
5. Genau 1 Begründungssatz pro Variante: Verknüpfe Zeitpunkt/Wetterwerte (Temperatur, Wind, Regen), Anlass und Style logisch in diesem Satz.
6. Schließe deine Nachricht IMMER exakt mit der Frage: „Passt das zusammen?“
7. Maximal 3 Durchläufe. Übergib danach oder bei Zustimmung die Entscheidung an die Person.

NICHT-ZIELE (STRIKT ABLEHNEN):
1. Keine Marken- oder Kaufberatung (keine Marken, Shops, Preise).
2. Keine Fotos oder Körpermaße/Konfektionsgrößen auswerten.
3. Keine dauerhafte Speicherung über die Sitzung hinaus.
4. Keine Stilberatung außerhalb von Uni, Arbeit und Freizeit (keine Hochzeiten, Galas, Kostüme).

STRUKTUR DER OUTFIT-ANTWORT:
Kurzüberblick: [Ort] ([Zeitpunkt]) | [Temperatur] °C, [Wind] km/h Wind, [Regen]% Regenrisiko | Anlass: [Anlass] (Style: [Style])

• **Variante 1 (Alltagstauglich / Klassisch):**
  - 👚 Damen: [Oberteil, Schicht, Beinkleid, Schuhe, Jacke]
  - 👔 Herren: [Oberteil, Schicht, Beinkleid, Schuhe, Jacke]
  *(Hinweis: Falls Damen oder Herren explizit gewünscht wurde, zeige nur die gewünschte Zeile)*
  *Begründung:* [Genau ein logischer Satz zu Wetter zur genannten Uhrzeit, Anlass und Style.]

• **Variante 2 (Zwiebelprinzip / Wärmer):**
  - 👚 Damen: [...]
  - 👔 Herren: [...]
  *Begründung:* [Genau ein logischer Satz zu Wetter, Anlass und Style.]

• **Variante 3 (Funktional / Alternativ):**
  - 👚 Damen: [...]
  - 👔 Herren: [...]
  *Begründung:* [Genau ein logischer Satz zu Wetter, Anlass und Style.]

Passt das zusammen?
"""

# --- 2. ZEIT- & ORTSERKENNUNG SOWIE OPEN-METEO API ---
def parse_time_from_text(text: str) -> tuple:
    """
    Erkennt Zeitangaben im Text.
    Gibt (day_offset, hour, label_found) zurück.
    day_offset: 0 = Heute, 1 = Morgen
    hour: 0-23 oder None (falls aktuelle Uhrzeit genutzt werden soll)
    """
    t = text.lower()
    day_offset = 1 if ("morgen" in t and "heute morgen" not in t and "guten morgen" not in t) else 0
    hour = None

    # 1. Explizite Uhrzeit suchen, z. B. "18 Uhr", "18:00", "um 8 uhr"
    match = re.search(r'\b([01]?\d|2[0-3])(?::(\d{2}))?\s*uhr\b', t)
    if not match:
        match = re.search(r'\bum\s+([01]?\d|2[0-3])(?::(\d{2}))?\b', t)
    
    if match:
        hour = int(match.group(1))
    else:
        # 2. Tageszeiten-Schlüsselwörter prüfen
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
            # Wenn nur "morgen" ohne Uhrzeit genannt wurde -> 09:00 Uhr als Standard
            hour = 9

    return day_offset, hour

def get_weather_data(city: str, day_offset: int = 0, hour: int = None) -> dict:
    """Ruft entweder aktuelle Wetterdaten oder stundengenaue Vorhersagen von Open-Meteo ab."""
    try:
        clean_city = city.strip(".,!?:;\"'()[]{}")
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
        
        # Fall A: Spezifische Uhrzeit / Tageszeit wurde genannt -> Hourly Forecast nutzen
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
        
        # Fall B: Keine Uhrzeit genannt -> Aktuelles Live-Wetter nutzen
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
    """Extrahiert den Stadtnamen via LLM oder Wort-Fallback."""
    try:
        res = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Antworte NUR mit dem reinen Namen der Stadt (z.B. 'Wien'). Wenn kein Ort genannt ist, antworte NUR mit 'NONE'."},
                {"role": "user", "content": text}
            ],
            temperature=0.0,
            max_tokens=10
        )
        raw = res.choices[0].message.content.strip()
        for junk in ["die stadt ist", "stadt:", "ort:", "der ort lautet", "in "]:
            if raw.lower().startswith(junk):
                raw = raw[len(junk):].strip()
        raw = raw.strip(".,!?:;\"'()[]{}")
        
        if "none" not in raw.lower() and len(raw) < 25:
            test = get_weather_data(raw)
            if "error" not in test:
                return test["ort"]
    except Exception:
        pass

    STOPWORDS = {
        "Ich", "Du", "Er", "Sie", "Es", "Wir", "Ihr", "Was", "Wie", "Wo",
        "Heute", "Morgen", "Abend", "Mittag", "Vormittag", "Nachmittag", "Nacht",
        "Uhr", "Uni", "Arbeit", "Freizeit", "Büro", "Schule", "Outfit", "Mann",
        "Frau", "Herren", "Damen", "Männer", "Frauen", "Kleidung", "Hörsaal"
    }
    words = [w.strip(".,!?:;\"'()[]{}") for w in text.split()]
    candidates = [w for w in words if w and w[0].isupper() and w not in STOPWORDS and len(w) > 2]
    
    for candidate in candidates:
        test = get_weather_data(candidate)
        if "error" not in test:
            return test["ort"]

    return None

# --- 3. STREAMLIT SETUP ---
st.set_page_config(page_title="Garderoben-Agent", page_icon="👔", layout="centered")
st.title("👔 Garderoben-Agent: Was ziehe ich an?")
st.caption("Modul Digitalisierung (NRM 28) · Zeitgenaue Open-Meteo API & Damen-/Herren-Auswahl")

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

# Session States initialisieren
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
if "current_weather" not in st.session_state:
    st.session_state.current_weather = None
if "current_city" not in st.session_state:
    st.session_state.current_city = None

# Chat-Verlauf rendern
for msg in st.session_state.messages:
    role = msg.get("role")
    content = msg.get("content")
    if role in ["user", "assistant"] and content:
        with st.chat_message(role):
            st.markdown(content)

# --- 4. CHAT-INTERAKTION ---
user_input = st.chat_input("z. B.: Ich muss heute um 18 Uhr in Wien zur Arbeit (Herren). Was ziehe ich an?")

if user_input:
    # 1. Stadt und gewünschte Uhrzeit aus der Frage ermitteln
    detected_city = detect_city_name(user_input, client, selected_model)
    day_offset, target_hour = parse_time_from_text(user_input)

    if detected_city:
        st.session_state.current_city = detected_city

    # Wetter neu abrufen, wenn eine Stadt bekannt ist (entweder neu genannt oder mit neuer Zeitangabe)
    if st.session_state.current_city and (detected_city or target_hour is not None or not st.session_state.current_weather):
        weather = get_weather_data(st.session_state.current_city, day_offset, target_hour)
        if "error" not in weather:
            st.session_state.current_weather = weather
            st.info(
                f"📡 **Open-Meteo Wetterdaten für {weather['ort']} ({weather['zeitpunkt']}):** "
                f"{weather['temperatur']} °C | Wind: {weather['wind']} km/h | Regenrisiko: {weather['regen']} %"
            )

    # 2. Nutzernachricht anzeigen und speichern
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 3. Kontext für das Modell aufbereiten
    api_messages = []
    for m in st.session_state.messages:
        api_messages.append({"role": m["role"], "content": m["content"]})

    if st.session_state.current_weather:
        w = st.session_state.current_weather
        weather_note = (
            f"\n\n[SYSTEM-HINWEIS: Offizielle Open-Meteo Wetterdaten für {w['ort']} zum Zeitpunkt '{w['zeitpunkt']}': "
            f"Temperatur: {w['temperatur']} °C, Wind: {w['wind']} km/h, Niederschlagsrisiko: {w['regen']}%. "
            f"Verwende genau diese Zahlen und den Zeitpunkt im Kurzüberblick und in den Begründungen!]"
        )
        api_messages[-1]["content"] += weather_note

    # 4. Antwort generieren
    with st.chat_message("assistant"):
        with st.spinner("Prüfe Outfit für Zeitpunkt & Anlass..."):
            try:
                response = client.chat.completions.create(
                    model=selected_model,
                    messages=api_messages,
                    temperature=0.6,
                    max_tokens=800,
                    frequency_penalty=0.5,
                    presence_penalty=0.3
                )
                final_text = response.choices[0].message.content.strip()
                st.markdown(final_text)
                st.session_state.messages.append({"role": "assistant", "content": final_text})
            except Exception as err:
                st.error(f"⚠️ Fehler: {str(err)}")
