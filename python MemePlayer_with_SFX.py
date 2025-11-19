"""
MemePlayer_with_SFX_fixed.py

Fixed version of MemePlayer + Image Reaction Sounds (MP3 support included).

Dependencies:
    pip install pillow python-vlc

Ensure VLC (matching Python bitness) is installed for video playback and MP3 via python-vlc.
"""

import os
import sys
import random
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

# Try import vlc, if not available we'll fall back (Windows winsound) or skip SFX.
try:
    import vlc
    VLC_AVAILABLE = True
except Exception:
    VLC_AVAILABLE = False

# On Windows, winsound can play .wav asynchronously (fallback)
try:
    import winsound
    WINSOUND_AVAILABLE = True
except Exception:
    WINSOUND_AVAILABLE = False

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp')
VIDEO_EXTS = ('.mp4', '.mov', '.m4v')
PLAYABLE_EXTS = IMAGE_EXTS + VIDEO_EXTS

# Support common audio formats; mp3 included
SFX_EXTS = ('.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac')

ASSETS_SFX_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'sfx')


class MemePlayer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('MemePlayer')
        self.geometry('900x600')
        self.protocol('WM_DELETE_WINDOW', self.on_close)

        # playback state
        self.folder = None
        self.files = []
        self.current_index = None
        self.is_running = False
        self.is_paused = False
        self.shuffle = tk.BooleanVar(value=True)
        self.interval_seconds = tk.IntVar(value=30)

        # VLC player for videos
        self.vlc_instance = None
        self.vlc_player = None

        # SFX
        self.sfx_files = []
        self.enable_image_sfx = tk.BooleanVar(value=True)
        self.sfx_volume = tk.IntVar(value=80)

        self._after_id = None
        self._video_stop_timer = None

        # IMPORTANT: build UI first so status_var exists, then load SFX
        self.setup_ui()
        self._load_sfx_files()

    def setup_ui(self):
        # Top controls
        control_frame = ttk.Frame(self)
        control_frame.pack(side='top', fill='x', padx=8, pady=6)

        ttk.Button(control_frame, text='Select Folder', command=self.select_folder).pack(side='left')
        ttk.Button(control_frame, text='Start', command=self.start).pack(side='left', padx=6)
        ttk.Button(control_frame, text='Stop', command=self.stop).pack(side='left')
        ttk.Button(control_frame, text='Prev', command=self.play_prev).pack(side='left', padx=6)
        ttk.Button(control_frame, text='Next', command=self.play_next).pack(side='left')
        ttk.Button(control_frame, text='Pause/Resume', command=self.toggle_pause).pack(side='left', padx=6)

        ttk.Checkbutton(control_frame, text='Shuffle', variable=self.shuffle).pack(side='left', padx=8)

        ttk.Label(control_frame, text='Interval (s):').pack(side='left')
        interval_spin = ttk.Spinbox(control_frame, from_=5, to=3600, textvariable=self.interval_seconds, width=6)
        interval_spin.pack(side='left', padx=(2, 12))

        if VLC_AVAILABLE:
            ttk.Label(control_frame, text='Volume:').pack(side='left')
            self.volume = tk.IntVar(value=80)
            vol = ttk.Scale(control_frame, from_=0, to=100, orient='horizontal',
                            variable=self.volume, command=self._on_volume_change, length=120)
            vol.pack(side='left', padx=6)
        else:
            # still create a dummy volume var to avoid attribute errors
            self.volume = tk.IntVar(value=80)
            ttk.Label(control_frame, text='(Video support requires python-vlc and VLC installed)').pack(side='left',
                                                                                                    padx=8)

        # SFX controls
        sfx_frame = ttk.Frame(self)
        sfx_frame.pack(side='top', fill='x', padx=8, pady=(0, 6))

        ttk.Checkbutton(sfx_frame, text='Play reaction sound for images', variable=self.enable_image_sfx).pack(
            side='left', padx=(0, 12))

        ttk.Label(sfx_frame, text='SFX Volume:').pack(side='left')
        sfx_vol = ttk.Scale(sfx_frame, from_=0, to=100, orient='horizontal', variable=self.sfx_volume,
                            command=self._on_sfx_volume_change, length=120)
        sfx_vol.pack(side='left', padx=6)

        ttk.Button(sfx_frame, text='Open SFX Folder', command=self.open_sfx_folder).pack(side='left', padx=6)
        ttk.Button(sfx_frame, text='Reload SFX', command=self._load_sfx_files).pack(side='left', padx=6)

        # Main area
        main_frame = ttk.Frame(self)
        main_frame.pack(fill='both', expand=True)

        # Left list of files
        left = ttk.Frame(main_frame, width=240)
        left.pack(side='left', fill='y', padx=6, pady=6)
        ttk.Label(left, text='Files in folder:').pack(anchor='w')
        self.listbox = tk.Listbox(left, width=36)
        self.listbox.pack(fill='both', expand=True)
        self.listbox.bind('<Double-Button-1>', lambda e: self._on_list_double())

        # Right display (image or video)
        right = ttk.Frame(main_frame)
        right.pack(side='left', fill='both', expand=True)

        # Canvas for images
        self.image_panel = tk.Label(right, bg='black')
        self.image_panel.pack(fill='both', expand=True)

        # Video panel (a frame we will give to vlc)
        self.video_panel = ttk.Frame(right)
        self.video_panel.place(relx=0, rely=0, relwidth=1, relheight=1)
        # Keep video_panel behind image_panel; we'll lift the one we need
        self.video_panel.lower(self.image_panel)

        # Status bar
        self.status_var = tk.StringVar(value='No folder selected')
        status = ttk.Label(self, textvariable=self.status_var, anchor='w')
        status.pack(side='bottom', fill='x')

    # ----------------- SFX helpers -----------------
    def _load_sfx_files(self):
        """Scan assets/sfx folder for supported sounds."""
        self.sfx_files = []
        try:
            if not os.path.exists(ASSETS_SFX_DIR):
                os.makedirs(ASSETS_SFX_DIR, exist_ok=True)
            for fn in os.listdir(ASSETS_SFX_DIR):
                if fn.lower().endswith(SFX_EXTS):
                    self.sfx_files.append(os.path.join(ASSETS_SFX_DIR, fn))
            self.sfx_files.sort()
            # Update status only if status_var exists
            try:
                self.status_var.set(f'Loaded {len(self.sfx_files)} SFX files.')
            except Exception:
                pass
        except Exception:
            self.sfx_files = []
            try:
                self.status_var.set('Failed to load SFX folder.')
            except Exception:
                pass

    def open_sfx_folder(self):
        """Open the SFX folder in file explorer so user can drop sounds."""
        if not os.path.exists(ASSETS_SFX_DIR):
            os.makedirs(ASSETS_SFX_DIR, exist_ok=True)
        try:
            if sys.platform.startswith('win'):
                os.startfile(ASSETS_SFX_DIR)
            elif sys.platform.startswith('darwin'):
                os.system(f'open "{ASSETS_SFX_DIR}"')
            else:
                os.system(f'xdg-open "{ASSETS_SFX_DIR}"')
            # reload after a short delay so newly added files appear
            self.after(600, self._load_sfx_files)
        except Exception as e:
            messagebox.showinfo('Open folder', f'Open SFX folder: {ASSETS_SFX_DIR}\n\nError: {e}')

    def _pick_random_sfx(self):
        if not self.sfx_files:
            return None
        return random.choice(self.sfx_files)

    def play_image_sfx(self):
        """Play a random SFX non-blocking when an image is shown."""
        if not self.enable_image_sfx.get():
            return
        sfx_path = self._pick_random_sfx()
        if not sfx_path or not os.path.exists(sfx_path):
            return  # no sfx available

        # If VLC available, use a temporary vlc.MediaPlayer for the SFX
        if VLC_AVAILABLE:
            try:
                # ensure vlc instance exists (don't override main player)
                if not self.vlc_instance:
                    self.vlc_instance = vlc.Instance()
                # ephemeral player so it doesn't affect video player
                sfx_player = self.vlc_instance.media_player_new()
                media = vlc.Media(sfx_path)
                sfx_player.set_media(media)
                try:
                    sfx_player.audio_set_volume(int(self.sfx_volume.get()))
                except Exception:
                    pass
                sfx_player.play()

                # schedule a cleanup after estimated duration (non-blocking)
                def stop_player_later(player):
                    try:
                        # wait a bit for length to become available
                        time.sleep(0.2)
                        length_ms = player.get_length()
                        if length_ms and length_ms > 0:
                            time.sleep((length_ms / 1000.0) * 1.1)
                        else:
                            # fallback short sleep
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
                # If VLC fails for SFX, fallthrough to winsound fallback
                pass

        # Fallback: try winsound on Windows for .wav files
        if WINSOUND_AVAILABLE and sfx_path.lower().endswith('.wav'):
            try:
                winsound.PlaySound(sfx_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception:
                pass
        # else: no cross-platform builtin audio; skip

    def _on_sfx_volume_change(self, _val):
        # volume applied to future SFX players (VLC); winsound has no volume control here
        pass

    # ----------------- File / playback helpers -----------------
    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self.folder = folder
        self._load_files()
        self.status_var.set(f'Selected: {self.folder} — {len(self.files)} playable files')

    def _load_files(self):
        self.files = []
        if not self.folder:
            return
        for root, dirs, filenames in os.walk(self.folder):
            for fn in filenames:
                if fn.lower().endswith(PLAYABLE_EXTS):
                    self.files.append(os.path.join(root, fn))
        self.files.sort()
        self._refresh_listbox()
        self.current_index = None

    def _refresh_listbox(self):
        self.listbox.delete(0, 'end')
        for f in self.files:
            self.listbox.insert('end', os.path.relpath(f, self.folder) if self.folder else f)

    def start(self):
        if not self.folder or not self.files:
            messagebox.showwarning('No folder', 'Please select a folder with memes first.')
            return
        if not VLC_AVAILABLE and any(f.lower().endswith(VIDEO_EXTS) for f in self.files):
            messagebox.showwarning('VLC missing', 'Video files found but python-vlc or VLC is not available. Install python-vlc and VLC to enable video playback.')

        if self.vlc_instance is None and VLC_AVAILABLE:
            # create instance and main player
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
        # schedule immediate play
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
            # resume
            self.is_paused = False
            if self._after_id is None:
                # schedule next
                self._after_id = self.after(self.interval_seconds.get() * 1000, self.play_next)
            if self.vlc_player and VLC_AVAILABLE:
                self.vlc_player.play()
            self.status_var.set('Resumed')
        else:
            self.is_paused = True
            self._cancel_timers()
            if self.vlc_player and VLC_AVAILABLE:
                self.vlc_player.pause()
            self.status_var.set('Paused')

    def play_prev(self):
        if not self.files:
            return
        if self.shuffle.get():
            # pick random distinct
            next_idx = random.randrange(len(self.files))
            self.current_index = next_idx
        else:
            if self.current_index is None:
                self.current_index = 0
            else:
                self.current_index = (self.current_index - 1) % len(self.files)
        self._play_current()

    def play_next(self):
        if not self.files:
            return
        if self.shuffle.get():
            next_idx = random.randrange(len(self.files))
            self.current_index = next_idx
        else:
            if self.current_index is None:
                self.current_index = 0
            else:
                self.current_index = (self.current_index + 1) % len(self.files)
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
        if idx is None or idx < 0 or idx >= len(self.files):
            return
        path = self.files[idx]
        self.listbox.selection_clear(0, 'end')
        self.listbox.selection_set(idx)
        self.listbox.see(idx)

        ext = os.path.splitext(path)[1].lower()
        if ext in IMAGE_EXTS:
            self._stop_video()
            self._show_image(path)
            # play reaction sound when showing image (after image displayed)
            self.play_image_sfx()
        elif ext in VIDEO_EXTS:
            if not VLC_AVAILABLE:
                # fallback: show a placeholder image
                self._stop_video()
                self._show_placeholder_video(path)
            else:
                self._play_video(path)
        else:
            self.status_var.set('Unknown file type: ' + path)

        # schedule next change after interval_seconds
        if self.is_running and not self.is_paused:
            self._after_id = self.after(self.interval_seconds.get() * 1000, self.play_next)

    def _show_image(self, path):
        # Raise image panel above video panel
        self.image_panel.lift(self.video_panel)
        try:
            img = Image.open(path)
            # resize preserving aspect ratio to fit panel
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
        txt = f'Video file\n{os.path.basename(path)}\n(python-vlc missing)'
        self.image_panel.config(image='', text=txt, fg='white', font=('Arial', 16))
        self.status_var.set('Video file (no video backend): ' + os.path.basename(path))

    def _play_video(self, path):
        # raise video panel above image panel
        self.video_panel.lift(self.image_panel)
        self.image_panel.config(image='', text='')

        if not self.vlc_player:
            return

        media = self.vlc_instance.media_new(path)
        self.vlc_player.set_media(media)

        # attach the video output to the video_panel
        self._attach_vlc_player_to_panel()

        # set volume
        try:
            self.vlc_player.audio_set_volume(int(self.volume.get()))
        except Exception:
            pass

        self.vlc_player.play()
        self.status_var.set('Playing video: ' + os.path.basename(path))

        # Stop the video after the interval (we want to switch every N seconds regardless of video length)
        # Cancel old timer if any and set a new one
        if self._video_stop_timer:
            try:
                self._video_stop_timer.cancel()
            except Exception:
                pass
        self._video_stop_timer = threading.Timer(self.interval_seconds.get(), self._stop_video)
        self._video_stop_timer.daemon = True
        self._video_stop_timer.start()

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
                # different vlc versions expose set_xwindow/set_xid
                try:
                    self.vlc_player.set_xid(handle)
                except Exception:
                    pass
        elif sys.platform.startswith('darwin'):
            # macOS may require special handling; try set_nsobject
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

    def _cancel_timers(self):
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _on_volume_change(self, _val):
        if VLC_AVAILABLE and self.vlc_player:
            try:
                self.vlc_player.audio_set_volume(int(self.volume.get()))
            except Exception:
                pass

    def on_close(self):
        # stop players and exit
        self.stop()
        self.destroy()


if __name__ == '__main__':
    app = MemePlayer()
    app.mainloop()
