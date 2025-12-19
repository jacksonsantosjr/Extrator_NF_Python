# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# --- Common Logic ---
def get_analysis(script_name, hidden_imports=None):
    if hidden_imports is None: hidden_imports = []
    
    return Analysis(
        [script_name],
        pathex=[],
        binaries=[],
        datas=[
            ('config', 'config'),
        ],
        hiddenimports=[
            'pdfplumber',
            'fitz',
            'pytesseract',
            'openpyxl',
            'pandas',
            'pydantic',
            'loguru',
            'requests',
            'tomli',
            'packaging' # CTk dep
        ] + hidden_imports,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        cipher=block_cipher,
        noarchive=False,
    )

# --- Analysis 1: Flet (Original) ---
a_flet = get_analysis('run.py', hidden_imports=['flet'])
pyz_flet = PYZ(a_flet.pure, a_flet.zipped_data, cipher=block_cipher)
exe_flet = EXE(
    pyz_flet,
    a_flet.scripts,
    a_flet.binaries,
    a_flet.zipfiles,
    a_flet.datas,
    [],
    name='FiscalExtractor_Flet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False, 
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# --- Analysis 2: CustomTkinter (V2) ---
a_tk = get_analysis('run_tkinter.py', hidden_imports=['customtkinter', 'PIL._tkinter_finder'])
pyz_tk = PYZ(a_tk.pure, a_tk.zipped_data, cipher=block_cipher)
exe_tk = EXE(
    pyz_tk,
    a_tk.scripts,
    a_tk.binaries,
    a_tk.zipfiles,
    a_tk.datas,
    [],
    name='FiscalExtractor_Tk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
