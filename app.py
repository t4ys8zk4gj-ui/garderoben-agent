import json
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
1. Prüfe, ob Zielort und Anlass (Uni, Arbeit oder Freizeit) vorliegen. Fehlt ein Punkt, frage kurz nach. Rate niemals den Ort oder Anlass!
2. Leite den Style ab:
   - Freizeit -> locker & funktional
   - Uni -> locker bis alltagstauglich (Smart-Everyday)
   - Arbeit -> gepflegt bis formell (Business Casual / Formell)
3. Rufe das Wetter ZWINGEND über das Tool `get_weather_data` ab. Erfinde niemals Wetterwerte!
4. Schlage maximal 3 Outfit-Varianten aus neutralen Kategorien vor (Oberteile, Mid-Layer, Jacken, Hosen, Schuhe - keine Marken).
5. Genau 1 Begründungssatz pro Variante: Verknüpfe Temperatur, Wind, Niederschlag, Anlass und Style in diesem Satz.
6. Schließe immer exakt mit der Frage: „Passt das zusammen?“ (Maximal 3 Durchläufe).
7. Übergib nach Bestätigung oder nach Durchlauf 3 die finale Entscheidung an die Person.

Nicht-Ziele (strikt ablehnen):
Keine Marken- oder Kaufberatung, keine Analyse von Fotos oder Körpermaßen/Größen, keine dauerhafte Speicherung, keine Stilberatung außerhalb von Uni/Arbeit/Freizeit.
"""

# Universell verfügbares Groq-Modell mit Tool-Support
MODEL_NAME = "llama-3.1-8b-instant"

# --- 2. OPEN-METEO WETTER-ABRUF ---
def get_weather_data(city: str) -> str:
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=de&format=json"
        geo_res = requests.get(geo_url, timeout=5).json()
        
        if not geo_res.get("results"):
            return json.dumps({"error": f"Ort '{city}' nicht gefunden."})
            
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
        
        data = {
            "ort": resolved_name,
            "temperatur_celsius": w_res["current"]["temperature_2m"],
            "wind_kmh": w_res["current"]["wind_speed_10m"],
            "niederschlagswahrscheinlichkeit_prozent": w_res["daily"]["precipitation_probability_max"][0]
        }
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": f"Fehler beim API-Abruf: {str(e)}"})

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather_data",
            "description": "Ruft aktuelle Wetterdaten (Temperatur, Wind, Niederschlagswahrscheinlichkeit) für eine Stadt über die Open-Meteo API ab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "Der Name der Stadt, z. B. Wien, Berlin, Hamburg"
                    }
                },
                "required": ["city"]
            }
        }
    }
]

# --- 3. STREAMLIT SETUP ---
st.set_page_config(page_title="Garderoben-Agent", page_icon="👔", layout="centered")
st.title("👔 Garderoben-Agent: Was ziehe ich an?")
st.caption("Modul Digitalisierung (NRM 28) · Powered by Groq & Open-Meteo API")

api_key = st.secrets.get("GROQ_API_KEY") if "GROQ_API_KEY" in st.secrets else None

if not api_key:
    with st.sidebar:
        api_key = st.text_input("Groq API Key eingeben:", type="password")
        st.caption("Kostenlos auf console.groq.com/keys")

if not api_key:
    st.info("Bitte trage deinen Groq API Key in die Streamlit Secrets ein.")
    st.stop()

client = Groq(api_key=api_key)

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

for msg in st.session_state.messages:
    role = msg.get("role")
    content = msg.get("content")
    if role in ["user", "assistant"] and content:
        with st.chat_message(role):
            st.markdown(content)

# --- 4. CHAT-LOGIK ---
user_input = st.chat_input("z. B.: Ich fahre heute nach Wien in die Uni. Was ziehe ich an?")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Prüfe Wetter via Open-Meteo und erstelle Outfit..."):
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=st.session_state.messages,
                tools=TOOLS,
                tool_choice="auto"
            )
            response_message = response.choices[0].message

            if response_message.tool_calls:
                st.session_state.messages.append(response_message.model_dump())
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    if function_name == "get_weather_data":
                        tool_output = get_weather_data(city=function_args.get("city"))
                        st.session_state.messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": tool_output
                        })
                
                second_response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=st.session_state.messages
                )
                final_text = second_response.choices[0].message.content
            else:
                final_text = response_message.content

            st.markdown(final_text)
            st.session_state.messages.append({"role": "assistant", "content": final_text})
