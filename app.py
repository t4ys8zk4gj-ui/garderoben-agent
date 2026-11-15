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

# --- 2. PRÜFFUNKTIONEN (NICHT-ZIELE, ZEIT, ORT & WETTER-API) ---
def check_non_goals(text: str) -> str:
    """
    Prüft deterministisch auf Nicht-Ziele (Marken, Kaufberatung, Körpermaße, fremde Anlässe)
    und gibt bei einem Treffer direkt den passenden Ablehnungsgrund zurück.
    """
    t = text.lower()
    tokens = set(re.split(r'[,;/|\s.!?:;"\'()\[\]{}\-]+', t))

    # 1. Marken- und Kaufberatung
    brand_keywords = {
        "marke", "marken", "markenname", "markennamen", "markenempfehlung", "kaufen", "kauf",
        "kaufberatung", "shop", "shops", "online-shop", "preis", "preise", "kosten", "kostet",
        "bestellen", "kauflink", "rabatt", "angebot", "zalando", "amazon", "aboutyou", "asos",
        "nike", "adidas", "puma", "reebok", "asics", "newbalance", "vans", "converse",
        "zara", "h&m", "hm", "uniqlo", "mango", "bershka", "pull&bear", "massimodutti", "c&a",
        "gucci", "prada", "louisvuitton", "chanel", "dior", "balenciaga", "versace", "hermes",
        "levi", "levis", "wrangler", "diesel", "g-star", "pepe",
        "northface", "jackwolfskin", "patagonia", "columbia", "mammut", "vaude", "salomon",
        "boss", "hugoboss", "tommy", "hilfiger", "calvinklein", "ralphlauren", "lacoste",
        "gant", "marcO'polo", "marcopolo", "esprit", "s.oliver", "soliver", "tomtailor",
        "carhartt", "dickies", "stoneisland", "moncler", "canadagoose", "wellensteyn",
        "timberland", "drmartens", "martens", "birkenstock", "ugg", "geox", "deichmann", "snipes"
    }
    brand_phrases = [
        "north face", "jack wolfskin", "new balance", "hugo boss", "tommy hilfiger",
        "calvin klein", "ralph lauren", "stone island", "canada goose", "dr. martens",
        "dr martens", "about you", "marc o'polo", "s. oliver", "tom tailor", "h & m", "c & a"
    ]
    if (tokens & brand_keywords) or any(p in t for p in brand_phrases):
        return (
            "⚠️ **Fehler: Keine Marken- oder Kaufberatung (Nicht-Ziel)**\n\n"
            "Als neutraler Garderoben-Agent gebe ich **keine Markenempfehlungen, Produktnamen, "
            "Preise oder Kauflinks** aus und bewerte auch keine einzelnen Kleidungsmarken.\n\n"
            "Bitte gib deine Anfrage ohne Markennamen ein (z. B. *Wien, Uni, 8 Uhr, Damen*)."
        )

    # 2. Körperdaten, Größen & Fotos
    body_keywords = {
        "foto", "fotos", "bild", "bilder", "selfie", "hochladen", "konfektionsgröße",
        "kleidergröße", "schuhgröße", "körpergröße", "gewicht", "kilo", "kilogramm",
        "körpermaße", "maße", "taillenumfang", "brustumfang", "bmi", "figurtyp"
    }
    if (tokens & body_keywords) or re.search(r'\b\d{2,3}\s*(kg|kilo|cm)\b', t) or re.search(r'\bgröße\s*(xs|s|m|l|xl|xxl|\d{2})\b', t):
        return (
            "⚠️ **Fehler: Keine Auswertung von Körperdaten, Größen oder Fotos (Nicht-Ziel)**\n\n"
            "Aus Gründen des Datenschutzes (*Privacy by Design*) werte ich **keine Fotos, "
            "Körpermaße, Gewichtsangaben oder Konfektionsgrößen** aus.\n\n"
            "Bitte beschränke deine Eingabe auf Ort, Anlass, optionale Uhrzeit und Damen/Herren."
        )

    # 3. Fremde Anlässe außerhalb von Uni, Arbeit und Freizeit
    event_keywords = {
        "hochzeit", "braut", "bräutigam", "trauzeuge", "gala", "roterteppich", "abiball",
        "prom", "fasching", "karneval", "kostüm", "kostümparty", "halloween", "taufe",
        "beerdigung", "trauerfeier", "oper", "staatsoper", "junggesellenabschied"
    }
    if tokens & event_keywords:
        return (
            "⚠️ **Fehler: Anlass außerhalb des Anwendungsbereichs (Nicht-Ziel)**\n\n"
            "Ich bin ausschließlich auf die Alltagsanlässe **Uni, Arbeit und Freizeit** spezialisiert "
            "und führe keine Stilberatung für besondere Events (wie Hochzeiten, Galas oder Kostümpartys) durch."
        )

    # 4. Dauerhafte Speicherung
    if any(w in tokens for w in {"speichern", "abspeichern", "merken", "profil", "datenbank", "account"}):
        return (
            "⚠️ **Fehler: Keine dauerhafte Datenspeicherung (Nicht-Ziel)**\n\n"
            "Ich speichere keine persönlichen Profile, Kleiderschränke oder Einstellungen über die aktuelle Sitzung hinaus."
        )

    return None

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
        
        if not raw or "none" in raw.lower() or len(raw) > 25 or len(raw) < 2:
            return None

        input_tokens = [w.strip(".,!?:;\"'()[]{}-/").lower() for w in re.split(r'[,;/|\s]+', text)]
        raw_lower = raw.lower()
        
        if raw_lower in NON_CITY_WORDS:
            return None

        if raw_lower not in input_tokens and raw_lower not in text.lower():
            return None

        test = get_weather_data(raw)
        if "error" not in test:
            return test["ort"]
    except Exception:
        pass

    return None

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

# 'allam' und weitere ungeeignete Spezialmodelle explizit ausschließen
EXCLUDE = ["whisper", "orpheus", "guard", "vision", "canopy", "tts", "embed", "safeguard", "allam", "playai"]
try:
    all_models = [m.id for m in client.models.list().data]
    valid_models = [m for m in all_models if not any(x in m.lower() for x in EXCLUDE)]
except Exception:
    valid_models = []

PREFERRED_ORDER = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "gemma2-9b-it",
    "mixtral-8x7b-32768"
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
        selected_model = "llama-3.3-70b-versatile"
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
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    is_first_reply = not any(m["role"] == "assistant" for m in st.session_state.messages)
    prefix = f"{TRANSPARENZ_TEXT}\n\n" if is_first_reply else ""

    # 1. HARTE PRÜFUNG AUF NICHT-ZIELE (Marken, Kaufberatung, Größen, Fotos, fremde Anlässe)
    non_goal_error = check_non_goals(user_input)
    if non_goal_error:
        full_error = f"{prefix}{non_goal_error}"
        with st.chat_message("assistant"):
            st.error("Fehler: Unzulässige Anfrage (Nicht-Ziel)")
            st.markdown(full_error)
        st.session_state.messages.append({"role": "assistant", "content": full_error})

    else:
        # 2. Ort und Zeit prüfen
        detected_city = detect_city_name(user_input, client, selected_model)
        day_offset, target_hour = parse_time_from_text(user_input)

        if detected_city:
            st.session_state.current_city = detected_city

        # 3. HARTE PRÜFUNG AUF FEHLENDE ORTSANGABE
        if not st.session_state.current_city:
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
            # 4. Wetterdaten abrufen und Outfit-Varianten generieren
            if detected_city or target_hour is not None or not st.session_state.current_weather:
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
                with st.spinner("Erstelle alle 3 Outfit-Varianten..."):
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
