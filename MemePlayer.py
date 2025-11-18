"""
MemePlayer - a simple Tkinter GUI that plays random memes from a selected folder every N seconds.
Supports images (png, jpg, jpeg, webp) and videos (mp4, mov) using Pillow + python-vlc.

Dependencies:
    pip install pillow python-vlc

Run:
    python MemePlayer.py

Features:
- Pick folder button
- Start / Stop / Next / Prev / Pause controls
- Interval (seconds) editable
- Shuffle mode
- Volume slider for videos

This is a single-file app. If python-vlc can't find the libvlc binaries, install VLC on your system.
"""

import os
import sys
import random
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

# Try import vlc, if not available we'll show an instruction message.
try:
    import vlc
    VLC_AVAILABLE = True
except Exception:
    VLC_AVAILABLE = False

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp')
VIDEO_EXTS = ('.mp4', '.mov', '.m4v')
PLAYABLE_EXTS = IMAGE_EXTS + VIDEO_EXTS

class MemePlayer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('MemePlayer')
        self.geometry('900x600')
        self.protocol('WM_DELETE_WINDOW', self.on_close)

        self.folder = None
        self.files = []
        self.current_index = None
        self.is_running = False
        self.is_paused = False
        self.shuffle = tk.BooleanVar(value=True)
        self.interval_seconds = tk.IntVar(value=30)

        # VLC player
        self.vlc_instance = None
        self.vlc_player = None

        self._after_id = None
        self._video_stop_timer = None

        self.setup_ui()

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
            vol = ttk.Scale(control_frame, from_=0, to=100, orient='horizontal', variable=self.volume, command=self._on_volume_change, length=120)
            vol.pack(side='left', padx=6)
        else:
            ttk.Label(control_frame, text='(Video support requires python-vlc and VLC installed)').pack(side='left', padx=8)

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

    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self.folder = folder
        self._load_files()
        self.status_var.set(f'Selected: {self.folder} — {len(self.files)} playable files')

    def _load_files(self):
        self.files = []
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
            self.vlc_instance = vlc.Instance()
            self.vlc_player = self.vlc_instance.media_player_new()

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
            # resize with preserving aspect ratio to fit panel
            panel_w = self.image_panel.winfo_width() or 800
            panel_h = self.image_panel.winfo_height() or 450
            img.thumbnail((panel_w, panel_h), Image.LANCZOS)
            self._imgtk = ImageTk.PhotoImage(img)
            self.image_panel.config(image=self._imgtk)
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
            self.vlc_player.set_hwnd(handle)
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
        self.stop()
        self.destroy()

if __name__ == '__main__':
    app = MemePlayer()
    app.mainloop()
