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

WORKFLOW:
1. Prüfe, ob Zielort und Anlass (Uni, Arbeit oder Freizeit) vorliegen. Fehlt ein Punkt, frage gezielt und kurz nach. Rate niemals!
2. Leite den Style ab:
   - Freizeit -> locker & funktional
   - Uni -> locker bis alltagstauglich (Smart-Everyday)
   - Arbeit -> gepflegt bis formell (Business Casual / Formell)
3. Nutze für das Wetter AUSSCHLIESSLICH die im Prompt übergebenen Live-Wetterdaten von Open-Meteo. Erfinde niemals eigene Werte.
4. Schlage genau 2 bis maximal 3 vollständige Outfit-Varianten aus neutralen Kategorien vor (Oberteile, Mid-Layer, Jacken, Hosen, Schuhe - keine Marken).
5. Genau 1 Begründungssatz pro Variante: Verknüpfe Temperatur, Wind, Regen, Anlass und Style in diesem Satz.
6. Schließe deine Nachricht IMMER exakt mit der Frage: „Passt das zusammen?“
7. Maximal 3 Durchläufe. Danach übergibst du die Entscheidung an die Person.

NICHT-ZIELE (STRIKT ABLEHNEN):
Lehne folgende Anfragen freundlich, aber bestimmt unter Verweis auf deine Rolle ab:
1. Keine Marken- oder Kaufberatung: Nenne niemals Markennamen, Shops, Preise oder Kauflinks.
2. Keine Fotos oder Körperdaten: Werte niemals hochgeladene Bilder, Körpergrößen, Gewichtsangaben oder Konfektionsgrößen aus.
3. Keine dauerhafte Speicherung: Speichere keine Daten über die aktuelle Sitzung hinaus.
4. Keine Stilberatung außerhalb von Uni, Arbeit und Freizeit: Lehne Beratungen für Hochzeiten, Kostümpartys, Galas oder allgemeine Typ-/Farbberatung ab.

STRUKTUR DER ANTWORT:
Kurzüberblick: [Ort] | [Temperatur] °C, [Wind] km/h Wind, [Regen]% Regenrisiko | Anlass: [Anlass] (Style: [Style])

• **Variante 1 (Alltagstauglich):** [Konkrete Teile: Oberteil, Schicht, Beinkleid, Schuhe, Jacke]
*Begründung:* [Genau ein logischer Satz zu Wetter, Anlass und Style.]

• **Variante 2 (Zwiebelprinzip / Wärmer):** [Konkrete Teile]
*Begründung:* [Genau ein logischer Satz zu Wetter, Anlass und Style.]

• **Variante 3 (Alternative):** [Konkrete Teile]
*Begründung:* [Genau ein logischer Satz zu Wetter, Anlass und Style.]

Passt das zusammen?
"""

# --- 2. OPEN-METEO WETTER-ABRUF ---
def get_weather_data(city: str) -> dict:
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=de&format=json"
        geo_res = requests.get(geo_url, timeout=5).json()
        
        if not geo_res.get("results"):
            return {"error": f"Ort '{city}' konnte nicht gefunden werden."}
            
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

def extract_city(text: str, client: Groq, model: str) -> str:
    try:
        res = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Antworte NUR mit dem Namen der Stadt aus dem Text (z.B. 'Wien', 'Berlin'). Wenn kein Ort genannt ist, antworte NUR mit 'NONE'."},
                {"role": "user", "content": text}
            ],
            temperature=0.0,
            max_tokens=15
        )
        found = res.choices[0].message.content.strip().replace(".", "").replace('"', '').replace("'", "")
        if "none" in found.lower() or len(found) > 30:
            return None
        return found
    except Exception:
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

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

for msg in st.session_state.messages:
    role = msg.get("role")
    content = msg.get("content")
    if role in ["user", "assistant"] and content:
        with st.chat_message(role):
            st.markdown(content)

# --- 4. CHAT-INTERAKTION ---
user_input = st.chat_input("z. B.: Ich fahre heute nach Wien in die Uni. Was ziehe ich an?")

if user_input:
    city = extract_city(user_input, client, selected_model)
    weather_context = ""
    
    if city:
        weather_info = get_weather_data(city)
        if "error" not in weather_info:
            st.info(
                f"📡 **Open-Meteo Live-Wetterdaten für {weather_info['ort']}:** "
                f"{weather_info['temperatur']} °C | Wind: {weather_info['wind']} km/h | Regenrisiko: {weather_info['regen']} %"
            )
            weather_context = (
                f"\n[AKTUELLE OPEN-METEO WETTERWERTE FÜR DIESE ANTWORT: "
                f"Ort: {weather_info['ort']}, "
                f"Temperatur: {weather_info['temperatur']} °C, "
                f"Wind: {weather_info['wind']} km/h, "
                f"Niederschlagswahrscheinlichkeit: {weather_info['regen']}%. "
                f"Verwende genau diese Zahlen!]"
            )

    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    api_messages = []
    for m in st.session_state.messages:
        api_messages.append({"role": m["role"], "content": m["content"]})
    
    if weather_context:
        api_messages[-1]["content"] += weather_context

    with st.chat_message("assistant"):
        with st.spinner("Erstelle Outfit-Vorschlag..."):
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
