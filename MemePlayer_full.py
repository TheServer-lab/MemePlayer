"""
MemePlayer_full.py

Features added on top of your SFX-enabled player:
- Simple playlist system (JSON): create/select/add/remove playlists
- Live search bar (filters file list as you type)
- Countdown timer display (text + progress bar)
- Background music player (assets/bgm/) with independent volume, play/pause/next/prev
- Global hotkeys (Ctrl+Alt+→ / ← / Space) via `keyboard` if available, otherwise fallback app-level keys
- Video loop toggle (checkbox) - when enabled, videos loop until skipped
- SFX (assets/sfx/) support including mp3

Dependencies:
    pip install pillow python-vlc keyboard

Make sure VLC (matching your Python bitness) is installed for video playback.
Place SFX files in assets/sfx/ and BGM tracks in assets/bgm/
"""

import os
import sys
import json
import random
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

# Optional global hotkeys library
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except Exception:
    KEYBOARD_AVAILABLE = False

# Trying vlc
try:
    import vlc
    VLC_AVAILABLE = True
except Exception:
    VLC_AVAILABLE = False

# Windows winsound fallback for .wav sfx
try:
    import winsound
    WINSOUND_AVAILABLE = True
except Exception:
    WINSOUND_AVAILABLE = False

# File type constants
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
VIDEO_EXTS = ('.mp4', '.mov', '.m4v', '.webm')
PLAYABLE_EXTS = IMAGE_EXTS + VIDEO_EXTS

# SFX formats (supports mp3)
SFX_EXTS = ('.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac')
BGM_EXTS = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac')

# Assets folders
BASE_DIR = os.path.dirname(__file__)
ASSETS_SFX_DIR = os.path.join(BASE_DIR, 'assets', 'sfx')
ASSETS_BGM_DIR = os.path.join(BASE_DIR, 'assets', 'bgm')
PLAYLISTS_FILE = os.path.join(BASE_DIR, 'playlists.json')

# Helper: ensure asset dirs exist
os.makedirs(ASSETS_SFX_DIR, exist_ok=True)
os.makedirs(ASSETS_BGM_DIR, exist_ok=True)


class BackgroundMusicPlayer:
    """Simple BGM player using VLC if available, otherwise does nothing.
    Plays tracks from a provided list in order, looping the BGM playlist.
    """

    def __init__(self):
        self.bgm_files = []
        self.index = 0
        self.playing = False
        self._thread = None
        self._stop_event = threading.Event()
        self.volume = 50
        self.vlc_instance = None
        self.player = None
        if VLC_AVAILABLE:
            try:
                self.vlc_instance = vlc.Instance()
                self.player = self.vlc_instance.media_player_new()
            except Exception:
                self.vlc_instance = None
                self.player = None

    def load_folder(self, folder=ASSETS_BGM_DIR):
        fl = []
        try:
            for f in os.listdir(folder):
                if f.lower().endswith(BGM_EXTS):
                    fl.append(os.path.join(folder, f))
            fl.sort()
        except Exception:
            fl = []
        self.bgm_files = fl
        self.index = 0

    def set_volume(self, vol):
        self.volume = max(0, min(100, int(vol)))
        if self.player:
            try:
                self.player.audio_set_volume(self.volume)
            except Exception:
                pass

    def play(self):
        if not self.bgm_files:
            return
        if not VLC_AVAILABLE or not self.player:
            return
        self.playing = True
        self._stop_event.clear()
        # start playback thread
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._play_loop, daemon=True)
            self._thread.start()

    def pause(self):
        if self.player:
            try:
                self.player.pause()
                self.playing = False
            except Exception:
                pass

    def stop(self):
        self._stop_event.set()
        self.playing = False
        if self.player:
            try:
                self.player.stop()
            except Exception:
                pass

    def next(self):
        if not self.bgm_files:
            return
        self.index = (self.index + 1) % len(self.bgm_files)
        self._play_current()

    def prev(self):
        if not self.bgm_files:
            return
        self.index = (self.index - 1) % len(self.bgm_files)
        self._play_current()

    def _play_current(self):
        if not VLC_AVAILABLE or not self.player or not self.bgm_files:
            return
        f = self.bgm_files[self.index]
        try:
            media = self.vlc_instance.media_new(f)
            self.player.set_media(media)
            self.player.audio_set_volume(self.volume)
            self.player.play()
        except Exception:
            pass

    def _play_loop(self):
        while not self._stop_event.is_set() and self.bgm_files:
            self._play_current()
            # wait for track to end or stop_event
            t_sleep = 0.5
            elapsed = 0.0
            # try to get length
            length_ms = None
            try:
                # wait briefly for length to be available
                time.sleep(0.2)
                length_ms = self.player.get_length()
            except Exception:
                length_ms = None
            if length_ms and length_ms > 0:
                total = (length_ms / 1000.0)
                waited = 0.0
                while waited < total and not self._stop_event.is_set():
                    time.sleep(t_sleep)
                    waited += t_sleep
            else:
                # fallback: wait a fixed 30s per track if length unknown
                waited = 0.0
                while waited < 30 and not self._stop_event.is_set():
                    time.sleep(t_sleep)
                    waited += t_sleep
            if self._stop_event.is_set():
                break
            # next track
            self.index = (self.index + 1) % len(self.bgm_files)
        # cleanup
        self.playing = False


class MemePlayer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('MemePlayer Full')
        self.geometry('980x650')
        self.protocol('WM_DELETE_WINDOW', self.on_close)

        # playback state
        self.folder = None
        self.files = []
        self.filtered_files = []  # after search filter
        self.current_index = None
        self.is_running = False
        self.is_paused = False
        self.shuffle = tk.BooleanVar(value=True)
        self.interval_seconds = tk.IntVar(value=30)
        self.loop_videos = tk.BooleanVar(value=False)

        # VLC players
        self.vlc_instance = None
        self.vlc_player = None

        # SFX
        self.sfx_files = []
        self.enable_image_sfx = tk.BooleanVar(value=True)
        self.sfx_volume = tk.IntVar(value=80)

        # BGM player
        self.bgm = BackgroundMusicPlayer()
        self.bgm_volume = tk.IntVar(value=50)

        # Playlists
        self.playlists = {}  # name -> list of file paths
        self.current_playlist = tk.StringVar(value='(None)')

        # UI timer/progress
        self._after_id = None
        self._video_stop_timer = None
        self._countdown_seconds_left = 0

        # hotkey registration flag
        self.hotkeys_registered = False

        # build UI
        self.setup_ui()

        # load SFX/BGM/Playlists
        self._load_sfx_files()
        self._load_bgm_files()
        self._load_playlists()

        # setup global hotkeys if possible
        self._setup_hotkeys()

    # ---------------- UI ----------------
    def setup_ui(self):
        # Top row: folder/select, playlist controls, search
        top_frame = ttk.Frame(self)
        top_frame.pack(side='top', fill='x', padx=8, pady=6)

        ttk.Button(top_frame, text='Select Folder', command=self.select_folder).pack(side='left')
        ttk.Button(top_frame, text='Start', command=self.start).pack(side='left', padx=6)
        ttk.Button(top_frame, text='Stop', command=self.stop).pack(side='left')
        ttk.Button(top_frame, text='Prev', command=self.play_prev).pack(side='left', padx=6)
        ttk.Button(top_frame, text='Next', command=self.play_next).pack(side='left')

        ttk.Checkbutton(top_frame, text='Shuffle', variable=self.shuffle).pack(side='left', padx=8)

        ttk.Label(top_frame, text='Interval (s):').pack(side='left')
        ttk.Spinbox(top_frame, from_=5, to=3600, textvariable=self.interval_seconds, width=6).pack(side='left',
                                                                                                    padx=(2, 12))

        # Playlist UI (simple JSON-based)
        pl_frame = ttk.Frame(self)
        pl_frame.pack(side='top', fill='x', padx=8, pady=(0, 6))

        ttk.Label(pl_frame, text='Playlist:').pack(side='left')
        self.playlist_combo = ttk.Combobox(pl_frame, textvariable=self.current_playlist, state='readonly', width=24)
        self.playlist_combo.pack(side='left', padx=(4, 6))
        self.playlist_combo.bind('<<ComboboxSelected>>', lambda e: self._apply_selected_playlist())

        ttk.Button(pl_frame, text='New', command=self._playlist_new).pack(side='left', padx=2)
        ttk.Button(pl_frame, text='Add Selected to Playlist', command=self._playlist_add_selected).pack(side='left',
                                                                                                      padx=2)
        ttk.Button(pl_frame, text='Remove Playlist', command=self._playlist_remove).pack(side='left', padx=2)

        # Search bar (live)
        ttk.Label(pl_frame, text='Search:').pack(side='left', padx=(12, 4))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(pl_frame, textvariable=self.search_var, width=30)
        search_entry.pack(side='left')
        search_entry.bind('<KeyRelease>', lambda e: self._apply_search_filter())

        # Timer + progress bar area
        timer_frame = ttk.Frame(self)
        timer_frame.pack(side='top', fill='x', padx=8, pady=(0, 6))
        self.timer_label = ttk.Label(timer_frame, text='Next meme in: --')
        self.timer_label.pack(side='left', padx=(0, 12))
        self.progress = ttk.Progressbar(timer_frame, orient='horizontal', length=300, mode='determinate')
        self.progress.pack(side='left')

        # SFX and BGM controls
        sfx_frame = ttk.Frame(self)
        sfx_frame.pack(side='top', fill='x', padx=8, pady=(0, 6))
        ttk.Checkbutton(sfx_frame, text='Play reaction sound for images', variable=self.enable_image_sfx).pack(side='left',
                                                                                                                padx=(0,
                                                                                                                       12))
        ttk.Label(sfx_frame, text='SFX Volume:').pack(side='left')
        ttk.Scale(sfx_frame, from_=0, to=100, orient='horizontal', variable=self.sfx_volume,
                  command=self._on_sfx_volume_change, length=120).pack(side='left', padx=6)
        ttk.Button(sfx_frame, text='Open SFX Folder', command=self.open_sfx_folder).pack(side='left', padx=6)
        ttk.Button(sfx_frame, text='Reload SFX', command=self._load_sfx_files).pack(side='left', padx=6)

        # BGM controls
        bgm_frame = ttk.Frame(self)
        bgm_frame.pack(side='top', fill='x', padx=8, pady=(0, 6))
        ttk.Label(bgm_frame, text='BGM:').pack(side='left')
        ttk.Button(bgm_frame, text='Play BGM', command=self._bgm_play).pack(side='left', padx=4)
        ttk.Button(bgm_frame, text='Pause BGM', command=self._bgm_pause).pack(side='left', padx=2)
        ttk.Button(bgm_frame, text='Prev BGM', command=self._bgm_prev).pack(side='left', padx=2)
        ttk.Button(bgm_frame, text='Next BGM', command=self._bgm_next).pack(side='left', padx=2)
        ttk.Label(bgm_frame, text='BGM Volume:').pack(side='left', padx=(12, 2))
        ttk.Scale(bgm_frame, from_=0, to=100, orient='horizontal', variable=self.bgm_volume,
                  command=self._on_bgm_volume_change, length=120).pack(side='left', padx=6)
        ttk.Button(bgm_frame, text='Open BGM Folder', command=self.open_bgm_folder).pack(side='left', padx=6)

        # Video loop toggle
        ttk.Checkbutton(bgm_frame, text='Loop videos until skipped', variable=self.loop_videos).pack(side='left', padx=12)

        # Main area: left file list, right display
        main_frame = ttk.Frame(self)
        main_frame.pack(fill='both', expand=True, padx=8, pady=6)

        left = ttk.Frame(main_frame, width=300)
        left.pack(side='left', fill='y', padx=(0, 6))

        ttk.Label(left, text='Files:').pack(anchor='w')
        self.listbox = tk.Listbox(left, width=45, selectmode='extended')
        self.listbox.pack(fill='both', expand=True)
        self.listbox.bind('<Double-Button-1>', lambda e: self._on_list_double())

        # Right display
        right = ttk.Frame(main_frame)
        right.pack(side='left', fill='both', expand=True)

        self.image_panel = tk.Label(right, bg='black')
        self.image_panel.pack(fill='both', expand=True)

        self.video_panel = ttk.Frame(right)
        self.video_panel.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.video_panel.lower(self.image_panel)

        # Bottom status bar
        self.status_var = tk.StringVar(value='No folder selected')
        ttk.Label(self, textvariable=self.status_var, anchor='w').pack(side='bottom', fill='x')

        # App-level key bindings as fallback if keyboard module missing
        self.bind('<Control-Alt-Right>', lambda e: self.play_next())
        self.bind('<Control-Alt-Left>', lambda e: self.play_prev())
        self.bind('<Control-Alt-space>', lambda e: self.toggle_pause())

    # ---------------- SFX/BGM/Playlists loader ----------------
    def _load_sfx_files(self):
        self.sfx_files = []
        try:
            for fn in os.listdir(ASSETS_SFX_DIR):
                if fn.lower().endswith(SFX_EXTS):
                    self.sfx_files.append(os.path.join(ASSETS_SFX_DIR, fn))
            self.sfx_files.sort()
            self._safe_status_set(f'Loaded {len(self.sfx_files)} SFX files.')
        except Exception:
            self.sfx_files = []
            self._safe_status_set('Failed to load SFX files.')

    def open_sfx_folder(self):
        """
        Open the SFX folder in the system file explorer and reload SFX files shortly after.
        This method fixes the earlier missing-method error when the UI tried to call it.
        """
        try:
            if sys.platform.startswith('win'):
                os.startfile(ASSETS_SFX_DIR)
            elif sys.platform.startswith('darwin'):
                os.system(f'open "{ASSETS_SFX_DIR}"')
            else:
                os.system(f'xdg-open "{ASSETS_SFX_DIR}"')
            # reload with a short delay so newly added files appear
            self.after(600, self._load_sfx_files)
        except Exception as e:
            messagebox.showinfo('Open folder', f'Open SFX folder: {ASSETS_SFX_DIR}\n\nError: {e}')

    def _load_bgm_files(self):
        self.bgm.load_folder(ASSETS_BGM_DIR)
        # set bgm volume
        self.bgm.set_volume(self.bgm_volume.get())
        self._safe_status_set(f'Loaded {len(self.bgm.bgm_files)} BGM tracks.')

    def _load_playlists(self):
        self.playlists = {}
        try:
            if os.path.exists(PLAYLISTS_FILE):
                with open(PLAYLISTS_FILE, 'r', encoding='utf-8') as f:
                    self.playlists = json.load(f)
            else:
                self.playlists = {}
        except Exception:
            self.playlists = {}
        self._refresh_playlist_combo()

    def _save_playlists(self):
        try:
            with open(PLAYLISTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.playlists, f, indent=2)
        except Exception:
            pass
        self._refresh_playlist_combo()

    def _refresh_playlist_combo(self):
        names = sorted(self.playlists.keys())
        if not names:
            names = ['(None)']
            self.current_playlist.set('(None)')
        self.playlist_combo['values'] = names
        if self.current_playlist.get() not in names:
            self.current_playlist.set(names[0])

    # ---------------- Playlist UI actions ----------------
    def _playlist_new(self):
        name = simple_input_dialog(self, 'New playlist', 'Enter playlist name:')
        if not name:
            return
        if name in self.playlists:
            messagebox.showinfo('Playlist exists', 'A playlist with that name already exists.')
            return
        self.playlists[name] = []
        self._save_playlists()
        self._refresh_playlist_combo()

    def _playlist_add_selected(self):
        name = self.current_playlist.get()
        if not name or name == '(None)':
            messagebox.showinfo('No playlist', 'Please select or create a playlist first.')
            return
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo('No selection', 'Select files in the list to add.')
            return
        for i in sel:
            p = self.filtered_files[i]
            if p not in self.playlists[name]:
                self.playlists[name].append(p)
        self._save_playlists()
        self._safe_status_set(f'Added {len(sel)} files to playlist "{name}".')

    def _playlist_remove(self):
        name = self.current_playlist.get()
        if not name or name == '(None)':
            return
        if messagebox.askyesno('Remove playlist', f'Remove playlist "{name}"?'):
            self.playlists.pop(name, None)
            self._save_playlists()
            self._safe_status_set(f'Playlist "{name}" removed.')

    def _apply_selected_playlist(self):
        name = self.current_playlist.get()
        if not name or name == '(None)':
            return
        files = self.playlists.get(name, [])
        # filter to files that still exist
        files = [f for f in files if os.path.exists(f)]
        self.files = files
        self._apply_search_filter()  # update filtered_files & UI
        self._safe_status_set(f'Loaded playlist "{name}" ({len(self.files)} files).')

    # ---------------- Folder / file loading ----------------
    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self.folder = folder
        self._load_files()
        self._safe_status_set(f'Selected {self.folder} — {len(self.files)} playable files')

    def _load_files(self):
        self.files = []
        if not self.folder:
            return
        for root, dirs, files in os.walk(self.folder):
            for fn in files:
                if fn.lower().endswith(PLAYABLE_EXTS):
                    self.files.append(os.path.join(root, fn))
        self.files.sort()
        # after loading files, apply search filter and update listbox
        self._apply_search_filter()
        self.current_index = None

    # ---------------- Search ----------------
    def _apply_search_filter(self):
        q = self.search_var.get().strip().lower()
        if not q:
            self.filtered_files = list(self.files)
        else:
            self.filtered_files = [f for f in self.files if q in os.path.basename(f).lower()]
        self._refresh_listbox()

    def _refresh_listbox(self):
        self.listbox.delete(0, 'end')
        for f in self.filtered_files:
            self.listbox.insert('end', os.path.relpath(f, self.folder) if self.folder else f)

    # ---------------- Playback control ----------------
    def start(self):
        if not self.filtered_files:
            messagebox.showwarning('No files', 'No playable files loaded.')
            return
        if not VLC_AVAILABLE and any(p.lower().endswith(VIDEO_EXTS) for p in self.filtered_files):
            messagebox.showwarning('VLC missing', 'Video files found but python-vlc is not available. Install python-vlc and VLC.')
        # init vlc players
        if VLC_AVAILABLE and not self.vlc_instance:
            try:
                self.vlc_instance = vlc.Instance()
                self.vlc_player = self.vlc_instance.media_player_new()
            except Exception:
                self.vlc_instance = None
                self.vlc_player = None
        self.is_running = True
        self.is_paused = False
        self.status_var.set('Running')
        if self.current_index is None:
            self.current_index = 0
        # immediate play
        self._play_current()

    def stop(self):
        self.is_running = False
        self.is_paused = False
        self._cancel_timers()
        self._stop_video()
        self.image_panel.config(image='', text='')
        self.status_var.set('Stopped')

    def toggle_pause(self):
        if not self.is_running:
            return
        if self.is_paused:
            self.is_paused = False
            if self._after_id is None:
                self._after_id = self.after(self.interval_seconds.get() * 1000, self.play_next)
            if self.vlc_player and VLC_AVAILABLE:
                try:
                    self.vlc_player.play()
                except Exception:
                    pass
            self.status_var.set('Resumed')
        else:
            self.is_paused = True
            self._cancel_timers()
            if self.vlc_player and VLC_AVAILABLE:
                try:
                    self.vlc_player.pause()
                except Exception:
                    pass
            self.status_var.set('Paused')

    def play_prev(self):
        if not self.filtered_files:
            return
        if self.shuffle.get():
            self.current_index = random.randrange(len(self.filtered_files))
        else:
            if self.current_index is None:
                self.current_index = 0
            else:
                self.current_index = (self.current_index - 1) % len(self.filtered_files)
        self._play_current()

    def play_next(self):
        if not self.filtered_files:
            return
        if self.shuffle.get():
            self.current_index = random.randrange(len(self.filtered_files))
        else:
            if self.current_index is None:
                self.current_index = 0
            else:
                self.current_index = (self.current_index + 1) % len(self.filtered_files)
        self._play_current()

    def _on_list_double(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.current_index = sel[0]
        self._play_current()

    def _play_current(self):
        self._cancel_timers()
        idx = self.current_index
        if idx is None or idx < 0 or idx >= len(self.filtered_files):
            return
        path = self.filtered_files[idx]
        # highlight in listbox
        self.listbox.selection_clear(0, 'end')
        self.listbox.selection_set(idx)
        self.listbox.see(idx)

        ext = os.path.splitext(path)[1].lower()
        if ext in IMAGE_EXTS:
            self._stop_video()
            self._show_image(path)
            # play SFX (non-blocking)
            self.play_image_sfx()
            # schedule next
            if self.is_running and not self.is_paused:
                self._start_countdown(self.interval_seconds.get())
        elif ext in VIDEO_EXTS:
            if not VLC_AVAILABLE or not self.vlc_player:
                self._stop_video()
                self._show_placeholder_video(path)
                if self.is_running and not self.is_paused:
                    self._start_countdown(self.interval_seconds.get())
            else:
                self._play_video(path)
                # if loop_videos is True -> don't advance automatically; loop same video
                if self.loop_videos.get():
                    # schedule to restart same video after its length
                    self._start_countdown_for_video_loop(path)
                else:
                    # schedule next after interval_seconds
                    if self.is_running and not self.is_paused:
                        self._start_countdown(self.interval_seconds.get())
        else:
            self.status_var.set('Unknown file type: ' + path)

    # ---------------- Timer / Countdown helpers ----------------
    def _start_countdown(self, seconds):
        self._cancel_timers()
        self._countdown_seconds_left = seconds
        self.progress['maximum'] = seconds
        self.progress['value'] = 0
        self._tick_countdown()

    def _tick_countdown(self):
        if not self.is_running or self.is_paused:
            return
        if self._countdown_seconds_left <= 0:
            self.timer_label.config(text='Next meme in: 0s')
            self.progress['value'] = self.progress['maximum']
            self.play_next()
            return
        self.timer_label.config(text=f'Next meme in: {int(self._countdown_seconds_left)}s')
        elapsed = self.progress['value'] + 1
        self.progress['value'] = elapsed
        self._countdown_seconds_left -= 1
        self._after_id = self.after(1000, self._tick_countdown)

    def _start_countdown_for_video_loop(self, path):
        # attempt to read video length via VLC; if not available fallback to interval_seconds
        self._cancel_timers()
        length_s = None
        try:
            media = self.vlc_instance.media_new(path)
            # parse media to get duration (may be async)
            media.parse_with_options(parse_flag=0, timeout=1)
            length_ms = media.get_duration()
            if length_ms and length_ms > 0:
                length_s = length_ms // 1000
        except Exception:
            length_s = None
        if not length_s or length_s <= 0:
            length_s = self.interval_seconds.get()
        self._countdown_seconds_left = length_s
        self.progress['maximum'] = length_s
        self.progress['value'] = 0
        self._tick_countdown()

    def _cancel_timers(self):
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
            self._countdown_seconds_left = 0
            self.progress['value'] = 0
            self.timer_label.config(text='Next meme in: --')

    # ---------------- Display helpers ----------------
    def _show_image(self, path):
        self.image_panel.lift(self.video_panel)
        try:
            img = Image.open(path)
            panel_w = self.image_panel.winfo_width() or 800
            panel_h = self.image_panel.winfo_height() or 450
            img.thumbnail((panel_w, panel_h), Image.LANCZOS)
            self._imgtk = ImageTk.PhotoImage(img)
            self.image_panel.config(image=self._imgtk, text='')
            self.status_var.set(f'Displaying image: {os.path.basename(path)}')
        except Exception as e:
            self.status_var.set('Error showing image: ' + str(e))

    def _show_placeholder_video(self, path):
        self.image_panel.lift(self.video_panel)
        txt = f'Video file\n{os.path.basename(path)}\n(no video backend)'
        self.image_panel.config(image='', text=txt, fg='white', font=('Arial', 16))
        self.status_var.set('Video file (no video backend): ' + os.path.basename(path))

    # ---------------- Video playback ----------------
    def _play_video(self, path):
        self.video_panel.lift(self.image_panel)
        self.image_panel.config(image='', text='')
        if not self.vlc_player:
            return
        try:
            media = self.vlc_instance.media_new(path)
            self.vlc_player.set_media(media)
            self._attach_vlc_player_to_panel()
            try:
                self.vlc_player.audio_set_volume(int(self.bgm_volume.get()))
            except Exception:
                pass
            self.vlc_player.play()
            self.status_var.set('Playing video: ' + os.path.basename(path))
        except Exception as e:
            self.status_var.set('Error playing video: ' + str(e))

    def _attach_vlc_player_to_panel(self):
        if not self.vlc_player:
            return
        self.update_idletasks()
        handle = self.video_panel.winfo_id()
        if sys.platform.startswith('win'):
            try:
                self.vlc_player.set_hwnd(handle)
            except Exception:
                pass
        elif sys.platform.startswith('linux'):
            try:
                self.vlc_player.set_xwindow(handle)
            except Exception:
                try:
                    self.vlc_player.set_xid(handle)
                except Exception:
                    pass
        elif sys.platform.startswith('darwin'):
            try:
                self.vlc_player.set_nsobject(handle)
            except Exception:
                pass

    def _stop_video(self):
        if self.vlc_player:
            try:
                self.vlc_player.stop()
            except Exception:
                pass
        if self._video_stop_timer:
            try:
                self._video_stop_timer.cancel()
            except Exception:
                pass
            self._video_stop_timer = None

    # ---------------- SFX playback ----------------
    def _pick_random_sfx(self):
        if not self.sfx_files:
            return None
        return random.choice(self.sfx_files)

    def play_image_sfx(self):
        if not self.enable_image_sfx.get():
            return
        sfx_path = self._pick_random_sfx()
        if not sfx_path or not os.path.exists(sfx_path):
            return
        # Try VLC for cross-format play
        if VLC_AVAILABLE:
            try:
                if not self.vlc_instance:
                    self.vlc_instance = vlc.Instance()
                sfx_player = self.vlc_instance.media_player_new()
                media = vlc.Media(sfx_path)
                sfx_player.set_media(media)
                try:
                    sfx_player.audio_set_volume(int(self.sfx_volume.get()))
                except Exception:
                    pass
                sfx_player.play()

                def stop_player_later(player):
                    try:
                        time.sleep(0.2)
                        length_ms = player.get_length()
                        if length_ms and length_ms > 0:
                            time.sleep((length_ms / 1000.0) * 1.1)
                        else:
                            time.sleep(2.0)
                        try:
                            player.stop()
                        except Exception:
                            pass
                    except Exception:
                        pass

                t = threading.Thread(target=stop_player_later, args=(sfx_player,), daemon=True)
                t.start()
                return
            except Exception:
                pass
        # winsound fallback for wav on Windows
        if WINSOUND_AVAILABLE and sfx_path.lower().endswith('.wav'):
            try:
                winsound.PlaySound(sfx_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception:
                pass

    # ---------------- BGM controls ----------------
    def _bgm_play(self):
        self.bgm.set_volume(self.bgm_volume.get())
        if not self.bgm.bgm_files:
            self._load_bgm_files()
        self.bgm.play()
        self._safe_status_set('BGM playing')

    def _bgm_pause(self):
        self.bgm.pause()
        self._safe_status_set('BGM paused')

    def _bgm_next(self):
        self.bgm.next()
        self._safe_status_set('BGM next')

    def _bgm_prev(self):
        self.bgm.prev()
        self._safe_status_set('BGM prev')

    def _on_bgm_volume_change(self, _val):
        self.bgm.set_volume(self.bgm_volume.get())

    def open_bgm_folder(self):
        try:
            if sys.platform.startswith('win'):
                os.startfile(ASSETS_BGM_DIR)
            elif sys.platform.startswith('darwin'):
                os.system(f'open "{ASSETS_BGM_DIR}"')
            else:
                os.system(f'xdg-open "{ASSETS_BGM_DIR}"')
            self.after(600, self._load_bgm_files)
        except Exception as e:
            messagebox.showinfo('Open folder', f'Open BGM folder: {ASSETS_BGM_DIR}\n\nError: {e}')

    # ---------------- Volume / misc ----------------
    def _on_volume_change(self, _val):
        if VLC_AVAILABLE and self.vlc_player:
            try:
                self.vlc_player.audio_set_volume(int(self.bgm_volume.get()))
            except Exception:
                pass

    def _on_sfx_volume_change(self, _val):
        # affects future SFX players (VLC)
        pass

    # ---------------- Playlists / helpers ----------------
    def _safe_status_set(self, text):
        try:
            self.status_var.set(text)
        except Exception:
            pass

    # ---------------- Hotkeys ----------------
    def _setup_hotkeys(self):
        if KEYBOARD_AVAILABLE:
            try:
                # register ctrl+alt+right => next, left => prev, ctrl+alt+space => pause/resume
                keyboard.add_hotkey('ctrl+alt+right', lambda: self.play_next())
                keyboard.add_hotkey('ctrl+alt+left', lambda: self.play_prev())
                keyboard.add_hotkey('ctrl+alt+space', lambda: self.toggle_pause())
                self.hotkeys_registered = True
                self._safe_status_set('Global hotkeys registered (Ctrl+Alt+Right/Left/Space)')
            except Exception:
                self.hotkeys_registered = False
        else:
            # fallback already bound to app-level keybindings in setup_ui()
            self._safe_status_set('Keyboard module not available; using local hotkeys when app focused')

    # ---------------- Save/exit ----------------
    def on_close(self):
        # cleanup bgm
        try:
            self.bgm.stop()
        except Exception:
            pass
        # unregister keyboard hotkeys if used
        if KEYBOARD_AVAILABLE and self.hotkeys_registered:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
        self.stop()
        self.destroy()


# ---------------- Simple dialog helper ----------------
def simple_input_dialog(parent, title, prompt):
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.grab_set()
    ttk.Label(dlg, text=prompt).pack(padx=12, pady=8)
    v = tk.StringVar()
    entry = ttk.Entry(dlg, textvariable=v, width=40)
    entry.pack(padx=12, pady=(0, 8))
    entry.focus_set()
    result = {'value': None}

    def on_ok():
        result['value'] = v.get().strip()
        dlg.destroy()

    def on_cancel():
        dlg.destroy()

    btn_frame = ttk.Frame(dlg)
    btn_frame.pack(pady=(0, 12))
    ttk.Button(btn_frame, text='OK', command=on_ok).pack(side='left', padx=6)
    ttk.Button(btn_frame, text='Cancel', command=on_cancel).pack(side='left', padx=6)
    parent.wait_window(dlg)
    return result['value']


if __name__ == '__main__':
    app = MemePlayer()
    app.mainloop()
