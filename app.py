import json
import re
import requests
import streamlit as st
from groq import Groq

# --- 1. SYSTEM-PROMPT & REGELN (NRM 28) ---
SYSTEM_PROMPT = """
Du bist der „Garderoben-Agent: Was ziehe ich an?“. Du unterstützt Studierende und Berufstätige dabei, in unter zwei Minuten eine passende Outfit-Auswahl auf Basis des aktuellen Wetters am Zielort und des Tagesanlasses zu treffen.

Zwingender Transparenzhinweis:
Beginne JEDE allererste Antwort im Chat zwingend mit:
„ℹ️ **Transparenzhinweis:** Ich bin ein KI-System zur Unterstützung deiner morgendlichen Outfit-Wahl. Meine Vorschläge basieren auf Live-Wetterdaten und festen Bekleidungsregeln – die endgültige Entscheidung triffst immer du selbst.“

Workflow:
1. Prüfe, ob Zielort und Anlass (Uni, Arbeit oder Freizeit) vorliegen. Fehlt ein Punkt, frage gezielt und kurz nach. Rate niemals den Ort oder Anlass!
2. Leite den Style ab:
   - Freizeit -> locker & funktional
   - Uni -> locker bis alltagstauglich (Smart-Everyday)
   - Arbeit -> gepflegt bis formell (Business Casual / Formell)
3. Wenn dir unten echte Live-Wetterdaten von Open-Meteo übergeben wurden, nutze AUSSCHLIESSLICH diese echten Werte (Temperatur, Wind, Regen). Erfinde niemals eigene Wetterwerte!
4. Schlage maximal 3 Outfit-Varianten aus neutralen Kategorien vor (Oberteile, Mid-Layer, Jacken, Hosen, Schuhe - keine Marken).
5. Genau 1 Begründungssatz pro Variante: Verknüpfe Temperatur, Wind, Niederschlag, Anlass und Style in diesem Satz.
6. Schließe immer exakt mit der Frage: „Passt das zusammen?“ (Maximal 3 Durchläufe mitzählen).
7. Übergib nach Bestätigung oder nach Durchlauf 3 die finale Entscheidung an die Person.

Nicht-Ziele (strikt ablehnen):
Keine Marken- oder Kaufberatung, keine Analyse von Fotos oder Körpermaßen/Größen, keine dauerhafte Speicherung, keine Stilberatung außerhalb von Uni/Arbeit/Freizeit.
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

# Hilfsfunktion: Stadt aus dem Text ermitteln
def extract_city(text: str, client: Groq, model: str) -> str:
    try:
        res = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Nenne ausschließlich den Namen der gesuchten Stadt aus dem Text als einzelnes Wort (z.B. 'Wien', 'München', 'Berlin'). Wenn keine Stadt oder kein Ort genannt wurde, antworte NUR mit 'NONE'."},
                {"role": "user", "content": text}
            ],
            temperature=0.0
        )
        found = res.choices[0].message.content.strip().replace(".", "").replace('"', "")
        return None if "none" in found.lower() else found
    except Exception:
        return None

# --- 3. STREAMLIT SETUP ---
st.set_page_config(page_title="Garderoben-Agent", page_icon="👔", layout="centered")
st.title("👔 Garderoben-Agent: Was ziehe ich an?")
st.caption("Modul Digitalisierung (NRM 28) · Open-Meteo Live-API & Groq LLM")

api_key = st.secrets.get("GROQ_API_KEY") if "GROQ_API_KEY" in st.secrets else None

if not api_key:
    with st.sidebar:
        api_key = st.text_input("Groq API Key eingeben:", type="password")

if not api_key:
    st.info("Bitte trage deinen Groq API Key in die Streamlit Secrets ein.")
    st.stop()

client = Groq(api_key=api_key)

# Verfügbare Modelle ermitteln
try:
    groq_models = [m.id for m in client.models.list().data if "whisper" not in m.id]
except Exception:
    groq_models = ["llama3-8b-8192"]

default_idx = 0
for idx, name in enumerate(groq_models):
    if any(k in name.lower() for k in ["llama-3", "llama3", "mixtral"]):
        default_idx = idx
        break

with st.sidebar:
    st.subheader("🤖 Modell-Status")
    selected_model = st.selectbox("Aktives LLM:", groq_models, index=default_idx)
    st.success(f"Aktiv: `{selected_model}`")

# Session State initialisieren
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
if "last_weather" not in st.session_state:
    st.session_state.last_weather = None

# Bisherigen Chatverlauf anzeigen
for msg in st.session_state.messages:
    role = msg.get("role")
    content = msg.get("content")
    if role in ["user", "assistant"] and content and not content.startswith("[SYSTEM-WETTER"):
        with st.chat_message(role):
            st.markdown(content)

# --- 4. CHAT-INTERAKTION ---
user_input = st.chat_input("z. B.: Ich fahre heute nach Wien in die Uni. Was ziehe ich an?")

if user_input:
    # 1. Nutzereingabe anzeigen
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Prüfe Eingabe & Wetterdaten via Open-Meteo..."):
            try:
                # Prüfen, ob eine Stadt genannt wurde
                city = extract_city(user_input, client, selected_model)
                
                # Wenn eine Stadt erkannt wurde: Echte Open-Meteo API anfragen
                if city:
                    weather_info = get_weather_data(city)
                    if "error" not in weather_info:
                        st.session_state.last_weather = weather_info
                        st.info(
                            f"📡 **Open-Meteo Live-Wetterdaten für {weather_info['ort']}:** "
                            f"{weather_info['temperatur']} °C | Wind: {weather_info['wind']} km/h | Regenrisiko: {weather_info['regen']} %"
                        )
                        # Wetterdaten verbindlich in den Kontext übergeben
                        weather_prompt = (
                            f"[SYSTEM-WETTERDATEN VON OPEN-METEO API]: "
                            f"Ort: {weather_info['ort']}, "
                            f"Temperatur: {weather_info['temperatur']} °C, "
                            f"Wind: {weather_info['wind']} km/h, "
                            f"Niederschlagswahrscheinlichkeit: {weather_info['regen']}%. "
                            f"Nutze genau diese Werte!"
                        )
                        st.session_state.messages.append({"role": "system", "content": weather_prompt})

                # Antwort vom LLM generieren
                response = client.chat.completions.create(
                    model=selected_model,
                    messages=st.session_state.messages,
                    temperature=0.3
                )
                final_text = response.choices[0].message.content
                st.markdown(final_text)
                st.session_state.messages.append({"role": "assistant", "content": final_text})

            except Exception as err:
                st.error(f"⚠️ Fehler beim Generieren: {str(err)}")
