import streamlit as st
import requests
import google.generativeai as genai

# --- 1. SYSTEM-PROMPT & WISSENSBASIS ---
SYSTEM_PROMPT = """
Du bist der „Garderoben-Agent: Was ziehe ich an?“. Du unterstützt Studierende und Berufstätige dabei, in unter zwei Minuten eine passende Outfit-Auswahl auf Basis des aktuellen Wetters am Zielort und des Tagesanlasses zu treffen.

ℹ️ Transparenzhinweis:
Beginne JEDE allererste Chat-Antwort mit:
„ℹ️ **Transparenzhinweis:** Ich bin ein KI-System zur Unterstützung deiner morgendlichen Outfit-Wahl. Meine Vorschläge basieren auf Live-Wetterdaten und festen Bekleidungsregeln – die endgültige Entscheidung triffst immer du selbst.“

Workflow:
1. Prüfe, ob Zielort und Anlass (Uni, Arbeit oder Freizeit) vorliegen. Fehlt ein Punkt, frage kurz nach. Rate niemals!
2. Leite den Style ab:
   - Freizeit -> locker & funktional
   - Uni -> locker bis alltagstauglich (Smart-Everyday)
   - Arbeit -> gepflegt bis formell (Business Casual / Formell)
3. Rufe das Wetter ZWINGEND über das bereitgestellte Tool `get_weather_data` ab. Nenne niemals ausgedachte Wetterwerte!
4. Schlage maximal 3 Outfit-Varianten aus markenfreien Kategorien vor (Oberteile, Mid-Layer, Jacken, Hosen, Schuhe).
5. Genau 1 Begründungssatz pro Variante: Verknüpfe Temperatur, Wind, Niederschlag, Anlass und Style in diesem Satz.
6. Schließe immer exakt mit: „Passt das zusammen?“ (Zähle Durchläufe intern mit, maximal 3 Iterationen).
7. Übergib nach Bestätigung oder nach Durchlauf 3 die finale Entscheidung an die Person.

Nicht-Ziele (strikt ablehnen):
Keine Marken/Kaufberatung, keine Analyse von Fotos oder Körpermaßen/Konfektionsgrößen, keine Speicherung, keine Stilberatung außerhalb von Uni/Arbeit/Freizeit.
"""

# --- 2. OPEN-METEO API ALS FUNCTION-CALLING TOOL ---
def get_weather_data(city: str) -> dict:
    """
    Ruft Live-Wetterdaten (Temperatur, Windgeschwindigkeit und maximale Niederschlagswahrscheinlichkeit)
    für einen Zielort über die Open-Meteo API ab.
    """
    try:
        # Geocoding: Stadt in Koordinaten umwandeln
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=de&format=json"
        geo_res = requests.get(geo_url, timeout=5).json()
        
        if not geo_res.get("results"):
            return {"error": f"Der Ort '{city}' konnte nicht gefunden werden. Bitte prüfe die Schreibweise."}
        
        lat = geo_res["results"][0]["latitude"]
        lon = geo_res["results"][0]["longitude"]
        resolved_name = geo_res["results"][0]["name"]
        
        # Wetterdaten für heute abfragen
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,wind_speed_10m"
            f"&daily=precipitation_probability_max"
            f"&timezone=auto&forecast_days=1"
        )
        w_res = requests.get(weather_url, timeout=5).json()
        
        return {
            "ort": resolved_name,
            "temperatur_celsius": w_res["current"]["temperature_2m"],
            "wind_kmh": w_res["current"]["wind_speed_10m"],
            "niederschlagswahrscheinlichkeit_prozent": w_res["daily"]["precipitation_probability_max"][0]
        }
    except Exception as e:
        return {"error": f"Technischer Fehler beim Abruf der Wetter-API: {str(e)}"}

# --- 3. STREAMLIT OBERFLÄCHE INITIALISIEREN ---
st.set_page_config(page_title="Garderoben-Agent", page_icon="👔", layout="centered")

st.title("👔 Garderoben-Agent: Was ziehe ich an?")
st.caption("Modul Digitalisierung (NRM 28) · Powered by Gemini & Open-Meteo API")

# API-Key laden (entweder aus Streamlit Secrets oder Sidebar)
api_key = st.secrets.get("GEMINI_API_KEY") if "GEMINI_API_KEY" in st.secrets else None

if not api_key:
    with st.sidebar:
        st.subheader("Konfiguration")
        api_key = st.text_input("Gemini API Key eingeben:", type="password")
        st.caption("Erhältlich kostenlos auf aistudio.google.com")

if not api_key:
    st.info("Bitte hinterlege deinen Gemini API-Key (in den Streamlit Secrets oder in der Seitenleiste links), um den Agenten zu starten.")
    st.stop()

# Gemini initialisieren
genai.configure(api_key=api_key)
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction=SYSTEM_PROMPT,
    tools=[get_weather_data]
)

# Chat-Verlauf im Session State halten
if "chat_session" not in st.session_state:
    st.session_state.chat_session = model.start_chat(enable_automatic_function_calling=True)
if "messages" not in st.session_state:
    st.session_state.messages = []

# Bisherige Nachrichten im Chat zeichnen
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- 4. CHAT-INTERAKTION ---
user_input = st.chat_input("z. B.: Ich fahre heute nach Wien in die Uni. Was ziehe ich an?")

if user_input:
    # Nutzereingabe anzeigen
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Antwort vom Agenten generieren
    with st.chat_message("assistant"):
        with st.spinner("Prüfe Wetter via Open-Meteo und erstelle Outfit..."):
            response = st.session_state.chat_session.send_message(user_input)
            agent_text = response.text
            st.markdown(agent_text)
            
    st.session_state.messages.append({"role": "assistant", "content": agent_text})