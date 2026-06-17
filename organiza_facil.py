# ==========================================
# IMPORTS
# ==========================================

import os
import shutil
import json
import hashlib
import sqlite3
import threading
import time
import sys
import webbrowser
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import customtkinter as ctk
from tkinter import filedialog, messagebox

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import matplotlib
matplotlib.use('Agg') # Define o backend para não interferir na janela principal (Fix do ícone)
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# ==========================================
# CONFIG & DESIGN SYSTEM
# ==========================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Caminhos de Dados
DATA_DIR = os.path.join(os.path.expanduser("~"), ".organiza_facil")
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE = os.path.join(DATA_DIR, "cache.db")
CONFIG_FILE = os.path.join(DATA_DIR, "settings.json")

COLORS = {
    "bg": "#0F172A",      # Slate 900
    "sidebar": "#1E293B", # Slate 800
    "card": "#334155",    # Slate 700
    "accent": "#3B82F6",  # Blue 500
    "success": "#10B981", # Emerald 500
    "warning": "#F59E0B", # Amber 500
    "danger": "#EF4444",  # Red 500
    "info": "#0EA5E9",    # Sky 500 (Adicionado para corrigir o erro)
    "text_main": "#F8FAFC",
    "text_dim": "#94A3B8"
}

# ==========================================
# UTILS & CACHE
# ==========================================

class CacheManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.enabled = True
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS file_cache (path TEXT PRIMARY KEY, hash TEXT, mtime REAL, size INTEGER)")
                conn.commit()
        except: self.enabled = False

    def get_cached_hash(self, path, mtime, size):
        if not self.enabled: return None
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT hash FROM file_cache WHERE path = ? AND mtime = ? AND size = ?", (path, mtime, size))
                row = cursor.fetchone()
                return row[0] if row else None
        except: return None

    def update_cache(self, path, file_hash, mtime, size):
        if not self.enabled: return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("INSERT OR REPLACE INTO file_cache VALUES (?, ?, ?, ?)", (path, file_hash, mtime, size))
                conn.commit()
        except: pass

# ==========================================
# MONITOR
# ==========================================

class FolderMonitor(FileSystemEventHandler):
    def __init__(self, app):
        self.app = app
    def on_created(self, event):
        if not event.is_directory:
            time.sleep(0.5)
            self.app.after(0, self.app.organize_files)

# ==========================================
# APLICAÇÃO ORGANIZA FÁCIL
# ==========================================

class OrganizaFacilApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title("Organiza Fácil - Inteligência em Arquivos")
        self.geometry("1150x800")
        self.minsize(900, 650)
        self.configure(fg_color=COLORS["bg"])

        # Carregar Ícone da Janela (Compatível com Windows/Mac e Executável)
        try:
            from PIL import Image, ImageTk
            
            # Lógica ultra-robusta para encontrar o ícone
            if hasattr(sys, '_MEIPASS'):
                base_path = sys._MEIPASS
            else:
                # Tenta o diretório do script, depois o diretório atual
                base_path = os.path.dirname(os.path.abspath(__file__))
            
            icon_path_ico = os.path.join(base_path, "icon.ico")
            icon_path_png = os.path.join(base_path, "icon.png")
            
            # Se não achou no diretório do script, tenta na pasta atual (fallback)
            if not os.path.exists(icon_path_png):
                icon_path_png = os.path.join(os.getcwd(), "icon.png")
            if not os.path.exists(icon_path_ico):
                icon_path_ico = os.path.join(os.getcwd(), "icon.ico")
            
            if os.path.exists(icon_path_ico) and sys.platform.startswith('win'):
                self.iconbitmap(icon_path_ico)
            elif os.path.exists(icon_path_png):
                img = Image.open(icon_path_png)
                photo = ImageTk.PhotoImage(img)
                self.wm_iconphoto(True, photo)
        except Exception as e:
            print(f"Erro ao carregar ícone: {e}")

        # Estado
        self.folder = ""
        self.history_actions = []
        self.is_processing = False
        self.current_tab = "Dashboard"
        
        # Recursos
        self.cache = CacheManager(DB_FILE)
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.observer = None
        self.auto_mode = ctk.BooleanVar(value=False)

        # Configurações de Extensões
        self.default_types = {
            "Imagens": [".jpg", ".png", ".jpeg", ".gif", ".webp", ".svg", ".bmp"],
            "Documentos": [".pdf", ".docx", ".txt", ".xlsx", ".pptx", ".odt", ".csv"],
            "Vídeos": [".mp4", ".mov", ".avi", ".mkv", ".wmv"],
            "Código": [".py", ".js", ".html", ".css", ".json", ".ts", ".cpp", ".java"],
            "Áudio": [".mp3", ".wav", ".flac", ".m4a"],
            "Compactados": [".zip", ".rar", ".7z", ".tar", ".gz"]
        }
        self.types = self.default_types.copy()
        self.load_settings()

        self.build_ui()

    def load_settings(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    self.types = json.load(f)
            except: pass

    def save_settings(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.types, f, indent=4)
        except: pass

    # ==========================================
    # UI RESPONSIVA
    # ==========================================

    def build_ui(self):
        # Configuração da Grid Principal
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar Lateral
        self.sidebar = ctk.CTkFrame(self, width=240, corner_radius=0, fg_color=COLORS["sidebar"])
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)

        # Logo e Título
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(pady=(40, 30), padx=20, fill="x")
        
        ctk.CTkLabel(logo_frame, text="✨ Organiza Fácil", font=("Segoe UI", 22, "bold"), text_color=COLORS["accent"]).pack(anchor="w")
        ctk.CTkLabel(logo_frame, text="Sua pasta, seu controle.", font=("Segoe UI", 12), text_color=COLORS["text_dim"]).pack(anchor="w")

        # Botões de Navegação
        self.nav_btns = {}
        self.create_nav_btn("🏠 Início", "Dashboard")
        self.create_nav_btn("⚡ Organizar", "Organize")
        self.create_nav_btn("🔍 Limpar Duplicados", "Duplicates")
        self.create_nav_btn("⚙ Ajustes", "Settings")
        self.create_nav_btn("📊 Relatórios", "Stats")

        # Info de Versão, Assinatura e GitHub
        footer_sidebar = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer_sidebar.pack(side="bottom", pady=20, padx=20, fill="x")
        
        # Assinatura do Desenvolvedor
        ctk.CTkLabel(footer_sidebar, text="Desenvolvido por", font=("Segoe UI", 10), text_color=COLORS["text_dim"]).pack()
        ctk.CTkLabel(footer_sidebar, text="Murilo Silva", font=("Segoe UI", 12, "bold"), text_color=COLORS["accent"]).pack(pady=(0, 10))

        version_frame = ctk.CTkFrame(footer_sidebar, fg_color="transparent")
        version_frame.pack(fill="x")
        ctk.CTkLabel(version_frame, text="v1.1.0 Pro", font=("Segoe UI", 10), text_color=COLORS["text_dim"]).pack(side="left")
        ctk.CTkButton(version_frame, text="GitHub", font=("Segoe UI", 10, "bold"), fg_color="transparent", text_color=COLORS["accent"], hover_color="#2D3748", width=60, command=lambda: webbrowser.open("https://github.com")).pack(side="right")

        # Área de Conteúdo (Responsiva)
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.show_tab("Dashboard")

    def create_nav_btn(self, text, tab_name):
        btn = ctk.CTkButton(
            self.sidebar, 
            text=text, 
            anchor="w", 
            height=45, 
            font=("Segoe UI", 14),
            fg_color="transparent", 
            hover_color="#334155", 
            corner_radius=8,
            command=lambda: self.show_tab(tab_name)
        )
        btn.pack(pady=4, padx=15, fill="x")
        self.nav_btns[tab_name] = btn

    def show_tab(self, tab_name):
        # Atualizar visual dos botões
        for name, btn in self.nav_btns.items():
            btn.configure(fg_color="transparent" if name != tab_name else COLORS["accent"],
                          text_color=COLORS["text_main"] if name != tab_name else "white")
        
        # Limpar conteúdo anterior
        for widget in self.content.winfo_children():
            widget.destroy()

        # Renderizar aba
        if tab_name == "Dashboard": self.render_dashboard()
        elif tab_name == "Organize": self.render_organize()
        elif tab_name == "Duplicates": self.render_duplicates()
        elif tab_name == "Settings": self.render_settings()
        elif tab_name == "Stats": self.render_stats()

    # ==========================================
    # DASHBOARD MODERNO
    # ==========================================

    def render_dashboard(self):
        container = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        container.pack(fill="both", expand=True)

        # Boas vindas
        ctk.CTkLabel(container, text="Olá! O que vamos organizar hoje?", font=("Segoe UI", 28, "bold"), text_color=COLORS["text_main"]).pack(pady=(20, 5), anchor="w")
        ctk.CTkLabel(container, text="Selecione uma ação rápida abaixo para começar.", font=("Segoe UI", 14), text_color=COLORS["text_dim"]).pack(pady=(0, 30), anchor="w")

        # Grid de Ações Rápidas (Responsivo)
        actions_grid = ctk.CTkFrame(container, fg_color="transparent")
        actions_grid.pack(fill="x", pady=10)
        actions_grid.grid_columnconfigure((0, 1, 2), weight=1)

        self.create_action_card(actions_grid, "⚡", "Organização Rápida", "Mova arquivos para pastas categorizadas.", COLORS["success"], 0, lambda: self.show_tab("Organize"))
        self.create_action_card(actions_grid, "🔍", "Limpeza Inteligente", "Remova arquivos duplicados e economize espaço.", COLORS["info"], 1, lambda: self.show_tab("Duplicates"))
        self.create_action_card(actions_grid, "⚙", "Personalizar", "Configure suas próprias extensões e pastas.", COLORS["warning"], 2, lambda: self.show_tab("Settings"))

        # Status do Sistema
        ctk.CTkLabel(container, text="Status do Sistema", font=("Segoe UI", 18, "bold"), text_color=COLORS["text_main"]).pack(pady=(40, 20), anchor="w")
        
        status_frame = ctk.CTkFrame(container, fg_color=COLORS["sidebar"], corner_radius=15)
        status_frame.pack(fill="x", pady=10)
        
        # Grid de Status
        status_frame.grid_columnconfigure((0, 1, 2), weight=1)
        self.create_status_item(status_frame, "Pasta Ativa", self.folder or "Nenhuma selecionada", 0)
        self.create_status_item(status_frame, "Performance", "Cache SQLite Ativo" if self.cache.enabled else "Modo Simples", 1)
        self.create_status_item(status_frame, "Monitoramento", "Ligado" if self.auto_mode.get() else "Desligado", 2)

    def create_action_card(self, parent, icon, title, desc, color, col, command):
        card = ctk.CTkFrame(parent, fg_color=COLORS["sidebar"], corner_radius=15, height=200)
        card.grid(row=0, column=col, padx=10, sticky="nsew")
        card.grid_propagate(False)
        
        ctk.CTkLabel(card, text=icon, font=("Segoe UI", 40)).pack(pady=(25, 10))
        ctk.CTkLabel(card, text=title, font=("Segoe UI", 16, "bold")).pack(pady=2)
        ctk.CTkLabel(card, text=desc, font=("Segoe UI", 11), text_color=COLORS["text_dim"], wraplength=180).pack(pady=5, padx=15)
        
        btn = ctk.CTkButton(card, text="Acessar", fg_color=color, height=32, corner_radius=8, command=command)
        btn.pack(side="bottom", pady=20, padx=20, fill="x")

    def create_status_item(self, parent, label, value, col):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=col, pady=25, padx=20, sticky="nsew")
        ctk.CTkLabel(frame, text=label, font=("Segoe UI", 12, "bold"), text_color=COLORS["accent"]).pack()
        ctk.CTkLabel(frame, text=value, font=("Segoe UI", 11), text_color=COLORS["text_main"], wraplength=200).pack(pady=5)

    # ==========================================
    # ABA ORGANIZAR (RESPONSIVA)
    # ==========================================

    def render_organize(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(frame, text="Central de Organização", font=("Segoe UI", 24, "bold")).pack(pady=(0, 20), anchor="w")

        # Seleção de Pasta (Card)
        folder_card = ctk.CTkFrame(frame, fg_color=COLORS["sidebar"], corner_radius=15)
        folder_card.pack(fill="x", pady=10)
        
        ctk.CTkButton(folder_card, text="📁 Escolher Pasta", command=self.select_folder, fg_color=COLORS["accent"], height=40).pack(side="left", padx=20, pady=20)
        self.path_lbl = ctk.CTkLabel(folder_card, text=self.folder or "Por favor, selecione a pasta que deseja organizar...", font=("Segoe UI", 13), text_color=COLORS["text_dim"])
        self.path_lbl.pack(side="left", padx=10)

        # Barra de Progresso e Ações
        actions_bar = ctk.CTkFrame(frame, fg_color="transparent")
        actions_bar.pack(fill="x", pady=20)

        ctk.CTkButton(actions_bar, text="🚀 Começar Organização", fg_color=COLORS["success"], font=("Segoe UI", 14, "bold"), height=45, width=220, command=self.start_organize_thread).pack(side="left")
        ctk.CTkButton(actions_bar, text="↩ Desfazer", fg_color="transparent", border_width=1, border_color=COLORS["warning"], text_color=COLORS["warning"], height=45, width=120, command=self.undo).pack(side="left", padx=15)
        
        ctk.CTkSwitch(actions_bar, text="Monitorar em tempo real", variable=self.auto_mode, command=self.toggle_auto, progress_color=COLORS["success"], font=("Segoe UI", 12)).pack(side="right")

        # Log Console
        ctk.CTkLabel(frame, text="Console de Atividades", font=("Segoe UI", 14, "bold"), text_color=COLORS["text_dim"]).pack(pady=(10, 5), anchor="w")
        self.log_box = ctk.CTkTextbox(frame, fg_color="#020617", border_color=COLORS["card"], border_width=1, font=("Consolas", 12), corner_radius=10)
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    # ==========================================
    # LÓGICA CORE
    # ==========================================

    def add_log(self, text, level="INFO"):
        if not hasattr(self, 'log_box'): return
        time_str = datetime.now().strftime("%H:%M:%S")
        prefix = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌"}.get(level, "•")
        msg = f"{prefix} [{time_str}] {text}\n"
        
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def select_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.folder = path
            if hasattr(self, 'path_lbl'): self.path_lbl.configure(text=path, text_color=COLORS["text_main"])
            self.add_log(f"Pasta ativa definida: {path}", "INFO")

    def start_organize_thread(self):
        if not self.folder: return messagebox.showwarning("Aviso", "Você precisa selecionar uma pasta primeiro!")
        threading.Thread(target=self.organize_files, daemon=True).start()

    def organize_files(self):
        try:
            # Proteção contra pastas de sistema críticas (Segurança)
            restricted_folders = ["C:\\Windows", "/System", "/bin", "/sbin", "/etc"]
            if any(self.folder.startswith(res) for res in restricted_folders):
                self.add_log("Acesso negado: Esta é uma pasta crítica do sistema.", "ERROR")
                messagebox.showerror("Segurança", "Por segurança, o Organiza Fácil não pode modificar pastas do sistema.")
                return

            entries = [e for e in os.scandir(self.folder) if e.is_file()]
            if not entries: return self.add_log("A pasta selecionada está vazia.", "WARNING")
            
            history = []
            self.add_log(f"Iniciando varredura em {len(entries)} arquivos...", "INFO")
            
            for entry in entries:
                try:
                    ext = os.path.splitext(entry.name)[1].lower()
                    moved = False
                    for cat, exts in self.types.items():
                        if ext in exts:
                            dest_dir = os.path.join(self.folder, cat)
                            os.makedirs(dest_dir, exist_ok=True)
                            dest_path = os.path.join(dest_dir, entry.name)
                            
                            if os.path.exists(dest_path):
                                n, e = os.path.splitext(entry.name)
                                dest_path = os.path.join(dest_dir, f"{n}_{int(time.time())}{e}")
                            
                            shutil.move(entry.path, dest_path)
                            history.append((dest_path, entry.path))
                            self.add_log(f"Movido: {entry.name} para {cat}", "SUCCESS")
                            moved = True
                            break
                    
                    if not moved:
                        others = os.path.join(self.folder, "Outros")
                        os.makedirs(others, exist_ok=True)
                        dest_path = os.path.join(others, entry.name)
                        shutil.move(entry.path, dest_path)
                        history.append((dest_path, entry.path))
                
                except PermissionError:
                    self.add_log(f"Sem permissão para mover: {entry.name}", "WARNING")
                except Exception as e:
                    self.add_log(f"Erro ao processar {entry.name}: {e}", "ERROR")

            if history:
                self.history_actions.append(history)
                self.add_log("Tudo pronto! Sua pasta está organizada.", "SUCCESS")
            else:
                self.add_log("Nenhum arquivo pôde ser movido.", "WARNING")

        except PermissionError:
            self.add_log("Erro de Permissão: Execute como Administrador ou escolha outra pasta.", "ERROR")
        except Exception as e: 
            self.add_log(f"Erro inesperado: {e}", "ERROR")

    def undo(self):
        if not self.history_actions: return messagebox.showinfo("Desfazer", "Não há ações recentes para reverter.")
        last = self.history_actions.pop()
        for curr, orig in last:
            try: shutil.move(curr, orig)
            except: pass
        self.add_log(f"Ação revertida com sucesso. {len(last)} arquivos restaurados.", "INFO")

    def toggle_auto(self):
        if self.auto_mode.get():
            if not self.folder: 
                self.auto_mode.set(False)
                return messagebox.showwarning("Aviso", "Selecione uma pasta para ativar o monitoramento automático.")
            self.observer = Observer()
            self.observer.schedule(FolderMonitor(self), self.folder, recursive=False)
            self.observer.start()
            self.add_log("Monitoramento em tempo real ATIVADO.", "SUCCESS")
        else:
            if self.observer: self.observer.stop()
            self.add_log("Monitoramento em tempo real DESATIVADO.", "INFO")

    # ==========================================
    # OUTRAS TELAS (SIMPLIFICADAS PARA DESIGN)
    # ==========================================

    def render_settings(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.pack(fill="both", expand=True)
        ctk.CTkLabel(frame, text="Ajustes de Categorias", font=("Segoe UI", 24, "bold")).pack(pady=(0, 20), anchor="w")
        
        scroll = ctk.CTkScrollableFrame(frame, fg_color=COLORS["sidebar"], corner_radius=15)
        scroll.pack(fill="both", expand=True)

        for cat, exts in self.types.items():
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=8, padx=15)
            ctk.CTkLabel(row, text=cat, font=("Segoe UI", 14, "bold"), width=140, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(row, fg_color=COLORS["bg"], border_color=COLORS["card"], width=450)
            entry.insert(0, ", ".join(exts))
            entry.pack(side="left", padx=15)
            
            def save_factory(c=cat, e=entry):
                self.types[c] = [x.strip() for x in e.get().split(",") if x.strip()]
                self.save_settings()
                self.add_log(f"Configurações de '{c}' salvas.", "SUCCESS")
            
            ctk.CTkButton(row, text="Salvar", width=80, fg_color=COLORS["card"], hover_color=COLORS["accent"], command=save_factory).pack(side="right")

    def render_duplicates(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.pack(fill="both", expand=True)
        ctk.CTkLabel(frame, text="Limpeza de Duplicados", font=("Segoe UI", 24, "bold")).pack(pady=(0, 10), anchor="w")
        ctk.CTkLabel(frame, text="Nossa IA analisa o conteúdo real dos arquivos, não apenas o nome.", font=("Segoe UI", 13), text_color=COLORS["text_dim"]).pack(pady=(0, 30), anchor="w")
        
        ctk.CTkButton(frame, text="🔍 Iniciar Varredura Inteligente", fg_color=COLORS["accent"], font=("Segoe UI", 16, "bold"), height=50, width=300, command=self.start_duplicate_thread).pack(pady=20)
        self.log_box = ctk.CTkTextbox(frame, fg_color="#020617", font=("Consolas", 12), corner_radius=10)
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    def start_duplicate_thread(self):
        if not self.folder: return messagebox.showwarning("Aviso", "Selecione uma pasta primeiro!")
        threading.Thread(target=self.smart_duplicates, daemon=True).start()

    def smart_duplicates(self):
        # Lógica inteligente de duplicados (mesma do Pro v2)
        self.add_log("Iniciando varredura inteligente de duplicados...", "INFO")
        size_map = defaultdict(list)
        for root, _, files in os.walk(self.folder):
            if "Duplicados_Detectados" in root: continue
            for f in files:
                p = os.path.join(root, f)
                try: size_map[os.path.getsize(p)].append(p)
                except: continue
        candidates = [p for paths in size_map.values() if len(paths) > 1 for p in paths]
        if not candidates: return self.add_log("Excelente! Nenhum arquivo duplicado encontrado.", "SUCCESS")
        
        hashes = {}
        dup_count = 0
        dup_dir = os.path.join(self.folder, "Duplicados_Detectados")
        
        def get_h(p):
            stat = os.stat(p)
            h = self.cache.get_cached_hash(p, stat.st_mtime, stat.st_size)
            if h: return h
            hasher = hashlib.md5()
            with open(p, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b""): hasher.update(chunk)
            h = hasher.hexdigest()
            self.cache.update_cache(p, h, stat.st_mtime, stat.st_size)
            return h

        results = self.executor.map(get_h, candidates)
        for path, f_hash in zip(candidates, results):
            if f_hash in hashes:
                os.makedirs(dup_dir, exist_ok=True)
                shutil.move(path, os.path.join(dup_dir, f"DUP_{os.path.basename(path)}"))
                dup_count += 1
                self.add_log(f"Duplicado removido: {os.path.basename(path)}", "WARNING")
            else: hashes[f_hash] = path
        self.add_log(f"Limpeza concluída! {dup_count} arquivos duplicados movidos.", "SUCCESS")

    def render_stats(self):
        if not self.folder: 
            ctk.CTkLabel(self.content, text="Selecione uma pasta para gerar relatórios visuais.", font=("Segoe UI", 16)).pack(pady=100)
            return
        
        # Limpar figuras anteriores para evitar vazamento de memória e conflitos de UI
        plt.close('all')
        
        stats = {}
        for cat in list(self.types.keys()) + ["Outros"]:
            p = os.path.join(self.folder, cat)
            if os.path.exists(p): 
                try:
                    stats[cat] = len([f for f in os.scandir(p) if f.is_file()])
                except: stats[cat] = 0
        
        if not any(stats.values()):
            ctk.CTkLabel(self.content, text="Nenhum arquivo encontrado nas pastas categorizadas.", font=("Segoe UI", 16)).pack(pady=100)
            return

        fig, ax = plt.subplots(figsize=(6, 4), dpi=100)
        fig.patch.set_facecolor(COLORS["bg"])
        ax.set_facecolor(COLORS["bg"])
        
        labels = [k for k, v in stats.items() if v > 0]
        values = [v for v in stats.values() if v > 0]
        
        ax.pie(values, labels=labels, autopct='%1.1f%%', textprops={'color':"w", 'weight':'bold'}, startangle=140)
        ax.set_title("Distribuição de Arquivos", color='w', pad=20, fontdict={'size': 16, 'weight': 'bold'})
        
        canvas = FigureCanvasTkAgg(fig, master=self.content)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=20, pady=20)

if __name__ == "__main__":
    app = OrganizaFacilApp()
    app.mainloop()
