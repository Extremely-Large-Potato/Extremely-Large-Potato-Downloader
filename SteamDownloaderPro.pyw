import os
import time
import psutil
import threading
import subprocess
import queue
import json
import customtkinter as ctk
from datetime import datetime
from enum import Enum
from tkinter import filedialog
import arabic_reshaper
from bidi.algorithm import get_display

# ==========================================
# تابع کمکی برای نمایش صحیح متن فارسی (RTL)
# ==========================================
def fix_persian(text):
    """Reshape and apply bidi algorithm so Persian renders correctly in Tkinter."""
    try:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text  # fallback: return original if libraries fail


# ==========================================
# دیکشنری چندزبانه (I18N)
# تمام مقادیر فارسی از fix_persian() رد می‌شن تا RTL درست نمایش داده بشه
# ==========================================
def _fa(text):
    return fix_persian(text)

I18N = {
    "English": {
        "title": "Steam Download Manager - Enterprise",
        "steam_path": "Steam.exe Path:",
        "log_path": "Log Directory:",
        "browse": "Browse...",
        "min_speed": "Min Speed (KB/s):",
        "shutdown_time": "Shutdown Time:",
        "theme": "Theme:",
        "lang": "Language:",
        "start": "▶ Start Monitor",
        "stop": "■ Stop Monitor",
        "net_speed": "Network:",
        "disk_speed": "Disk:",
        "cancel_shutdown": "✕ Cancel Shutdown",
        "warning_no_path": "⚠  Please set the Steam.exe path first.",
    },
    "فارسی": {
        "title":           "مدیریت دانلود استیم - نسخه تجاری",  # titlebar handles RTL natively
        "steam_path":      _fa("مسیر فایل استیم:"),
        "log_path":        _fa("محل ذخیره لاگ:"),
        "browse":          _fa("انتخاب مسیر"),
        "min_speed":       _fa("حداقل سرعت (KB/s):"),
        "shutdown_time":   _fa("زمان خاموشی سیستم:"),
        "theme":           _fa("رنگ‌بندی:"),
        "lang":            _fa("زبان:"),
        "start":           _fa("▶ شروع مانیتورینگ"),
        "stop":            _fa("■ توقف مانیتورینگ"),
        "net_speed":       _fa("سرعت شبکه:"),
        "disk_speed":      _fa("سرعت دیسک:"),
        "cancel_shutdown": _fa("✕ لغو خاموشی"),
        "warning_no_path": _fa("لطفاً ابتدا مسیر Steam.exe را تنظیم کنید."),
    }
}

# ==========================================
# تنظیمات پایه CustomTkinter
# ==========================================
ctk.set_default_color_theme("blue")

# ==========================================
# امضای توسعه‌دهنده — تغییر ندهید
# ==========================================
_AUTHOR      = "Extremely Large Potato"
_AUTHOR_JOKE = "سیب‌زمینی رفت خواستگاری... گفتن: «شغلت چیه؟» گفت: فعلاً سرخ‌پوستم، ولی آینده‌م روشنه! 🍟"
_VERSION     = "1.0.0"
_GITHUB      = "https://github.com/Extremely-Large-Potato"

def _get_signature():
    """این تابع امضای برنامه رو برمی‌گردونه — دست نزنید! 🥔"""
    return f"{_AUTHOR}  •  v{_VERSION}"

def _get_joke():
    return _AUTHOR_JOKE  # tooltip سیستم‌عامل RTL رو خودش handle می‌کنه


class State(Enum):
    IDLE       = ("IDLE",       "آماده به کار")
    NETWORK    = ("NETWORK",    "در حال دانلود")
    PROCESSING = ("PROCESSING", "در حال پردازش/نصب")
    VERIFYING  = ("VERIFYING",  "تایید فایل‌ها")
    STUCK      = ("STUCK",      "گیر کرده/افت سرعت")
    RECOVERY   = ("RECOVERY",   "در حال بازیابی")
    COOLDOWN   = ("COOLDOWN",   "استراحت سیستم")

    def display(self, lang="English"):
        """Return correctly rendered state label for current language."""
        eng, fa = self.value
        if lang == "فارسی":
            return f"{eng} ({fix_persian(fa)})"
        return f"{eng} ({fa})"


# ==========================================
# کلاس اصلی اپلیکیشن
# ==========================================
class SteamDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Steam Download Manager")
        self.geometry("800x750")
        self.minsize(750, 650)

        # متغیرهای ذخیره‌سازی
        self.config_file = "config.json"
        self.steam_var = ctk.StringVar()
        self.log_var = ctk.StringVar()
        self.threshold_var = ctk.StringVar(value="50")

        # متغیرهای جدید برای تم، زبان و زمان خاموشی
        self.lang_var = ctk.StringVar(value="English")
        self.theme_var = ctk.StringVar(value="Dark")
        self.hour_var = ctk.StringVar(value="00")
        self.min_var = ctk.StringVar(value="00")

        self.stuck_time_limit = 30
        self.net_history = [0] * 60
        self.disk_history = [0] * 60
        self.gui_queue = queue.Queue()
        self.is_running = False
        self.current_state = State.IDLE
        self.stuck_timer = 0
        self.shutdown_triggered = False
        self._shutdown_cancelled_today = ""  # روز لغو خاموشی

        # FIX: Track per-PID disk I/O to avoid accumulation bug
        self._pid_disk_snapshot = {}

        # FIX: Guard against concurrent restart calls
        self._restart_in_progress = False

        self.load_settings()

        # تنظیم تم اولیه
        ctk.set_appearance_mode(self.theme_var.get())

        self.build_base_ui()
        self.build_settings_ui()
        self.build_dashboard_ui()

        # FIX: Register traces only once here, not inside build_settings_ui()
        for var in (self.steam_var, self.log_var, self.threshold_var,
                    self.hour_var, self.min_var):
            var.trace_add("write", self.save_settings)

        self.process_queue()
        self.check_shutdown_timer()

    # ------------------------------------------
    # بخش 1: مدیریت تنظیمات
    # ------------------------------------------
    def load_settings(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.steam_var.set(data.get("steam_path", ""))
                    self.log_var.set(data.get("log_path", ""))
                    self.threshold_var.set(str(data.get("threshold", 50)))

                    # جلوگیری از ارور نسخه قبلی
                    saved_lang = data.get("lang", "English")
                    if saved_lang == "fa":
                        saved_lang = "فارسی"
                    elif saved_lang == "en":
                        saved_lang = "English"
                    self.lang_var.set(saved_lang)

                    self.theme_var.set(data.get("theme", "Dark"))
                    self.hour_var.set(data.get("hour", "00"))
                    self.min_var.set(data.get("min", "00"))
                    # اگه قبلاً همین روز خاموشی زده شده بود، دوباره trigger نشه
                    triggered_date = data.get("shutdown_triggered_date", "")
                    today = datetime.now().strftime("%Y-%m-%d")
                    if triggered_date == today:
                        self.shutdown_triggered = True
            except Exception as e:
                print(f"Error loading settings: {e}")

    def save_settings(self, *args):
        # FIX: Safe int conversion — don't crash on empty threshold field
        try:
            threshold_val = int(self.threshold_var.get())
        except ValueError:
            threshold_val = 50

        data = {
            "steam_path": self.steam_var.get(),
            "log_path": self.log_var.get(),
            "threshold": threshold_val,
            "lang": self.lang_var.get(),
            "theme": self.theme_var.get(),
            "hour": self.hour_var.get(),
            "min": self.min_var.get(),
            # تاریخ آخرین خاموشی رو ذخیره کن تا بعد از restart دوباره trigger نشه
            "shutdown_triggered_date": (
                datetime.now().strftime("%Y-%m-%d") if self.shutdown_triggered else ""
            )
        }
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

    # ------------------------------------------
    # بخش 2: رابط کاربری (مبنا و تنظیمات داینامیک)
    # ------------------------------------------
    def build_base_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.settings_frame = ctk.CTkFrame(self)
        self.settings_frame.grid(row=0, column=0, padx=20, pady=20, sticky="ew")

    def build_settings_ui(self):
        # پاک کردن المان‌های قبلی
        for widget in self.settings_frame.winfo_children():
            widget.destroy()

        lang = self.lang_var.get()
        if lang not in I18N:
            lang = "English"
            self.lang_var.set("English")

        is_rtl = (lang == "فارسی")
        texts = I18N[lang]

        self.title(texts["title"])

        self.settings_frame.grid_columnconfigure(0, weight=1)
        self.settings_frame.grid_columnconfigure(1, weight=0)
        self.settings_frame.grid_columnconfigure(2, weight=0)
        self.settings_frame.grid_columnconfigure(3, weight=0)
        self.settings_frame.grid_columnconfigure(4, weight=1)

        def create_row(row_idx, label_text, widget_center, widget_side=None):
            lbl = ctk.CTkLabel(self.settings_frame, text=label_text, font=("Segoe UI", 13))
            if is_rtl:
                lbl.grid(row=row_idx, column=3, padx=10, pady=10, sticky="w")
                widget_center.grid(row=row_idx, column=2, padx=10, pady=10, sticky="ew")
                if widget_side:
                    widget_side.grid(row=row_idx, column=1, padx=10, pady=10, sticky="e")
            else:
                lbl.grid(row=row_idx, column=1, padx=10, pady=10, sticky="e")
                widget_center.grid(row=row_idx, column=2, padx=10, pady=10, sticky="ew")
                if widget_side:
                    widget_side.grid(row=row_idx, column=3, padx=10, pady=10, sticky="w")

        # ردیف 0: تم و زبان
        # FIX: Create combos as children of top_frame (not settings_frame) so
        # pack() inside top_frame never conflicts with grid() on settings_frame.
        top_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        top_frame.grid(row=0, column=1, columnspan=3, pady=10)   # grid on settings_frame ✓

        combo_lang = ctk.CTkOptionMenu(top_frame, values=["English", "فارسی"],
                                       variable=self.lang_var, command=self.change_language)
        combo_theme = ctk.CTkOptionMenu(top_frame, values=["Dark", "Light"],
                                        variable=self.theme_var, command=self.change_theme)

        if is_rtl:
            ctk.CTkLabel(top_frame, text=texts["lang"]).pack(side="right", padx=5)
            combo_lang.pack(side="right", padx=5)
            ctk.CTkLabel(top_frame, text=texts["theme"]).pack(side="right", padx=5)
            combo_theme.pack(side="right", padx=5)
        else:
            ctk.CTkLabel(top_frame, text=texts["lang"]).pack(side="left", padx=5)
            combo_lang.pack(side="left", padx=5)
            ctk.CTkLabel(top_frame, text=texts["theme"]).pack(side="left", padx=5)
            combo_theme.pack(side="left", padx=5)

        # ردیف 1 و 2: مسیرها
        entry_steam = ctk.CTkEntry(self.settings_frame, textvariable=self.steam_var, width=300)
        btn_steam = ctk.CTkButton(self.settings_frame, text=texts["browse"], width=100,
                                  command=self.browse_steam)
        create_row(1, texts["steam_path"], entry_steam, btn_steam)

        entry_log = ctk.CTkEntry(self.settings_frame, textvariable=self.log_var, width=300)
        btn_log = ctk.CTkButton(self.settings_frame, text=texts["browse"], width=100,
                                command=self.browse_log)
        create_row(2, texts["log_path"], entry_log, btn_log)

        # ردیف 3: حداقل سرعت و زمان خاموشی
        time_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        hours = [f"{i:02d}" for i in range(24)]
        mins = [f"{i:02d}" for i in range(60)]

        ctk.CTkOptionMenu(time_frame, values=hours, variable=self.hour_var, width=60).pack(side="left")
        ctk.CTkLabel(time_frame, text=" : ", font=("Segoe UI", 16, "bold")).pack(side="left")
        ctk.CTkOptionMenu(time_frame, values=mins, variable=self.min_var, width=60).pack(side="left")

        speed_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        entry_speed = ctk.CTkEntry(speed_frame, textvariable=self.threshold_var, width=80)

        if is_rtl:
            entry_speed.pack(side="right")
            ctk.CTkLabel(speed_frame, text=texts["min_speed"]).pack(side="right", padx=5)
            create_row(3, texts["shutdown_time"], time_frame, speed_frame)
        else:
            entry_speed.pack(side="left")
            ctk.CTkLabel(speed_frame, text=texts["min_speed"]).pack(side="left", padx=5)
            create_row(3, texts["shutdown_time"], time_frame, speed_frame)

        # Update dashboard labels if they already exist
        if hasattr(self, 'btn_start'):
            self.btn_start.configure(text=texts["start"])
            self.btn_stop.configure(text=texts["stop"])
            # label متن رو برای زبان جدید آپدیت کن — عدد لمس نمیشه
            if lang == "فارسی":
                self.lbl_speed_net.configure(text=fix_persian("سرعت شبکه:"))
                self.lbl_speed_disk.configure(text=fix_persian("سرعت دیسک:"))
            else:
                self.lbl_speed_net.configure(text="Network:")
                self.lbl_speed_disk.configure(text="Disk:")
        if hasattr(self, 'btn_cancel_shutdown'):
            self.btn_cancel_shutdown.configure(text=texts["cancel_shutdown"])

        # FIX: Traces are NOT registered here anymore — registered once in __init__

    def build_dashboard_ui(self):
        dashboard_frame = ctk.CTkFrame(self)
        dashboard_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        # Single column — everything centres automatically
        dashboard_frame.grid_columnconfigure(0, weight=1)

        lang = self.lang_var.get()
        if lang not in I18N:
            lang = "English"
        texts = I18N[lang]

        # Row 0: state label
        self.lbl_state = ctk.CTkLabel(dashboard_frame, text=self.current_state.display(self.lang_var.get()),
                                      font=("Segoe UI", 16, "bold"))
        self.lbl_state.grid(row=0, column=0, pady=(12, 4))

        # Row 1: speed labels — each split into a label-text + value pair
        # این کار از بهم‌ریختگی RTL در ترکیب متن فارسی و عدد جلوگیری می‌کنه
        speed_row = ctk.CTkFrame(dashboard_frame, fg_color="transparent")
        speed_row.grid(row=1, column=0, pady=4)

        _lang_init = self.lang_var.get()
        is_rtl_init = (_lang_init == "فارسی")

        # Network indicator — label frame
        net_frame = ctk.CTkFrame(speed_row, fg_color="transparent")
        net_frame.pack(side="left", padx=20)
        if is_rtl_init:
            self.lbl_speed_net_val = ctk.CTkLabel(net_frame, text="0.00 MB/s",
                                                  text_color="#2ecc71", font=("Segoe UI", 14))
            self.lbl_speed_net_val.pack(side="left")
            self.lbl_speed_net = ctk.CTkLabel(net_frame,
                                              text=fix_persian("سرعت شبکه:"),
                                              text_color="#2ecc71", font=("Segoe UI", 14))
            self.lbl_speed_net.pack(side="left", padx=(4, 0))
        else:
            self.lbl_speed_net = ctk.CTkLabel(net_frame, text="Network:",
                                              text_color="#2ecc71", font=("Segoe UI", 14))
            self.lbl_speed_net.pack(side="left")
            self.lbl_speed_net_val = ctk.CTkLabel(net_frame, text="0.00 MB/s",
                                                  text_color="#2ecc71", font=("Segoe UI", 14))
            self.lbl_speed_net_val.pack(side="left", padx=(4, 0))

        # Disk indicator — label frame
        disk_frame = ctk.CTkFrame(speed_row, fg_color="transparent")
        disk_frame.pack(side="left", padx=20)
        if is_rtl_init:
            self.lbl_speed_disk_val = ctk.CTkLabel(disk_frame, text="0.00 MB/s",
                                                   text_color="#3498db", font=("Segoe UI", 14))
            self.lbl_speed_disk_val.pack(side="left")
            self.lbl_speed_disk = ctk.CTkLabel(disk_frame,
                                               text=fix_persian("سرعت دیسک:"),
                                               text_color="#3498db", font=("Segoe UI", 14))
            self.lbl_speed_disk.pack(side="left", padx=(4, 0))
        else:
            self.lbl_speed_disk = ctk.CTkLabel(disk_frame, text="Disk:",
                                               text_color="#3498db", font=("Segoe UI", 14))
            self.lbl_speed_disk.pack(side="left")
            self.lbl_speed_disk_val = ctk.CTkLabel(disk_frame, text="0.00 MB/s",
                                                   text_color="#3498db", font=("Segoe UI", 14))
            self.lbl_speed_disk_val.pack(side="left", padx=(4, 0))

        # Row 2: all three buttons centred as a unit via inner frame
        btn_row = ctk.CTkFrame(dashboard_frame, fg_color="transparent")
        btn_row.grid(row=2, column=0, pady=(10, 14))

        self.btn_start = ctk.CTkButton(btn_row, text=texts["start"], width=160,
                                       fg_color="#27ae60", hover_color="#2ecc71",
                                       command=self.start_monitoring)
        self.btn_start.pack(side="left", padx=8)

        self.btn_stop = ctk.CTkButton(btn_row, text=texts["stop"], width=160,
                                      fg_color="#c0392b", hover_color="#e74c3c",
                                      state="disabled", command=self.stop_monitoring)
        self.btn_stop.pack(side="left", padx=8)

        self.btn_cancel_shutdown = ctk.CTkButton(
            btn_row, text=texts["cancel_shutdown"], width=160,
            fg_color="#7f8c8d", hover_color="#95a5a6",
            state="disabled", command=self.cancel_shutdown
        )
        self.btn_cancel_shutdown.pack(side="left", padx=8)

        # Row 3: warning label — hidden until needed
        self.lbl_warning = ctk.CTkLabel(dashboard_frame, text="",
                                        text_color="#e67e22", font=("Segoe UI", 12))
        self.lbl_warning.grid(row=3, column=0, pady=(0, 6))

        # Row 4: signature — غیرقابل حذف از UI، فقط از کد قابل تغییره
        sig_frame = ctk.CTkFrame(dashboard_frame, fg_color="transparent")
        sig_frame.grid(row=4, column=0, pady=(0, 10))

        import webbrowser
        _sig_lbl = ctk.CTkLabel(
            sig_frame,
            text=_get_signature(),
            font=("Segoe UI", 11, "bold"),
            text_color="#808080",
            cursor="hand2"
        )
        _sig_lbl.pack(side="left", padx=(0, 8))
        _sig_lbl.bind("<Button-1>", lambda e: webbrowser.open(_GITHUB))

        ctk.CTkLabel(
            sig_frame,
            text="🥔",
            font=("Segoe UI", 13),
        ).pack(side="left")

        # tooltip-style joke — hover روی 🥔 نشون داده میشه
        self._build_joke_tooltip(sig_frame)

        # Canvas bg respects current theme on first build
        initial_bg = "#1e1e1e" if self.theme_var.get() == "Dark" else "#f0f0f0"
        self.canvas = ctk.CTkCanvas(self, bg=initial_bg, highlightthickness=0)
        self.canvas.grid(row=2, column=0, padx=20, pady=20, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self.draw_graph())

    # ------------------------------------------
    # امضا و tooltip جوک
    # ------------------------------------------
    def _build_joke_tooltip(self, parent):
        """
        یه tooltip ساده می‌سازه که وقتی موس روی 🥔 میره، جوک نشون داده میشه.
        این tooltip از یه Toplevel بدون border ساخته شده — بدون کتابخانه اضافه.
        """
        # پیدا کردن label آخر (همون 🥔)
        potato_lbl = [w for w in parent.winfo_children()][-1]

        tip_window = [None]

        def show_tip(event):
            if tip_window[0]:
                return
            x = event.widget.winfo_rootx() + 20
            y = event.widget.winfo_rooty() - 40
            tw = ctk.CTkToplevel(self)
            tw.wm_overrideredirect(True)   # بدون titlebar
            tw.wm_geometry(f"+{x}+{y}")
            tw.attributes("-topmost", True)
            ctk.CTkLabel(
                tw,
                text=_get_joke(),
                font=("Segoe UI", 12),
                fg_color=("#f5f5f5", "#2b2b2b"),
                corner_radius=8,
                padx=10, pady=6
            ).pack()
            tip_window[0] = tw

        def hide_tip(event):
            if tip_window[0]:
                tip_window[0].destroy()
                tip_window[0] = None

        potato_lbl.bind("<Enter>", show_tip)
        potato_lbl.bind("<Leave>", hide_tip)

    # ------------------------------------------
    # رویدادهای تغییر زبان و تم
    # ------------------------------------------
    def change_language(self, choice):
        self.save_settings()
        self.build_settings_ui()
        self.draw_graph()

    def change_theme(self, choice):
        ctk.set_appearance_mode(choice)
        self.save_settings()
        self.canvas.configure(bg="#1e1e1e" if choice == "Dark" else "#f0f0f0")
        self.draw_graph()

    def browse_steam(self):
        path = filedialog.askopenfilename(filetypes=[("Executable", "*.exe")])
        if path:
            self.steam_var.set(path)

    def browse_log(self):
        path = filedialog.askdirectory()
        if path:
            self.log_var.set(path)

    # ------------------------------------------
    # بخش 3: سنسورها و منطق اصلی
    # ------------------------------------------
    def get_network_speed(self):
        try:
            current = psutil.net_io_counters()
            if not hasattr(self, "_last_net"):
                self._last_net = (current.bytes_recv, time.perf_counter())
                return 0
            old_bytes, old_time = self._last_net
            now = time.perf_counter()
            delta_bytes = current.bytes_recv - old_bytes
            delta_time = now - old_time
            self._last_net = (current.bytes_recv, now)
            return max(0, delta_bytes / delta_time) if delta_time > 0 else 0
        except Exception:
            return 0

    def get_steam_disk_speed(self):
        # FIX: Track per-PID snapshots so process restarts don't cause negative deltas
        now = time.perf_counter()
        new_snapshot = {}

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.info["name"] and "steam" in proc.info["name"].lower():
                    io = proc.io_counters()
                    new_snapshot[proc.info["pid"]] = io.read_bytes + io.write_bytes
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not hasattr(self, "_last_disk_time"):
            self._pid_disk_snapshot = new_snapshot
            self._last_disk_time = now
            return 0

        delta_time = now - self._last_disk_time
        if delta_time <= 0:
            return 0

        # Sum only PIDs present in both snapshots (ignores restarted processes)
        total_delta = 0
        for pid, current_bytes in new_snapshot.items():
            if pid in self._pid_disk_snapshot:
                diff = current_bytes - self._pid_disk_snapshot[pid]
                if diff > 0:
                    total_delta += diff

        self._pid_disk_snapshot = new_snapshot
        self._last_disk_time = now
        return total_delta / delta_time

    def graceful_steam_restart(self):
        # FIX: Guard so this never runs concurrently
        if self._restart_in_progress:
            return
        self._restart_in_progress = True

        steam_exe = self.steam_var.get()
        if not steam_exe or not os.path.exists(steam_exe):
            self._restart_in_progress = False
            return
        try:
            subprocess.run([steam_exe, "-shutdown"], timeout=15)
        except Exception:
            pass

        start_wait = time.time()
        while time.time() - start_wait < 30:
            if not any(
                p.info["name"] and p.info["name"].lower() == "steam.exe"
                for p in psutil.process_iter(["name"])
            ):
                break
            time.sleep(1)
        else:
            subprocess.run(["taskkill", "/F", "/IM", "steam.exe"])

        subprocess.Popen([steam_exe])
        time.sleep(8)
        os.system("start steam://open/downloads")

        self._restart_in_progress = False

    def write_log(self, state, net_speed, disk_speed, reason=""):
        folder = self.log_var.get()
        if not folder:
            return
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, datetime.now().strftime("%Y-%m-%d") + ".log")
        try:
            with open(file_path, "a", encoding="utf8") as f:
                f.write(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"State: {state.display()} | "
                    f"Net: {net_speed:.2f} MB/s | "
                    f"Disk: {disk_speed:.2f} MB/s | "
                    f"RAM: {psutil.virtual_memory().percent}% | "
                    f"CPU: {psutil.cpu_percent()}%\n"
                )
                if reason:
                    f.write(f"Reason: {reason}\n")
        except Exception:
            pass

    # ------------------------------------------
    # بخش 4: گراف ریسپانسیو و حلقه پردازش
    # ------------------------------------------
    def draw_graph(self):
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 20 or height < 20:
            return
        self.canvas.delete("all")

        grid_color = "#333333" if self.theme_var.get() == "Dark" else "#cccccc"
        for i in range(1, 4):
            y = height * (i / 4)
            self.canvas.create_line(0, y, width, y, fill=grid_color, dash=(4, 4))

        max_val = max(max(self.net_history), max(self.disk_history), 1)
        x_step = width / (len(self.net_history) - 1)

        net_coords = []
        disk_coords = []
        for i in range(len(self.net_history)):
            x = i * x_step
            y_net = max(5, height - (self.net_history[i] / max_val * height))
            y_disk = max(5, height - (self.disk_history[i] / max_val * height))
            net_coords.extend([x, y_net])
            disk_coords.extend([x, y_disk])

        if len(disk_coords) >= 4:
            self.canvas.create_line(disk_coords, fill="#3498db", width=2, smooth=True)
        if len(net_coords) >= 4:
            self.canvas.create_line(net_coords, fill="#2ecc71", width=2, smooth=True)

    def monitor_loop(self):
        while self.is_running:
            raw_net = self.get_network_speed()
            raw_disk = self.get_steam_disk_speed()

            net_mb = raw_net / (1024 * 1024)
            disk_mb = raw_disk / (1024 * 1024)

            try:
                threshold_mb = int(self.threshold_var.get()) / 1024
            except ValueError:
                threshold_mb = 50 / 1024

            self.net_history.append(net_mb)
            self.disk_history.append(disk_mb)
            self.net_history = self.net_history[-60:]
            self.disk_history = self.disk_history[-60:]

            new_state = self.current_state
            reason = ""

            if net_mb > threshold_mb:
                new_state = State.NETWORK
                self.stuck_timer = 0
            elif disk_mb > threshold_mb:
                new_state = State.PROCESSING
                self.stuck_timer = 0
            else:
                self.stuck_timer += 1
                # FIX: Correct order — STUCK while waiting, RECOVERY when limit exceeded
                if self.stuck_timer >= self.stuck_time_limit:
                    new_state = State.RECOVERY
                    reason = "Speed dropped below threshold."
                else:
                    new_state = State.STUCK

            if new_state != self.current_state or new_state == State.RECOVERY:
                self.write_log(new_state, net_mb, disk_mb, reason)
                self.current_state = new_state

            self.gui_queue.put({
                "net": net_mb,
                "disk": disk_mb,
                "state": self.current_state
            })

            # FIX: Run restart in its own thread — don't block monitor_loop
            if self.current_state == State.RECOVERY:
                self.gui_queue.put({"state": State.COOLDOWN})
                threading.Thread(
                    target=self.graceful_steam_restart, daemon=True
                ).start()
                self.stuck_timer = 0
                self.current_state = State.IDLE

            time.sleep(1)

    def process_queue(self):
        try:
            while True:
                data = self.gui_queue.get_nowait()
                lang = self.lang_var.get()
                if lang not in I18N:
                    lang = "English"
                texts = I18N[lang]

                if "net" in data and "disk" in data:
                    # فقط label عدد رو آپدیت کن — متن ثابته و درست نمایش داده میشه
                    self.lbl_speed_net_val.configure(text=f"{data['net']:.2f} MB/s")
                    self.lbl_speed_disk_val.configure(text=f"{data['disk']:.2f} MB/s")
                if "state" in data:
                    self.lbl_state.configure(text=data['state'].display(self.lang_var.get()))

                self.draw_graph()
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_queue)

    # ------------------------------------------
    # بخش 5: سیستم خاموشی هوشمند (Shutdown Logic)
    # ------------------------------------------
    def check_shutdown_timer(self):
        if self.shutdown_triggered:
            return
        # اگه همین روز لغو شده بود، تا فردا دیگه trigger نشه
        if getattr(self, "_shutdown_cancelled_today", "") == datetime.now().strftime("%Y-%m-%d"):
            return

        now = datetime.now()
        target_hour = self.hour_var.get()
        target_min = self.min_var.get()

        # اگه زمان روی 00:00 باشه یعنی کاربر تنظیم نکرده — چک نکن
        if target_hour == "00" and target_min == "00":
            self.after(10000, self.check_shutdown_timer)
            return

        # زمان هدف رو به دقیقه تبدیل کن
        target_total = int(target_hour) * 60 + int(target_min)
        now_total    = now.hour * 60 + now.minute

        # اگه زمان رسیده یا گذشته (تا ۵ دقیقه تاخیر قابل قبوله)
        # این یعنی حتی اگه یه چک از دست رفت، بار بعدی trigger میشه
        minutes_diff = (now_total - target_total) % (24 * 60)
        if 0 <= minutes_diff < 5:
            self.shutdown_triggered = True
            self.write_log(State.IDLE, 0, 0,
                f"Executing Auto-Shutdown (triggered at {now.strftime('%H:%M:%S')})")
            os.system("shutdown /s /t 60")
            if hasattr(self, 'btn_cancel_shutdown'):
                self.btn_cancel_shutdown.configure(state="normal")
            # نمایش countdown در label state
            if hasattr(self, 'lbl_state'):
                self.lbl_state.configure(text="⏻ Shutting down in 60s...")
            return  # دیگه reschedule نکن

        # هر ۱۰ ثانیه چک کن — به جای ۳۰ ثانیه — تا هیچ دقیقه‌ای miss نشه
        self.after(10000, self.check_shutdown_timer)

    def cancel_shutdown(self):
        os.system("shutdown /a")
        self.shutdown_triggered = False
        # ذخیره تاریخ لغو — جلوگیری از trigger مجدد همین روز
        self._shutdown_cancelled_today = datetime.now().strftime("%Y-%m-%d")
        self.write_log(State.IDLE, 0, 0, "Auto-Shutdown cancelled by user")
        # پاک کردن تاریخ از config تا روز بعد دوباره کار کنه
        self.save_settings()
        if hasattr(self, 'btn_cancel_shutdown'):
            self.btn_cancel_shutdown.configure(state="disabled")
        if hasattr(self, 'lbl_state'):
            self.lbl_state.configure(
                text=self.current_state.display(self.lang_var.get()))
        # ۶ دقیقه صبر کن تا از پنجره ۵ دقیقه‌ای خارج بشیم، بعد دوباره چک کن
        self.after(360000, self.check_shutdown_timer)

    def start_monitoring(self):
        # Show warning instead of silently blocking when Steam path is missing
        if not self.steam_var.get():
            if hasattr(self, "lbl_warning"):
                self.lbl_warning.configure(text=I18N.get(self.lang_var.get(), I18N["English"])["warning_no_path"])
                self.after(3000, lambda: self.lbl_warning.configure(text=""))
            return
        if hasattr(self, "lbl_warning"):
            self.lbl_warning.configure(text="")
        self.is_running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.current_state = State.IDLE
        self.stuck_timer = 0
        self.net_history = [0] * 60
        self.disk_history = [0] * 60
        # Reset per-PID disk snapshot on fresh start
        self._pid_disk_snapshot = {}
        if hasattr(self, '_last_disk_time'):
            del self._last_disk_time
        threading.Thread(target=self.monitor_loop, daemon=True).start()

    def stop_monitoring(self):
        self.is_running = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.current_state = State.IDLE
        self.lbl_state.configure(text=self.current_state.display(self.lang_var.get()))


if __name__ == "__main__":
    app = SteamDownloaderApp()
    app.mainloop()