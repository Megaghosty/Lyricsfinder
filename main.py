import asyncio
import re
import threading
import time
import requests
import json
import os
import customtkinter as ctk
from bs4 import BeautifulSoup
import translators as ts
from datetime import datetime, timezone

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus
)

ctk.set_appearance_mode("Dark")

BG_COLOR = "#09090b"
TEXT_INACTIVE = "#52525b"
TEXT_ACTIVE = "#ffffff"
TRAD_INACTIVE = "#3f3f46"
TRAD_ACTIVE = "#60a5fa"

CACHE_FILE = "lyrics_cache.json"
MAX_CACHE_SONGS = 50

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_cache(cache_data):
    try:
        if len(cache_data) > MAX_CACHE_SONGS:
            keys_to_remove = list(cache_data.keys())[:-MAX_CACHE_SONGS]
            for k in keys_to_remove:
                del cache_data[k]
                
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except:
        pass

def parse_lrc(lrc_text: str):
    pattern = re.compile(r"\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)")
    entries = []
    for line in lrc_text.splitlines():
        match = pattern.match(line.strip())
        if match:
            minutes, seconds, frac, text = match.groups()
            text = text.strip()
            if text:
                total_sec = int(minutes) * 60 + int(seconds) + float(f"0.{frac}")
                entries.append((total_sec, text))
    return sorted(entries, key=lambda x: x[0])

def clean_meta(text: str) -> str:
    if not text: return ""
    text = re.sub(r"[\(\[].*?(clip|video|audio|remaster|live|version|lyrics|official|hd).*?[\)\]]", "", text, flags=re.I)
    text = re.split(r"(?i)\s+feat\.|\s+ft\.", text)[0]
    return text.strip()

def fetch_genius_lyrics(title: str, artist: str):
    try:
        query = f"{artist} {title}".strip()
        search_url = f"https://genius.com/api/search/multi?per_page=1&q={requests.utils.quote(query)}"
        res = requests.get(search_url, timeout=5).json()
        
        song_url = None
        for sec in res.get("response", {}).get("sections", []):
            if sec.get("type") == "song" and sec.get("hits"):
                song_url = sec["hits"][0].get("result", {}).get("url")
                break
                
        if not song_url: return None
        
        html = requests.get(song_url, timeout=5).text
        soup = BeautifulSoup(html, "html.parser")
        lyrics_divs = soup.select('div[data-lyrics-container="true"]')
        
        if not lyrics_divs: return None
        
        lyrics = "\n".join([d.get_text(separator="\n").strip() for d in lyrics_divs])
        return re.sub(r'\n{3,}', '\n\n', lyrics)
    except:
        return None

class UltimateLyricsApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Karaoké Ultime")
        self.geometry("600x850")
        self.configure(fg_color=BG_COLOR)
        self.attributes("-topmost", True)
        self.minsize(380, 150)

        self.cache = load_cache()
        self.target_lang = "fr"

        self.current_title = ""
        self.current_artist = ""
        self.winrt_title_ref = ""
        self.manual_override = False

        self.lyrics_data = [] 
        self.line_widgets = []
        self.active_index = -1
        self.is_synced = False
        self.is_mini_mode = False
        
        self.sync_offset = 0.0

        self._build_ui()
        threading.Thread(target=self._media_loop, daemon=True).start()

    def _build_ui(self):
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=25, pady=(25, 5))

        top_bar = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        top_bar.pack(fill="x")
        self.lbl_source = ctk.CTkLabel(top_bar, text="Source: En attente", font=ctk.CTkFont(size=11), text_color="#3B8ED0")
        self.lbl_source.pack(side="left")
        self.btn_mini = ctk.CTkButton(top_bar, text="Mode Mini", width=70, height=24, font=ctk.CTkFont(size=11), command=self.toggle_mini)
        self.btn_mini.pack(side="right")

        title_bar = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_bar.pack(fill="x", pady=(10,0))
        self.lbl_title = ctk.CTkLabel(title_bar, text="Prêt à écouter", font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"), text_color="#ffffff", anchor="w")
        self.lbl_title.pack(side="left")
        self.btn_search = ctk.CTkButton(title_bar, text="🔍", width=30, height=30, fg_color="transparent", hover_color="#27272a", command=self.manual_search)
        self.btn_search.pack(side="left", padx=(10,0))

        self.lbl_artist = ctk.CTkLabel(self.header_frame, text="Lancez une musique...", font=ctk.CTkFont(family="Segoe UI", size=16), text_color="#a1a1aa", anchor="w")
        self.lbl_artist.pack(fill="x")
        
        # Barre de progression
        self.progress_bar = ctk.CTkProgressBar(self.header_frame, height=4, progress_color="#3B8ED0", fg_color="#27272a")
        self.progress_bar.pack(fill="x", pady=(8, 0))
        self.progress_bar.set(0)

        self.ctrl_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.ctrl_frame.pack(fill="x", padx=25, pady=(0, 15))
        
        self.lbl_status = ctk.CTkLabel(self.ctrl_frame, text="", font=ctk.CTkFont(size=11, slant="italic"), text_color="#3B8ED0")
        self.lbl_status.pack(side="left")

        self.combo_lang = ctk.CTkComboBox(self.ctrl_frame, values=["fr", "en", "es", "de", "it", "pt"], width=55, height=24, command=self.change_language)
        self.combo_lang.set("fr")
        self.combo_lang.pack(side="right", padx=(5, 0))

        self.switch_trad = ctk.CTkSwitch(self.ctrl_frame, text="Trad", width=50, font=ctk.CTkFont(size=12), command=self.toggle_translation)
        self.switch_trad.pack(side="right", padx=(5, 0))
        self.switch_trad.select()

        self.switch_sync = ctk.CTkSwitch(self.ctrl_frame, text="Sync", width=50, font=ctk.CTkFont(size=12), command=self.toggle_sync_mode)
        self.switch_sync.pack(side="right", padx=(10, 0))
        self.switch_sync.deselect()

        self.offset_frame = ctk.CTkFrame(self.ctrl_frame, fg_color="transparent")
        btn_minus = ctk.CTkButton(self.offset_frame, text="-", width=20, height=20, command=lambda: self.change_offset(-0.5))
        btn_minus.pack(side="left")
        self.lbl_offset = ctk.CTkLabel(self.offset_frame, text=" 0.0s ", font=ctk.CTkFont(size=11))
        self.lbl_offset.pack(side="left", padx=2)
        btn_plus = ctk.CTkButton(self.offset_frame, text="+", width=20, height=20, command=lambda: self.change_offset(0.5))
        btn_plus.pack(side="left")

        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=(0, 20))

        self.bind("<Double-Button-1>", self._on_double_click)

    def change_offset(self, amount):
        self.sync_offset += amount
        sign = "+" if self.sync_offset > 0 else ""
        self.lbl_offset.configure(text=f" {sign}{self.sync_offset:.1f}s ")

    def manual_search(self):
        dialog = ctk.CTkInputDialog(text="Entrez 'Artiste - Titre' :", title="Recherche manuelle")
        result = dialog.get_input()
        if result and "-" in result:
            parts = result.split("-", 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            self.manual_override = True
            self.current_title = title
            self.current_artist = artist
            self.sync_offset = 0.0
            self.change_offset(0)
            self._trigger_fetch(title, artist)

    def change_language(self, new_lang):
        self.target_lang = new_lang
        for i in range(len(self.lyrics_data)):
            sec, orig, _ = self.lyrics_data[i]
            self.lyrics_data[i] = (sec, orig, "")
            if i < len(self.line_widgets) and self.line_widgets[i]["trad_lbl"]:
                self.line_widgets[i]["trad_lbl"].configure(text="")
        
        orig_lines = [item[1] for item in self.lyrics_data]
        threading.Thread(target=self._background_translation, args=(orig_lines, self.current_title, self.current_artist, new_lang), daemon=True).start()

    def toggle_translation(self):
        show = self.switch_trad.get() == 1
        for item in self.line_widgets:
            if item["trad_lbl"] and item["trad_lbl"].cget("text").strip() not in ["", "↳", "↳ (Traduction indisponible)"]:
                if show: item["trad_lbl"].pack(fill="x", anchor="w", pady=(2, 0))
                else: item["trad_lbl"].pack_forget()

    def toggle_sync_mode(self):
        if self.switch_sync.get() == 0:
            self.offset_frame.pack_forget()
            for item in self.line_widgets:
                item["orig_lbl"].configure(text_color=TEXT_ACTIVE, font=ctk.CTkFont(size=18, weight="normal"))
                if item["trad_lbl"]: item["trad_lbl"].configure(text_color=TRAD_ACTIVE)
        else:
            if self.is_synced: self.offset_frame.pack(side="right", padx=(10, 10))
            self.active_index = -1
            for item in self.line_widgets:
                item["orig_lbl"].configure(text_color=TEXT_INACTIVE, font=ctk.CTkFont(size=20, weight="bold"))
                if item["trad_lbl"]: item["trad_lbl"].configure(text_color=TRAD_INACTIVE)

    def toggle_mini(self):
        self.is_mini_mode = not self.is_mini_mode
        if self.is_mini_mode:
            self.geometry("450x150")
            self.header_frame.pack_forget()
            self.ctrl_frame.pack_forget()
            self.overrideredirect(True)
        else:
            self.overrideredirect(False)
            self.geometry("600x850")
            self.header_frame.pack(fill="x", padx=25, pady=(25, 5), before=self.scroll_frame)
            self.ctrl_frame.pack(fill="x", padx=25, pady=(0, 15), before=self.scroll_frame)

    def _on_double_click(self, event):
        if self.is_mini_mode:
            self.toggle_mini()

    def rebuild_ui_lines(self):
        for child in self.scroll_frame.winfo_children():
            child.destroy()
        self.line_widgets.clear()
        self.active_index = -1

        show_trad = self.switch_trad.get() == 1
        is_sync = self.switch_sync.get() == 1

        ctk.CTkFrame(self.scroll_frame, fg_color="transparent", height=150).pack(fill="x")

        for _, orig, trad in self.lyrics_data:
            block = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            block.pack(fill="x", pady=10, padx=15)

            font_weight = "bold" if is_sync else "normal"
            font_size = 20 if is_sync else 18
            color = TEXT_INACTIVE if is_sync else TEXT_ACTIVE

            orig_lbl = ctk.CTkLabel(block, text=orig, font=ctk.CTkFont(family="Segoe UI", size=font_size, weight=font_weight), text_color=color, justify="left", anchor="w", wraplength=460)
            orig_lbl.pack(fill="x", anchor="w")

            trad_lbl = ctk.CTkLabel(block, text=f"↳ {trad}" if trad else "", font=ctk.CTkFont(family="Segoe UI", size=15, slant="italic"), text_color=TRAD_INACTIVE if is_sync else TRAD_ACTIVE, justify="left", anchor="w", wraplength=460)
            if show_trad and trad: trad_lbl.pack(fill="x", anchor="w", pady=(2, 0))

            self.line_widgets.append({"frame": block, "orig_lbl": orig_lbl, "trad_lbl": trad_lbl})

        ctk.CTkFrame(self.scroll_frame, fg_color="transparent", height=300).pack(fill="x")

    def highlight_line(self, index: int):
        if not self.is_synced or self.switch_sync.get() == 0: return
        if index == self.active_index or index >= len(self.line_widgets): return

        if 0 <= self.active_index < len(self.line_widgets):
            old = self.line_widgets[self.active_index]
            old["orig_lbl"].configure(text_color=TEXT_INACTIVE, font=ctk.CTkFont(size=20, weight="bold"))
            old["trad_lbl"].configure(text_color=TRAD_INACTIVE)

        self.active_index = index
        current = self.line_widgets[index]
        current["orig_lbl"].configure(text_color=TEXT_ACTIVE, font=ctk.CTkFont(size=22, weight="bold"))
        current["trad_lbl"].configure(text_color=TRAD_ACTIVE)

        total = len(self.line_widgets)
        if total > 0:
            target_pos = max(0.0, min(1.0, (index / total) - 0.35))
            self.scroll_frame._parent_canvas.yview_moveto(target_pos)

    def _background_translation(self, orig_lines, song_title, song_artist, lang):
        cache_key = f"{song_title}_{song_artist}_{lang}"
        
        if cache_key in self.cache:
            self.after(0, lambda: self.lbl_status.configure(text="Traduction du cache"))
            cached = self.cache[cache_key]
            for i, tr in enumerate(cached):
                if self.current_title != song_title or self.target_lang != lang: return
                if i < len(self.lyrics_data):
                    sec, orig, _ = self.lyrics_data[i]
                    self.lyrics_data[i] = (sec, orig, tr)
                    if i < len(self.line_widgets) and tr:
                        lbl = self.line_widgets[i]["trad_lbl"]
                        self.after(0, lambda l=lbl, t=tr: l.configure(text=f"↳ {t}"))
                        if self.switch_trad.get() == 1:
                            self.after(0, lambda l=lbl: l.pack(fill="x", anchor="w", pady=(2, 0)))
            return

        self.after(0, lambda: self.lbl_status.configure(text="Traduction en cascade..."))
        translated_for_cache = []
        
        for i, line in enumerate(orig_lines):
            if self.current_title != song_title or self.target_lang != lang: return
            
            tr = ""
            line_clean = line.strip()
            
            if line_clean:
                for attempt in range(3):
                    try:
                        tr = ts.translate_text(line_clean, translator='bing', from_language='auto', to_language=lang)
                        if tr: break
                    except Exception:
                        pass
                    time.sleep(1 + attempt) 
            
            if line_clean and not tr:
                tr = "(Traduction indisponible)"
                
            translated_for_cache.append(tr)

            if i < len(self.lyrics_data):
                sec, orig, _ = self.lyrics_data[i]
                self.lyrics_data[i] = (sec, orig, tr)
                
                if i < len(self.line_widgets) and tr:
                    lbl = self.line_widgets[i]["trad_lbl"]
                    self.after(0, lambda l=lbl, t=tr: l.configure(text=f"↳ {t}"))
                    if self.switch_trad.get() == 1:
                        self.after(0, lambda l=lbl: l.pack(fill="x", anchor="w", pady=(2, 0)))
            
            time.sleep(0.5)

        if self.current_title == song_title and self.target_lang == lang:
            self.cache[cache_key] = translated_for_cache
            save_cache(self.cache)
            self.after(0, lambda: self.lbl_status.configure(text="Traduction terminée"))

    def _trigger_fetch(self, t, a):
        self.after(0, lambda: self.lbl_title.configure(text=t))
        self.after(0, lambda: self.lbl_artist.configure(text=a))
        self.after(0, lambda: self.lbl_status.configure(text="Recherche Lrclib..."))
        self.after(0, lambda: self.progress_bar.set(0))

        synced, plain = None, None
        source = ""
        
        try:
            r = requests.get("https://lrclib.net/api/get", params={"track_name": t, "artist_name": a}, timeout=5)
            if r.status_code == 200:
                synced, plain = r.json().get("syncedLyrics"), r.json().get("plainLyrics")
                source = "Lrclib"
        except: pass

        if not synced and not plain:
            self.after(0, lambda: self.lbl_status.configure(text="Recherche Genius..."))
            plain = fetch_genius_lyrics(t, a)
            if plain: source = "Genius"

        self.lyrics_data = []

        if synced:
            self.is_synced = True
            self.after(0, lambda: self.lbl_source.configure(text=f"Paroles: {source} (Sync)"))
            parsed = parse_lrc(synced)
            orig_lines = [p[1] for p in parsed]
            for sec, orig in parsed: self.lyrics_data.append((sec, orig, ""))
            self.after(0, self.rebuild_ui_lines)
            if self.switch_sync.get() == 1:
                self.after(0, lambda: self.offset_frame.pack(side="right", padx=(10, 10)))
            threading.Thread(target=self._background_translation, args=(orig_lines, t, a, self.target_lang), daemon=True).start()
            
        elif plain:
            self.is_synced = False
            self.after(0, lambda: self.lbl_source.configure(text=f"Paroles: {source} (Texte)"))
            self.after(0, self.switch_sync.deselect) 
            self.after(0, self.offset_frame.pack_forget)
            orig_lines = [l.strip() for l in plain.splitlines() if l.strip()]
            for orig in orig_lines: self.lyrics_data.append((0, orig, ""))
            self.after(0, self.rebuild_ui_lines)
            threading.Thread(target=self._background_translation, args=(orig_lines, t, a, self.target_lang), daemon=True).start()
        else:
            self.is_synced = False
            self.after(0, self.offset_frame.pack_forget)
            self.after(0, lambda: self.lbl_source.configure(text="Paroles: Introuvables"))
            self.after(0, lambda: self.lbl_status.configure(text="Aucun résultat"))
            self.after(0, self.rebuild_ui_lines)

    def _media_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while True:
            t_winrt, a_winrt, pos_sec, app_name, duration = loop.run_until_complete(self._query_winrt())

            if t_winrt and t_winrt != self.winrt_title_ref:
                self.winrt_title_ref = t_winrt
                self.manual_override = False
                self.sync_offset = 0.0
                self.after(0, lambda: self.change_offset(0))

            if not self.manual_override:
                t, a = t_winrt, a_winrt
            else:
                t, a = self.current_title, self.current_artist

            if t and (t != self.current_title or a != self.current_artist or not self.lyrics_data):
                self.current_title = t
                self.current_artist = a
                self._trigger_fetch(t, a)
                
            # Mise à jour de la barre de progression
            if duration > 0:
                self.after(0, lambda p=pos_sec/duration: self.progress_bar.set(min(1.0, max(0.0, p))))
            else:
                self.after(0, lambda: self.progress_bar.set(0))

            if self.is_synced and pos_sec > 0 and self.lyrics_data and self.switch_sync.get() == 1:
                adjusted_pos = pos_sec + self.sync_offset
                target_idx = -1
                for idx, (sec, _, _) in enumerate(self.lyrics_data):
                    if adjusted_pos >= sec: target_idx = idx
                    else: break
                if target_idx != -1:
                    self.after(0, self.highlight_line, target_idx)

            time.sleep(0.15) # Taux de rafraichissement accéléré pour la fluidité

    async def _query_winrt(self):
        try:
            mgr = await MediaManager.request_async()
            session = mgr.get_current_session()
            if not session:
                sessions = mgr.get_sessions()
                for s in sessions:
                    info = s.get_playback_info()
                    if info and info.playback_status == PlaybackStatus.PLAYING:
                        session = s
                        break
                if not session and len(sessions) > 0: session = sessions[0]

            if not session: return None, None, 0.0, "Inconnue", 0.0

            props = await session.try_get_media_properties_async()
            if not props or not props.title: return None, None, 0.0, "Inconnue", 0.0

            # Extrapolation du timing pour une synchro parfaite
            timeline = session.get_timeline_properties()
            pos = 0.0
            duration = 0.0
            
            if timeline:
                if timeline.end_time:
                    duration = timeline.end_time.total_seconds()
                if timeline.position:
                    pos = timeline.position.total_seconds()
                    
                    info = session.get_playback_info()
                    if info and info.playback_status == PlaybackStatus.PLAYING:
                        try:
                            # On extrapole le temps exact écoulé depuis la dernière mise à jour de Windows
                            last_updated = timeline.last_updated_time
                            if last_updated.tzinfo is None:
                                last_updated = last_updated.replace(tzinfo=timezone.utc)
                            now = datetime.now(timezone.utc)
                            delta = (now - last_updated).total_seconds()
                            if delta > 0:
                                pos += delta
                        except:
                            pass
            
            app_id = session.source_app_user_model_id or "Inconnue"
            app_name = app_id.split("!")[-1].split(".exe")[0].capitalize()

            raw_title = props.title
            raw_artist = props.artist

            if " - " in raw_title:
                parts = raw_title.split(" - ", 1)
                raw_artist = parts[0]
                raw_title = parts[1]

            return clean_meta(raw_title), clean_meta(raw_artist), pos, app_name, duration
        except: return None, None, 0.0, "Erreur", 0.0

if __name__ == "__main__":
    app = UltimateLyricsApp()
    app.mainloop()
