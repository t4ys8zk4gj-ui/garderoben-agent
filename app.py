import json
import requests
import streamlit as st
from groq import Groq

# --- 1. SYSTEM-PROMPT & REGELN (NRM 28) ---
SYSTEM_PROMPT = """
Du bist der „Garderoben-Agent: Was ziehe ich an?“. Du unterstützt Studierende und Berufstätige dabei, in unter zwei Minuten eine passende Outfit-Auswahl auf Basis des aktuellen Wetters am Zielort und des Tagesanlasses zu treffen.

SPRACHREGELN:
- Antworte in natürlichem, fehlerfreiem Hochdeutsch.
- Duze die Person durchgehend und freundlich.
- Wiederhole dich nicht.

TRANSPARENZHINWEIS:
Beginne deine allererste Antwort im Chat IMMER zwingend mit folgendem Wortlaut:
„ℹ️ **Transparenzhinweis:** Ich bin ein KI-System zur Unterstützung deiner morgendlichen Outfit-Wahl. Meine Vorschläge basieren auf Live-Wetterdaten und festen Bekleidungsregeln – die endgültige Entscheidung triffst immer du selbst.“

WORKFLOW & REGELN:
1. Prüfe, ob Zielort und Anlass (Uni, Arbeit oder Freizeit) vorliegen.
   - Fehlt der Ort? Frage kurz und gezielt nach dem Ort.
   - Fehlt der Anlass? Frage kurz und gezielt nach dem Anlass.
   - WICHTIG: Frage den Nutzer NIEMALS nach Wetterwerten (Temperatur, Wind, Regen)! Der Nutzer kennt diese Werte nicht. Das Wetter kommt ausschließlich automatisch aus dem System.
2. Leite den Style ab:
   - Freizeit -> locker & funktional
   - Uni -> locker bis alltagstauglich (Smart-Everyday)
   - Arbeit -> gepflegt bis formell (Business Casual / Formell)
3. Nutze für das Wetter AUSSCHLIESSLICH die im Prompt übergebenen Live-Wetterdaten von Open-Meteo. Erfinde niemals eigene Werte.
4. Schlage genau 2 bis maximal 3 vollständige Outfit-Varianten aus neutralen Kategorien vor (Oberteile, Mid-Layer, Jacken, Hosen, Schuhe - keine Marken).
5. Genau 1 Begründungssatz pro Variante: Verknüpfe Temperatur, Wind, Regen, Anlass und Style in diesem Satz.
6. Schließe deine Nachricht IMMER exakt mit der Frage: „Passt das zusammen?“
7. Maximal 3 Durchläufe (Zähle Durchläufe intern mit). Übergib danach oder bei Zustimmung die Entscheidung an die Person.

NICHT-ZIELE (STRIKT ABLEHNEN):
Lehne folgende Anfragen freundlich, aber bestimmt unter Verweis auf deine Rolle ab:
1. Keine Marken- oder Kaufberatung: Nenne niemals Markennamen, Shops, Preise oder Kauflinks.
2. Keine Fotos oder Körperdaten: Werte niemals Bilder, Körpergrößen, Gewichtsangaben oder Konfektionsgrößen aus.
3. Keine dauerhafte Speicherung: Speichere keine Daten über die aktuelle Sitzung hinaus.
4. Keine Stilberatung außerhalb von Uni, Arbeit und Freizeit: Lehne Beratungen für Hochzeiten, Partys oder Galas ab.

STRUKTUR DER OUTFIT-ANTWORT:
Kurzüberblick: [Ort] | [Temperatur] °C, [Wind] km/h Wind, [Regen]% Regenrisiko | Anlass: [Anlass] (Style: [Style])

• **Variante 1 (Alltagstauglich):** [Konkrete Zusammenstellung: Oberteil + Schicht + Hose + Schuhe + Jacke]
*Begründung:* [Genau ein logischer Satz zu Wetter, Anlass und Style.]

• **Variante 2 (Zwiebelprinzip / Wärmer):** [Konkrete Zusammenstellung]
*Begründung:* [Genau ein logischer Satz zu Wetter, Anlass und Style.]

• **Variante 3 (Alternative):** [Konkrete Zusammenstellung]
*Begründung:* [Genau ein logischer Satz zu Wetter, Anlass und Style.]

Passt das zusammen?
"""

# --- 2. OPEN-METEO WETTER-ABRUF & ROBUSTE ORTS-ERKENNUNG ---
def get_weather_data(city: str) -> dict:
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
            f"&daily=precipitation_probability_max"
            f"&timezone=auto&forecast_days=1"
        )
        w_res = requests.get(weather_url, timeout=5).json()
        
        return {
            "ort": resolved_name,
            "temperatur": w_res["current"]["temperature_2m"],
            "wind": w_res["current"]["wind_speed_10m"],
            "regen": w_res["daily"]["precipitation_probability_max"][0]
        }
    except Exception as e:
        return {"error": f"Fehler beim API-Abruf: {str(e)}"}

def find_weather(text: str, client: Groq, model: str) -> dict:
    """Findet zuverlässig Wetterdaten aus dem Text via LLM und direktem Geocoding-Fallback."""
    # 1. Schnelle LLM-Extraktion
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
            data = get_weather_data(raw)
            if "error" not in data:
                return data
    except Exception:
        pass

    # 2. Fallback: Wörter im Text direkt gegen Geocoding prüfen
    STOPWORDS = {"Ich", "Du", "Er", "Sie", "Es", "Wir", "Ihr", "Was", "Wie", "Wo", "Heute", "Morgen", "Uni", "Arbeit", "Freizeit", "Büro", "Schule", "Outfit", "Anzug", "Kleidung", "Hörsaal"}
    words = [w.strip(".,!?:;\"'()[]{}") for w in text.split()]
    candidates = [w for w in words if w and w[0].isupper() and w not in STOPWORDS and len(w) > 2]
    
    for candidate in candidates:
        data = get_weather_data(candidate)
        if "error" not in data:
            return data

    return None

# --- 3. STREAMLIT SETUP ---
st.set_page_config(page_title="Garderoben-Agent", page_icon="👔", layout="centered")
st.title("👔 Garderoben-Agent: Was ziehe ich an?")
st.caption("Modul Digitalisierung (NRM 28) · Open-Meteo Live-API & Groq")

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

# Chat-Verlauf rendern
for msg in st.session_state.messages:
    role = msg.get("role")
    content = msg.get("content")
    if role in ["user", "assistant"] and content:
        with st.chat_message(role):
            st.markdown(content)

# --- 4. CHAT-INTERAKTION ---
user_input = st.chat_input("z. B.: Ich fahre heute nach Wien in die Uni. Was ziehe ich an?")

if user_input:
    # 1. Prüfen, ob neuer Ort genannt wurde
    weather = find_weather(user_input, client, selected_model)
    if weather:
        st.session_state.current_weather = weather
        st.info(
            f"📡 **Open-Meteo Live-Wetterdaten für {weather['ort']}:** "
            f"{weather['temperatur']} °C | Wind: {weather['wind']} km/h | Regenrisiko: {weather['regen']} %"
        )

    # 2. Nutzernachricht anzeigen und speichern
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 3. Kontext vorbereiten
    api_messages = []
    for m in st.session_state.messages:
        api_messages.append({"role": m["role"], "content": m["content"]})

    # Wenn Wetterdaten vorliegen (aus dieser oder vorheriger Nachricht), anfügen
    if st.session_state.current_weather:
        w = st.session_state.current_weather
        weather_note = (
            f"\n\n[SYSTEM-HINWEIS: Offizielle Open-Meteo Wetterdaten für {w['ort']}: "
            f"Temperatur: {w['temperatur']} °C, Wind: {w['wind']} km/h, Niederschlagsrisiko: {w['regen']}%. "
            f"Verwende genau diese Zahlen im Kurzüberblick und in den Begründungen! Frage den Nutzer keinesfalls nach Wetterdaten!]"
        )
        api_messages[-1]["content"] += weather_note

    # 4. Antwort generieren
    with st.chat_message("assistant"):
        with st.spinner("Prüfe Outfit..."):
            try:
                response = client.chat.completions.create(
                    model=selected_model,
                    messages=api_messages,
                    temperature=0.6,
                    max_tokens=700,
                    frequency_penalty=0.5,
                    presence_penalty=0.3
                )
                final_text = response.choices[0].message.content.strip()
                st.markdown(final_text)
                st.session_state.messages.append({"role": "assistant", "content": final_text})
            except Exception as err:
                st.error(f"⚠️ Fehler: {str(err)}")
