"""
AI Video Asistani v2
---------------------
Iki mod:
1) Anlatimli Video: konu -> arastirma -> senaryo -> gorsel -> seslendirme -> video
2) Sessiz Komedi: orijinal karakterler -> sozsuz sahne/gag senaryosu -> ses efektli video
   (Tom&Jerry TARZINDA ilham alinir, ama TAMAMEN ORIJINAL karakterler uretilir; gercek
   Tom&Jerry gorselleri/isimleri kullanilmaz.)

Tamamen ucretsiz araclar:
- Arama: DuckDuckGo (ddgs)            - key yok
- Metin/senaryo: Pollinations text API - key yok
- Gorsel: Pollinations image API       - key yok   | Pexels API (opsiyonel, daha kaliteli stok)
- Seslendirme: edge-tts                - key yok, sinirsiz
- Ses efekti / muzik: Freesound API    - ucretsiz key (opsiyonel)
- Video birlestirme: moviepy + Pillow
"""

import os
import io
import re
import random
import asyncio
import textwrap
import tempfile
import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------------------
st.set_page_config(page_title="AI Video Asistani", layout="wide")

TEMP_DIR = tempfile.mkdtemp(prefix="ai_video_")

ORIENTATIONS = {
    "Yatay 16:9 (YouTube)": (1280, 720),
    "Dikey 9:16 (Reels / Shorts / TikTok)": (720, 1280),
}

LANGUAGES = {
    "Turkce": {"Kadin (Emel)": "tr-TR-EmelNeural", "Erkek (Ahmet)": "tr-TR-AhmetNeural"},
    "Ingilizce": {"Kadin (Jenny)": "en-US-JennyNeural", "Erkek (Guy)": "en-US-GuyNeural"},
    "Almanca": {"Kadin (Katja)": "de-DE-KatjaNeural", "Erkek (Conrad)": "de-DE-ConradNeural"},
}

STYLE_PRESETS = {
    "Genel Anlatim": "Notr, bilgilendirici ve akici bir uslupla yaz.",
    "Haber Tarzi": "Bir haber spikeri gibi resmi, net ve vurgulu bir dille yaz.",
    "Hikaye Anlatimi": "Sicak, merak uyandiran, hikaye anlatir gibi yaz; giris-gelisme-sonuc belirgin olsun.",
    "Egitim Videosu": "Sade, ogretici, adim adim aciklayan bir ogretmen uslubuyla yaz.",
}

PEXELS_API_KEY = st.secrets.get("PEXELS_API_KEY", "") if hasattr(st, "secrets") else ""
FREESOUND_API_KEY = st.secrets.get("FREESOUND_API_KEY", "") if hasattr(st, "secrets") else ""

DEFAULTS = {
    "scenes": [], "topic": "", "research": "", "characters": [],
    "silent_scenes": [], "mode": "Anlatimli Video",
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------------------------
# ORTAK YARDIMCI FONKSIYONLAR
# ---------------------------------------------------------------------------
def web_research(topic: str, max_results: int = 5) -> str:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    snippets = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(topic, region="tr-tr", max_results=max_results):
                snippets.append(f"- {r.get('title','')}: {r.get('body','')}")
    except Exception as e:
        return f"(Arastirma hatasi, genel bilgiyle devam edilecek: {e})"
    return "\n".join(snippets) if snippets else "(Sonuc bulunamadi, genel bilgiyle devam edilecek)"


def call_llm(prompt: str) -> str:
    """Pollinations text API - ucretsiz, key gerekmez."""
    try:
        resp = requests.post(
            "https://text.pollinations.ai/openai",
            json={"messages": [{"role": "user", "content": prompt}], "model": "openai"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        st.warning(f"Metin API hatasi: {e}")
        return ""


def generate_ai_image(prompt: str, w: int, h: int, seed: int = None):
    safe_prompt = requests.utils.quote(prompt)[:400]
    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width={w}&height={h}&nologo=true"
    if seed is not None:
        url += f"&seed={seed}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def search_pexels_image(query: str):
    if not PEXELS_API_KEY:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            timeout=15,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if photos:
            img_resp = requests.get(photos[0]["src"]["large"], timeout=15)
            return Image.open(io.BytesIO(img_resp.content)).convert("RGB")
    except Exception:
        return None
    return None


def get_scene_image(query: str, w: int, h: int):
    img = search_pexels_image(query)
    source = "Pexels (stok gorsel)"
    if img is None:
        img = generate_ai_image(query, w, h)
        source = "Yapay zeka ile uretildi"
    return img.resize((w, h)), source


async def _tts_async(text, voice, out_path):
    import edge_tts
    await edge_tts.Communicate(text, voice).save(out_path)


def text_to_speech(text, voice, out_path):
    asyncio.run(_tts_async(text, voice, out_path))
    return out_path


def search_freesound(query: str, kind: str = "sfx"):
    """kind: 'sfx' kisa efekt, 'music' arka plan muzigi. Key yoksa None doner."""
    if not FREESOUND_API_KEY:
        return None
    dur_filter = "duration:[0.3 TO 8]" if kind == "sfx" else "duration:[20 TO 180]"
    try:
        r = requests.get(
            "https://freesound.org/apiv2/search/text/",
            params={
                "query": query, "token": FREESOUND_API_KEY,
                "fields": "id,previews,license", "filter": dur_filter, "page_size": 1,
            },
            timeout=20,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return None
        preview_url = results[0]["previews"]["preview-hq-mp3"]
        audio_bytes = requests.get(preview_url, timeout=20).content
        out_path = os.path.join(TEMP_DIR, f"sfx_{abs(hash(query))}_{kind}.mp3")
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        return out_path
    except Exception:
        return None


def add_caption(img: Image.Image, text: str, w: int, h: int, highlight: bool = False) -> Image.Image:
    img = img.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    try:
        size = 30 if w < h else 36
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        font = ImageFont.load_default()

    wrap_width = 30 if w < h else 45
    wrapped = textwrap.fill(text, width=wrap_width)
    lines = wrapped.split("\n")
    line_h = font.size + 8
    box_h = line_h * len(lines) + 40
    fill_color = (0, 90, 60, 190) if highlight else (0, 0, 0, 160)
    draw.rectangle([0, h - box_h, w, h], fill=fill_color)
    y = h - box_h + 20
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) / 2, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h
    return img


def chunk_text_by_words(text: str, chunk_size: int = 4):
    words = text.split()
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]


# ---------------------------------------------------------------------------
# MOD 1: ANLATIMLI VIDEO
# ---------------------------------------------------------------------------
def generate_script(topic, research, n_scenes, style_instruction):
    prompt = f"""Sen profesyonel bir video senaristisin. {style_instruction}
Asagidaki konu ve arastirma notlarini kullanarak Turkce, {n_scenes} kisa sahneden
olusan bir video anlatim metni yaz. Her sahneyi yeni satirda, basinda etiket olmadan yaz.
Her sahne 1-2 cumle olsun.

KONU: {topic}
ARASTIRMA NOTLARI:
{research}

Sadece sahne metinlerini alt alta yaz, baska aciklama ekleme:"""
    text = call_llm(prompt)
    if not text:
        text = f"{topic} hakkinda merak edilenler.\nBu konu giderek onem kazaniyor.\nDetaylara birlikte bakalim.\nSonuc olarak hayatimizi etkiliyor."
    return [l.strip(" -\t") for l in text.split("\n") if l.strip()]


def render_narrated_video(scenes, voice, w, h, use_transitions, use_music, use_karaoke, progress_cb=None):
    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeAudioClip, afx

    clips = []
    for i, scene in enumerate(scenes):
        if progress_cb:
            progress_cb(i, len(scenes), "Seslendiriliyor...")
        audio_path = os.path.join(TEMP_DIR, f"scene_{i}.mp3")
        text_to_speech(scene["text"], voice, audio_path)
        audio_clip = AudioFileClip(audio_path)
        duration = max(audio_clip.duration, 2.0)

        if use_karaoke:
            chunks = chunk_text_by_words(scene["text"], 4) or [scene["text"]]
            per = duration / len(chunks)
            sub_clips = []
            for j, ch in enumerate(chunks):
                captioned = add_caption(scene["image"], ch, w, h, highlight=True)
                p = os.path.join(TEMP_DIR, f"scene_{i}_{j}.png")
                captioned.save(p)
                sub_clips.append(ImageClip(p).set_duration(per))
            from moviepy.editor import concatenate_videoclips as cc
            visual = cc(sub_clips, method="compose").set_audio(audio_clip)
        else:
            captioned = add_caption(scene["image"], scene["text"], w, h)
            p = os.path.join(TEMP_DIR, f"scene_{i}.png")
            captioned.save(p)
            visual = ImageClip(p).set_duration(duration).set_audio(audio_clip)

        if use_transitions and i > 0:
            visual = visual.crossfadein(0.5)
        clips.append(visual)

    if progress_cb:
        progress_cb(len(scenes), len(scenes), "Video birlestiriliyor...")

    pad = -0.5 if use_transitions else 0
    final = concatenate_videoclips(clips, method="compose", padding=pad)

    if use_music:
        topic_mood = st.session_state.topic or "cinematic background"
        music_path = search_freesound(topic_mood, "music")
        if music_path:
            music = AudioFileClip(music_path).fx(afx.audio_loop, duration=final.duration).volumex(0.15)
            final = final.set_audio(CompositeAudioClip([final.audio, music]))

    out_path = os.path.join(TEMP_DIR, "final_video.mp4")
    final.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac", logger=None)
    return out_path


# ---------------------------------------------------------------------------
# MOD 2: SESSIZ KOMEDI (ozgun karakterler, sozsuz, ses efektli)
# ---------------------------------------------------------------------------
def generate_characters(brief: str, n: int = 2):
    prompt = f"""Sessiz slapstik komedi tarzinda (klasik kedi-fare kovalamaca esprisi gibi
ama TAMAMEN OZGUN, telifsiz) {n} adet ozgun karakter tasarla. Gercek/ unlu hicbir
cizgi film karakterinin ismini veya ozel tasarimini kullanma, tamamen yeni bir tasarim uret.

Kullanicinin istegi: {brief}

Her karakter icin tek satirda su formatta yaz (baska aciklama ekleme):
ISIM | GORUNUM ACIKLAMASI (renk, tur, kiyafet, karakter ozellikleri - detayli, gorsel uretim icin)"""
    text = call_llm(prompt)
    characters = []
    for line in text.split("\n"):
        if "|" in line:
            name, desc = line.split("|", 1)
            characters.append({
                "name": name.strip(" -"),
                "description": desc.strip(),
                "seed": random.randint(1, 999999),
            })
    if not characters:
        characters = [
            {"name": "Pati", "description": "kucuk turuncu tuylu, iri gozlu, yaramaz bir kedi", "seed": random.randint(1, 999999)},
            {"name": "Fisik", "description": "gri, kucuk, kurnaz bakisli bir fare, kirmizi minik sapka takiyor", "seed": random.randint(1, 999999)},
        ]
    return characters


def build_character_context(characters):
    return "; ".join([f"{c['name']}: {c['description']}" for c in characters])


def generate_silent_scenes(brief, characters, n_scenes):
    char_ctx = build_character_context(characters)
    prompt = f"""Sessiz slapstik komedi (konusma yok, sadece gorsel aksiyon ve ses efektleri) icin
{n_scenes} adet sahne/gag yaz. Karakterler: {char_ctx}
Tema/konu: {brief}

Her sahneyi tek satirda su formatta yaz (baska aciklama ekleme):
GORSEL AKSIYON ACIKLAMASI | SES EFEKTI ANAHTAR KELIMESI (orn: boing, crash, whistle, splash, honk)

Sahneler birbirini takip eden komik bir olay orgusu olustursun, giris-gelisme-doruk-sonuc olsun."""
    text = call_llm(prompt)
    scenes = []
    for line in text.split("\n"):
        if "|" in line:
            visual, sfx = line.split("|", 1)
            scenes.append({
                "visual": visual.strip(" -"),
                "sfx": sfx.strip(),
                "duration": 4,
            })
    return scenes


def render_silent_video(scenes, characters, w, h, use_transitions, use_music, progress_cb=None):
    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeAudioClip, afx

    char_ctx = build_character_context(characters)
    base_seed = characters[0]["seed"] if characters else random.randint(1, 999999)

    clips = []
    for i, scene in enumerate(scenes):
        if progress_cb:
            progress_cb(i, len(scenes), "Sahne gorseli uretiliyor...")
        full_prompt = f"{char_ctx}. Sahne: {scene['visual']}. Sessiz komedi cizgi film stili, canli renkler."
        img = scene.get("image")
        if img is None:
            img = generate_ai_image(full_prompt, w, h, seed=base_seed)
            img = img.resize((w, h))
            scene["image"] = img

        duration = scene.get("duration", 4)
        img_path = os.path.join(TEMP_DIR, f"silent_{i}.png")
        img.save(img_path)
        clip = ImageClip(img_path).set_duration(duration)

        sfx_path = search_freesound(scene.get("sfx", ""), "sfx")
        if sfx_path:
            clip = clip.set_audio(AudioFileClip(sfx_path).set_start(0))

        if use_transitions and i > 0:
            clip = clip.crossfadein(0.4)
        clips.append(clip)

    if progress_cb:
        progress_cb(len(scenes), len(scenes), "Video birlestiriliyor...")

    pad = -0.4 if use_transitions else 0
    final = concatenate_videoclips(clips, method="compose", padding=pad)

    if use_music:
        music_path = search_freesound("comedy cartoon background", "music")
        if music_path:
            music = AudioFileClip(music_path).fx(afx.audio_loop, duration=final.duration).volumex(0.25)
            existing = final.audio
            final = final.set_audio(CompositeAudioClip([a for a in [existing, music] if a is not None]))

    out_path = os.path.join(TEMP_DIR, "final_silent_video.mp4")
    final.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac", logger=None)
    return out_path


# ---------------------------------------------------------------------------
# ARAYUZ
# ---------------------------------------------------------------------------
st.title("AI Video Asistani")
st.caption("Konu -> arastirma -> senaryo -> gorsel -> seslendirme -> video. Ya da sozsuz, ozgun karakterli komedi videolari.")

with st.sidebar:
    st.header("Ayarlar")
    st.session_state.mode = st.radio("Video Turu", ["Anlatimli Video", "Sessiz Komedi"])
    orientation_label = st.selectbox("Format", list(ORIENTATIONS.keys()))
    W, H = ORIENTATIONS[orientation_label]
    use_transitions = st.checkbox("Sahne gecis efektleri (crossfade)", value=True)
    use_music = st.checkbox("Arka plan muzigi ekle", value=bool(FREESOUND_API_KEY))
    if not FREESOUND_API_KEY:
        st.caption("Muzik/ses efekti icin ucretsiz Freesound API key gerekir (freesound.org/apiv2).")

    if st.session_state.mode == "Anlatimli Video":
        lang_label = st.selectbox("Dil", list(LANGUAGES.keys()))
        voice_label = st.selectbox("Seslendirme", list(LANGUAGES[lang_label].keys()))
        voice = LANGUAGES[lang_label][voice_label]
        style_label = st.selectbox("Uslup", list(STYLE_PRESETS.keys()))
        use_karaoke = st.checkbox("Karaoke tarzi vurgulu altyazi", value=False)
        n_scenes = st.slider("Sahne sayisi", 3, 12, 6)

    if PEXELS_API_KEY:
        st.success("Pexels bagli")
    else:
        st.info("Pexels key yok -> gorseller AI ile uretilecek")

# ============================== MOD 1 ==============================
if st.session_state.mode == "Anlatimli Video":
    topic = st.text_input("Video konusu", value=st.session_state.topic, placeholder="Orn: Uzayda yasamin gelecegi")

    if st.button("Taslagi Olustur", type="primary") and topic.strip():
        st.session_state.topic = topic
        with st.spinner("Web'de arastiriliyor..."):
            st.session_state.research = web_research(topic)
        with st.spinner("Senaryo yaziliyor..."):
            scene_texts = generate_script(topic, st.session_state.research, n_scenes, STYLE_PRESETS[style_label])

        scenes = []
        progress = st.progress(0, text="Gorseller hazirlaniyor...")
        for i, text in enumerate(scene_texts):
            img, source = get_scene_image(text[:80], W, H)
            scenes.append({"text": text, "image": img, "image_source": source})
            progress.progress((i + 1) / len(scene_texts), text=f"Sahne {i+1}/{len(scene_texts)}")
        progress.empty()
        st.session_state.scenes = scenes
        st.success(f"{len(scenes)} sahnelik taslak hazir!")

    with st.expander("Arastirma notlari"):
        st.write(st.session_state.research or "Henuz arastirma yapilmadi.")

    if st.session_state.scenes:
        st.subheader("Sahneleri Duzenle")
        for i, scene in enumerate(st.session_state.scenes):
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.image(scene["image"], caption=scene.get("image_source", ""), use_container_width=True)
                    if st.button("Gorseli yenile", key=f"regen_img_{i}"):
                        with st.spinner("Yeni gorsel uretiliyor..."):
                            new_img = generate_ai_image(scene["text"][:80], W, H).resize((W, H))
                            st.session_state.scenes[i]["image"] = new_img
                            st.session_state.scenes[i]["image_source"] = "AI ile uretildi (yenilendi)"
                        st.rerun()
                with c2:
                    st.session_state.scenes[i]["text"] = st.text_area(
                        f"Sahne {i+1} metni", value=scene["text"], key=f"text_{i}", height=100)
                    if st.button("Bu sahneyi sil", key=f"del_{i}"):
                        st.session_state.scenes.pop(i)
                        st.rerun()

        st.divider()
        if st.button("Videoyu Olustur", type="primary"):
            progress = st.progress(0, text="Basliyor...")
            def cb(i, total, msg):
                progress.progress(min((i + 1) / max(total, 1), 1.0), text=f"{msg} ({i+1}/{total})")
            with st.spinner("Video render ediliyor..."):
                out_path = render_narrated_video(
                    st.session_state.scenes, voice, W, H,
                    use_transitions, use_music, use_karaoke, progress_cb=cb)
            progress.empty()
            st.success("Video hazir!")
            st.video(out_path)
            with open(out_path, "rb") as f:
                st.download_button("Videoyu Indir", f, file_name="video.mp4", mime="video/mp4")

# ============================== MOD 2 ==============================
else:
    st.info("Bu mod, Tom&Jerry'nin KENDISINI degil, o TARZDA (sozsuz, kovalamaca, ses efektli) "
            "TAMAMEN OZGUN karakterler ve sahneler uretir. Cikti hareketli bir animasyon degil, "
            "gorsel + ses efektleriyle ilerleyen bir 'motion comic' videodur.")

    brief = st.text_input("Ne tur bir sozsuz komedi istiyorsun?",
                           placeholder="Orn: Bir kedi ile farenin mutfaktaki kovalamacasi")

    if st.button("Karakterleri Olustur", type="primary") and brief.strip():
        with st.spinner("Ozgun karakterler tasarlaniyor..."):
            st.session_state.characters = generate_characters(brief, n=2)

    if st.session_state.characters:
        st.subheader("Karakterler")
        cols = st.columns(len(st.session_state.characters))
        for idx, ch in enumerate(st.session_state.characters):
            with cols[idx]:
                if "ref_image" not in ch:
                    with st.spinner(f"{ch['name']} icin referans gorsel uretiliyor..."):
                        ch["ref_image"] = generate_ai_image(
                            f"karakter referans sayfasi, {ch['description']}, cizgi film stili, beyaz arka plan",
                            512, 512, seed=ch["seed"])
                st.image(ch["ref_image"], caption=ch["name"], use_container_width=True)
                st.caption(ch["description"])

        n_silent_scenes = st.slider("Sahne (gag) sayisi", 4, 30, 10)
        if st.button("Sahneleri/Gagleri Yaz"):
            with st.spinner("Sozsuz sahne senaryosu yaziliyor..."):
                st.session_state.silent_scenes = generate_silent_scenes(
                    brief, st.session_state.characters, n_silent_scenes)

    if st.session_state.silent_scenes:
        st.subheader("Sahneleri Duzenle")
        for i, scene in enumerate(st.session_state.silent_scenes):
            with st.container(border=True):
                scene["visual"] = st.text_area(f"Sahne {i+1} - gorsel aksiyon", value=scene["visual"], key=f"sv_{i}")
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    scene["sfx"] = st.text_input("Ses efekti", value=scene["sfx"], key=f"sfx_{i}")
                with col2:
                    scene["duration"] = st.number_input("Sure (sn)", min_value=1, max_value=15,
                                                          value=scene.get("duration", 4), key=f"dur_{i}")
                with col3:
                    if st.button("Sahneyi sil", key=f"del_silent_{i}"):
                        st.session_state.silent_scenes.pop(i)
                        st.rerun()

        st.divider()
        if st.button("Sozsuz Videoyu Olustur", type="primary"):
            progress = st.progress(0, text="Basliyor...")
            def cb2(i, total, msg):
                progress.progress(min((i + 1) / max(total, 1), 1.0), text=f"{msg} ({i+1}/{total})")
            with st.spinner("Video render ediliyor..."):
                out_path = render_silent_video(
                    st.session_state.silent_scenes, st.session_state.characters, W, H,
                    use_transitions, use_music, progress_cb=cb2)
            progress.empty()
            st.success("Video hazir!")
            st.video(out_path)
            with open(out_path, "rb") as f:
                st.download_button("Videoyu Indir", f, file_name="sessiz_komedi.mp4", mime="video/mp4")
