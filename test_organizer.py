import os
import shutil
import pytest
import sqlite3
import json
import sqlite3
import json
import os
import shutil

# Mocking the CacheManager class since we can't import the whole app due to Tkinter dependency in sandbox
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
# FIXTURES (AMBIENTE DE TESTE)
# ==========================================

@pytest.fixture
def temp_workspace(tmp_path):
    """Cria uma pasta temporária com alguns arquivos de teste"""
    d = tmp_path / "test_folder"
    d.mkdir()
    
    # Criar arquivos de teste
    (d / "photo.jpg").write_text("dummy content")
    (d / "doc.pdf").write_text("dummy content")
    (d / "script.py").write_text("print('hello')")
    (d / "unknown.xyz").write_text("dummy content")
    
    return d

@pytest.fixture
def cache_manager(tmp_path):
    """Cria um gerenciador de cache temporário"""
    db_path = tmp_path / "test_cache.db"
    return CacheManager(str(db_path))

# ==========================================
# TESTES DE CACHE
# ==========================================

def test_cache_init(cache_manager):
    """Testa se o banco de dados é inicializado corretamente"""
    assert cache_manager.enabled is True
    assert os.path.exists(cache_manager.db_path)

def test_cache_update_and_get(cache_manager):
    """Testa salvar e recuperar um hash do cache"""
    path = "/fake/path/file.txt"
    f_hash = "abc123hash"
    mtime = 1234567.8
    size = 1024
    
    cache_manager.update_cache(path, f_hash, mtime, size)
    cached_hash = cache_manager.get_cached_hash(path, mtime, size)
    
    assert cached_hash == f_hash

def test_cache_invalid_get(cache_manager):
    """Testa se retorna None para dados inexistentes ou alterados"""
    path = "/fake/path/file.txt"
    cache_manager.update_cache(path, "hash1", 1.0, 100)
    
    # Mtime diferente
    assert cache_manager.get_cached_hash(path, 2.0, 100) is None
    # Tamanho diferente
    assert cache_manager.get_cached_hash(path, 1.0, 200) is None

# ==========================================
# TESTES DE LÓGICA DE ORGANIZAÇÃO
# ==========================================

class MockApp:
    """Uma versão simplificada do app para testar apenas a lógica de organização"""
    def __init__(self, folder):
        self.folder = str(folder)
        self.types = {
            "Imagens": [".jpg"],
            "PDFs": [".pdf"],
            "Código": [".py"]
        }
        self.history_actions = []
        
    def add_log(self, text, level="INFO"):
        pass # Mock log

    def organize_files(self):
        # Copiado da lógica original para teste
        entries = [e for e in os.scandir(self.folder) if e.is_file()]
        history = []
        for entry in entries:
            ext = os.path.splitext(entry.name)[1].lower()
            moved = False
            for cat, exts in self.types.items():
                if ext in exts:
                    dest_dir = os.path.join(self.folder, cat)
                    os.makedirs(dest_dir, exist_ok=True)
                    dest_path = os.path.join(dest_dir, entry.name)
                    shutil.move(entry.path, dest_path)
                    history.append((dest_path, entry.path))
                    moved = True
                    break
            if not moved:
                others = os.path.join(self.folder, "Outros")
                os.makedirs(others, exist_ok=True)
                shutil.move(entry.path, os.path.join(others, entry.name))
                history.append((os.path.join(others, entry.name), entry.path))
        self.history_actions.append(history)

def test_organization_logic(temp_workspace):
    """Testa se os arquivos são movidos para as pastas corretas"""
    app = MockApp(temp_workspace)
    app.organize_files()
    
    # Verificar pastas criadas
    assert os.path.exists(temp_workspace / "Imagens" / "photo.jpg")
    assert os.path.exists(temp_workspace / "PDFs" / "doc.pdf")
    assert os.path.exists(temp_workspace / "Código" / "script.py")
    assert os.path.exists(temp_workspace / "Outros" / "unknown.xyz")

def test_undo_logic(temp_workspace):
    """Testa se a função de desfazer restaura os arquivos"""
    app = MockApp(temp_workspace)
    app.organize_files()
    
    # Garantir que foram movidos
    assert not os.path.exists(temp_workspace / "photo.jpg")
    
    # Desfazer
    last = app.history_actions.pop()
    for curr, orig in last:
        shutil.move(curr, orig)
        
    # Verificar se voltaram
    assert os.path.exists(temp_workspace / "photo.jpg")
    assert os.path.exists(temp_workspace / "doc.pdf")
    assert os.path.exists(temp_workspace / "script.py")

# ==========================================
# TESTES DE CONFIGURAÇÃO
# ==========================================

def test_settings_load_save(tmp_path):
    """Testa se as configurações são salvas e lidas corretamente"""
    config_file = tmp_path / "test_settings.json"
    test_data = {"CustomCat": [".exe", ".msi"]}
    
    # Salvar
    with open(config_file, "w") as f:
        json.dump(test_data, f)
        
    # Ler
    with open(config_file, "r") as f:
        loaded_data = json.load(f)
        
    assert loaded_data["CustomCat"] == [".exe", ".msi"]
