import os
from dotenv import load_dotenv
load_dotenv()

import re
import json
import time
import threading
import queue
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox, simpledialog
from tkinter.filedialog import asksaveasfilename
import parser
from utils import DEFAULTS

# ==================== GUI ====================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Avito Parser")
        self.geometry("940x820")
        self.minsize(840, 700)
        self.resizable(True, True)
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.stop_event = threading.Event()
        self.parser_thread = None
        self.log_queue = queue.Queue()
        self.current_profile = None

        self.is_infinite = False
        self.cycle_complete = False
        self.create_widgets()
        self.update_idletasks()
        self.refresh_profiles_list()
        self.after(100, self.process_log_queue)

        self.load_gui_state()
        self.bind("<Configure>", self.on_configure)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_profiles_frame(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=12, pady=(10, 10))
        ctk.CTkLabel(frame, text="Профили настроек", font=ctk.CTkFont(size=14, weight="bold")).pack()

        prof_row = ctk.CTkFrame(frame, fg_color="transparent")
        prof_row.pack(fill="x", pady=(10, 5))
        self.profile_combo = ctk.CTkComboBox(prof_row, values=["(нет)"], width=200, state="readonly")
        self.profile_combo.pack(side="left", fill="x", expand=True)
        self.profile_combo.set("(нет)")
        ctk.CTkButton(prof_row, text="📂", width=36, command=self.load_profile).pack(side="left", padx=(4, 0))

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x")
        ctk.CTkButton(btn_row, text="💾 Сохранить", width=110, command=self.save_profile).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_row, text="💾 Как…", width=70, command=self.save_profile_as).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_row, text="🗑", width=36, fg_color="#c0392b", hover_color="#a93226", command=self.delete_profile).pack(side="left")
        return frame

    def create_settings_frame(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        ctk.CTkLabel(frame, text="Настройки поиска", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(0, 8))

        # URL
        ctk.CTkLabel(frame, text="URL (каждый с новой строки):").pack(anchor="w")
        self.urls_text = ctk.CTkTextbox(frame, height=55)
        self.urls_text.pack(fill="x", pady=(0, 6))
        self.bind_context_menu(self.urls_text)

        # Числовые фильтры
        filters = [
            ("Макс. цена ₽:", "max_price", DEFAULTS["MAX_PRICE"]),
            ("Макс. страниц:", "max_pages", DEFAULTS["MAX_PAGES"]),
            ("Макс. возраст (дни):", "max_age", DEFAULTS["MAX_DAYS_AGE"]),
        ]
        self.entries = {}
        for label, attr, default in filters:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label).pack(side="left")
            entry = ctk.CTkEntry(row, width=100)
            entry.pack(side="right")
            self.entries[attr.replace("-", "_")] = entry
            self.bind_context_menu(entry)

        # Белый список
        ctk.CTkLabel(frame, text="Белый список слов\n(требовать наличие, каждый с новой строки):").pack(anchor="w", pady=(8, 0))
        self.whitelist_text = ctk.CTkTextbox(frame, height=60)
        self.whitelist_text.pack(fill="x", pady=(0, 6))
        self.bind_context_menu(self.whitelist_text)

        # Чёрные списки
        ctk.CTkLabel(frame, text="Чёрный список продавцов\n(каждый с новой строки):").pack(anchor="w", pady=(8, 0))
        self.sellers_text = ctk.CTkTextbox(frame, height=60)
        self.sellers_text.pack(fill="x", pady=(0, 6))
        self.bind_context_menu(self.sellers_text)

        ctk.CTkLabel(frame, text="Чёрный список слов\n(в заголовке/тексте):").pack(anchor="w")
        self.words_text = ctk.CTkTextbox(frame, height=60)
        self.words_text.pack(fill="x", pady=(0, 8))
        self.bind_context_menu(self.words_text)

        # Лист новых объявлений
        ctk.CTkLabel(frame, text="Лист новых:").pack(anchor="w")
        self.target_sheet_entry = ctk.CTkEntry(frame, placeholder_text="Новые")
        self.target_sheet_entry.pack(fill="x", pady=(0, 8))
        self.bind_context_menu(self.target_sheet_entry)

        # Режим парсинга
        ctk.CTkLabel(frame, text="Режим парсинга", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(12, 4))

        inf_row = ctk.CTkFrame(frame, fg_color="transparent")
        inf_row.pack(fill="x", pady=2)

        self.infinite_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(inf_row, text="Бесконечный режим", variable=self.infinite_var).pack(side="left")

        ctk.CTkLabel(inf_row, text="Интервал (мин):").pack(side="left", padx=(10, 2))
        self.interval_entry = ctk.CTkEntry(inf_row, width=60)
        self.interval_entry.insert(0, "30")
        self.interval_entry.pack(side="left")

        self.new_sheet_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame, text="Второй лист 'Новые' для новых объявлений", variable=self.new_sheet_var).pack(anchor="w", pady=(4, 0))
        return frame

    def create_buttons_frame(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=12, pady=(0, 10))
        self.start_btn = ctk.CTkButton(
            frame, text="▶ Запустить парсер", height=40,
            command=self.start_parser, fg_color="#2ecc71", hover_color="#27ae60"
        )
        self.start_btn.pack(fill="x", pady=(0, 5))

        self.stop_btn = ctk.CTkButton(
            frame, text="⏹ Остановить", height=40,
            command=self.stop_parser, fg_color="#e74c3c", hover_color="#c0392b", state="disabled"
        )
        self.stop_btn.pack(fill="x")
        return frame


    def create_widgets(self):
        # Левая панель
        left = ctk.CTkFrame(self, width=370)
        left.pack(side="left", fill="y", padx=10, pady=10)
        left.pack_propagate(False)

        self.create_profiles_frame(left)
        self.create_settings_frame(left)
        self.create_buttons_frame(left)

        # Правая панель — лог
        right = ctk.CTkFrame(self)
        right.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=10)
        ctk.CTkLabel(right, text="Лог работы", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5))
        self.log_box = ctk.CTkTextbox(right, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.bind_context_menu(self.log_box)
        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.pack(pady=(0, 10))
        ctk.CTkButton(btn_row, text="Очистить лог", width=120, command=lambda: self.log_box.delete("1.0", "end")).pack(side="left")
        ctk.CTkButton(btn_row, text="📋 Копировать", width=100, command=self.copy_log).pack(side="left", padx=(10, 5))
        ctk.CTkButton(btn_row, text="💾 Сохранить", width=100, command=self.save_log).pack(side="left")

    def bind_context_menu(self, ctk_widget):
        """ПКМ + Ctrl для CTkEntry/CTkTextbox."""
        inner = None
        if hasattr(ctk_widget, '_entry'):
            inner = ctk_widget._entry
        elif hasattr(ctk_widget, '_textbox'):
            inner = ctk_widget._textbox
        elif hasattr(ctk_widget, '_text_frame') and hasattr(ctk_widget._text_frame, '_textbox'):
            inner = ctk_widget._text_frame._textbox
        if not inner:
            return

        def focus_and_copy():
            inner.focus_set()
            inner.event_generate("<<Copy>>")

        def focus_and_paste():
            inner.focus_set()
            inner.event_generate("<<Paste>>")

        def focus_and_cut():
            inner.focus_set()
            inner.event_generate("<<Cut>>")

        def focus_and_select_all():
            inner.focus_set()
            inner.event_generate("<<SelectAll>>")

        def show_menu(e):
            inner.focus_set()
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(label="Вырезать", command=focus_and_cut)
            menu.add_command(label="Копировать", command=focus_and_copy)
            menu.add_command(label="Вставить", command=focus_and_paste)
            menu.add_separator()
            menu.add_command(label="Выделить всё", command=focus_and_select_all)
            try:
                menu.tk_popup(e.x_root, e.y_root)
            finally:
                menu.grab_release()

        ctk_widget.bind("<Button-3>", show_menu)
        inner.bind("<Control-c>", lambda e: focus_and_copy() or "break")
        inner.bind("<Control-v>", lambda e: focus_and_paste() or "break")
        inner.bind("<Control-x>", lambda e: focus_and_cut() or "break")
        inner.bind("<Control-a>", lambda e: focus_and_select_all() or "break")
        ctk_widget.bind("<Control-c>", lambda e: focus_and_copy() or "break")
        ctk_widget.bind("<Control-v>", lambda e: focus_and_paste() or "break")
        ctk_widget.bind("<Control-x>", lambda e: focus_and_cut() or "break")
        ctk_widget.bind("<Control-a>", lambda e: focus_and_select_all() or "break")

    def list_profiles(self):
        prof_dir = DEFAULTS["PROFILES_DIR"]
        if not os.path.isdir(prof_dir):
            return []
        return sorted(f[:-5] for f in os.listdir(prof_dir) if f.endswith(".json"))

    def refresh_profiles_list(self):
        names = self.list_profiles()
        values = ["(нет)"] + names if names else ["(нет)"]
        self.profile_combo.configure(values=values)
        if self.current_profile and self.current_profile in names:
            self.profile_combo.set(self.current_profile)
        else:
            self.profile_combo.set("(нет)")
            self.current_profile = None

    def get_config(self):
        return {
            "URLS": self.urls_text.get("1.0", "end").strip(),
            "MAX_PRICE": self.entries["max_price"].get().strip(),
            "MAX_PAGES": self.entries["max_pages"].get().strip(),
            "MAX_DAYS_AGE": self.entries["max_age"].get().strip(),
            "WHITELIST_WORDS": self.whitelist_text.get("1.0", "end").strip(),
            "BLACKLIST_SELLERS": self.sellers_text.get("1.0", "end").strip(),
            "BLACKLIST_WORDS": self.words_text.get("1.0", "end").strip(),
            "TARGET_SHEET_NAME": self.target_sheet_entry.get().strip(),
            "INFINITE_LOOP": self.infinite_var.get(),
            "LOOP_INTERVAL_MIN": self.interval_entry.get() or "30",
            "NEW_SHEET": self.new_sheet_var.get(),
        }

    def apply_config(self, cfg: dict):
        self.urls_text.delete("1.0", "end")
        self.urls_text.insert("1.0", cfg.get("URLS", ""))
        self.entries["max_price"].delete(0, "end")
        self.entries["max_price"].insert(0, cfg.get("MAX_PRICE", ""))
        self.entries["max_pages"].delete(0, "end")
        self.entries["max_pages"].insert(0, cfg.get("MAX_PAGES", ""))
        self.entries["max_age"].delete(0, "end")
        self.entries["max_age"].insert(0, cfg.get("MAX_DAYS_AGE", ""))
        self.whitelist_text.delete("1.0", "end")
        self.whitelist_text.insert("1.0", cfg.get("WHITELIST_WORDS", ""))
        self.sellers_text.delete("1.0", "end")
        self.sellers_text.insert("1.0", cfg.get("BLACKLIST_SELLERS", ""))
        self.words_text.delete("1.0", "end")
        self.words_text.insert("1.0", cfg.get("BLACKLIST_WORDS", ""))
        self.target_sheet_entry.delete(0, "end")
        self.target_sheet_entry.insert(0, cfg.get("TARGET_SHEET_NAME", "Новые"))
        self.infinite_var.set(cfg.get("INFINITE_LOOP", False))
        self.interval_entry.delete(0, "end")
        self.interval_entry.insert(0, cfg.get("LOOP_INTERVAL_MIN", "30"))
        self.new_sheet_var.set(cfg.get("NEW_SHEET", False))

    def _safe_filename(self, name: str) -> str:
        name = name.strip()
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        return name[:80] if name else ""

    def save_profile(self):
        if self.current_profile:
            self._write_profile(self.current_profile)
            self.log(f"💾 Профиль «{self.current_profile}» сохранён.")
        else:
            self.save_profile_as()

    def save_profile_as(self):
        name = simpledialog.askstring("Сохранить профиль как…", "Имя профиля:", parent=self)
        if not name:
            return
        name = self._safe_filename(name)
        if not name:
            messagebox.showerror("Ошибка", "Некорректное имя")
            return
        path = os.path.join(DEFAULTS["PROFILES_DIR"], f"{name}.json")
        if os.path.exists(path):
            if not messagebox.askyesno("Перезаписать?", f"Профиль «{name}» уже есть. Перезаписать?"):
                return
        self._write_profile(name)
        self.current_profile = name
        self.refresh_profiles_list()
        self.log(f"💾 Профиль «{name}» сохранён.")

    def _write_profile(self, name: str):
        path = os.path.join(DEFAULTS["PROFILES_DIR"], f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.get_config(), f, ensure_ascii=False, indent=2)

    def load_profile(self):
        name = self.profile_combo.get()
        if not name or name == "(нет)":
            messagebox.showinfo("Профиль", "Выберите профиль из списка")
            return
        path = os.path.join(DEFAULTS["PROFILES_DIR"], f"{name}.json")
        if not os.path.exists(path):
            messagebox.showerror("Ошибка", f"Файл профиля не найден:\n{path}")
            self.refresh_profiles_list()
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.apply_config(cfg)
            self.current_profile = name
            self.log(f"📂 Загружен профиль «{name}»")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить профиль:\n{e}")

    def delete_profile(self):
        name = self.profile_combo.get()
        if not name or name == "(нет)":
            messagebox.showinfo("Удаление", "Выберите профиль для удаления")
            return
        if not messagebox.askyesno("Удалить?", f"Удалить профиль «{name}»?"):
            return
        path = os.path.join(DEFAULTS["PROFILES_DIR"], f"{name}.json")
        try:
            os.remove(path)
            if self.current_profile == name:
                self.current_profile = None
            self.refresh_profiles_list()
            self.log(f"🗑 Профиль «{name}» удалён")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    # ---------- Лог и запуск ----------
    def log(self, msg):
        self.log_queue.put(msg)

    def process_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get()
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            if self.is_infinite and "Цикл завершён" in msg:
                interval_min = int(self.get_config().get("LOOP_INTERVAL_MIN", 30))
                self.remaining_sec = interval_min * 60
                self.update_timer()
        self.after(100, self.process_log_queue)

    def copy_log(self):
        text = self.log_box.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log("📋 Лог скопирован в буфер обмена!")

    def save_log(self):
        filename = asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Сохранить лог"
        )
        if filename:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(self.log_box.get("1.0", "end"))
            self.log(f"💾 Лог сохранён: {filename}")

    def start_parser(self):
        if self.parser_thread and self.parser_thread.is_alive():
            return
        config = self.get_config()
        if not config["URLS"]:
            messagebox.showerror("Ошибка", "Укажите хотя бы один URL")
            return
        creds_file = DEFAULTS["CREDENTIALS_FILE"]
        if not os.path.exists(creds_file):
            messagebox.showerror("Ошибка", f"Файл {creds_file} не найден")
            return

        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.is_infinite = config.get("INFINITE_LOOP", False)
        self.log("🚀 Запуск парсера...\n")

        parser_instance = parser.AvitoParser(config, self.log, self.stop_event)
        self.parser_thread = threading.Thread(target=self._run_parser, args=(parser_instance,), daemon=True)
        self.parser_thread.start()

    def _run_parser(self, parser_instance):
        try:
            parser_instance.run()
        finally:
            self.after(0, self._on_parser_finished)

    def update_timer(self):
        if self.remaining_sec > 0:
            mins, secs = divmod(self.remaining_sec, 60)
            self.start_btn.configure(text=f"⏳ {mins:02d}:{secs:02d}")
            self.remaining_sec -= 1
            self.after(1000, self.update_timer)
        else:
            self.start_btn.configure(text="▶ Запустить парсер")

    def _on_parser_finished(self):
        self.start_btn.configure(state="normal", text="▶ Запустить парсер")
        self.stop_btn.configure(state="disabled")
        self.remaining_sec = 0
        self.log("\n——— Парсер остановлен ———\n")

    def stop_parser(self):
        self.stop_event.set()
        self.log("⏹ Запрошена остановка...")
        self.stop_btn.configure(state="disabled")
        self.remaining_sec = 0
        self.start_btn.configure(text="▶ Запустить парсер")

    def load_gui_state(self):
        path = "gui_state.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                self.geometry(state.get("geometry", "940x820"))
                if state.get("state"):
                    self.state(state["state"])
                self.log(f"📐 Окно восстановлено: {state.get('geometry')}")
            except Exception as e:
                self.log(f"⚠️ Ошибка загрузки состояния окна: {e}")

    def save_gui_state(self):
        path = "gui_state.json"
        state = {
            "geometry": self.geometry(),
            "state": self.state()
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"⚠️ Ошибка сохранения состояния окна: {e}")

    def on_configure(self, e):
        if e.widget is self:
            self.after_idle(self.save_gui_state)

    def on_closing(self):
        self.save_gui_state()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
