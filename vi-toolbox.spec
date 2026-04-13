# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('app/shell/ui/main_window.ui', 'app/shell/ui'), ('app/tools/identification_tool/tool.ui', 'app/tools/identification_tool')]
datas += collect_data_files('paddleocr')
datas += collect_data_files('paddlex')


a = Analysis(
    ['app\\__main__.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['app.tools.identification_tool.ocr.paddleocr_engine', 'app.tools.identification_tool.ocr.easyocr_engine', 'app.tools.identification_tool.ocr.tesseract'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='vi-toolbox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='vi-toolbox',
)
