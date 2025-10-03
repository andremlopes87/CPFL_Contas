@echo off
setlocal

if not exist .venv (
    echo [INFO] Criando ambiente virtual Python 3.11
    py -3.11 -m venv .venv
)

call .\.venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo [INFO] Gerando executavel CPFLFetcher.exe
pyinstaller --onefile --name CPFLFetcher ^
    --add-data "config.example.json;." ^
    --add-data "data/mocks;data/mocks" ^
    main.py

echo.
echo [SUCESSO] Arquivo criado em dist\CPFLFetcher.exe
endlocal
