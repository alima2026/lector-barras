@echo off
setlocal
title Mudanza Darkinel Polo

cd /d "%~dp0"

echo Levantando base PostgreSQL en Docker...
docker compose -f "C:\Users\Adrian\Desktop\Pedidos Magna\Analisis Ventas Mostrador\docker-compose.yml" up -d postgres
if errorlevel 1 (
    echo.
    echo No se pudo levantar PostgreSQL en Docker.
    echo Verifica que Docker Desktop este abierto.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Falta preparar la app local.
    echo Ejecuta primero: Instalar_app_escritorio.bat
    echo.
    pause
    exit /b 1
)

echo.
echo ===============================================
echo  ABRIENDO APP LOCAL - MUDANZA DARKINEL / POLO
echo ===============================================
echo.
echo La app funciona en esta PC, sin depender de Streamlit Cloud.
echo Si no se abre sola, entra a:
echo http://localhost:8501
echo.
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /c:"IPv4"') do (
    set "IP_LOCAL=%%A"
    goto :ip_encontrada
)
:ip_encontrada
if defined IP_LOCAL (
    set "IP_LOCAL=%IP_LOCAL: =%"
    echo Desde otra PC en la misma red entra a:
    echo http://%IP_LOCAL%:8501
    echo.
)
echo.
echo Para cerrar la app, cerra esta ventana.
echo.

start "" cmd /c "timeout /t 4 >nul && start "" http://localhost:8501"

".venv\Scripts\python.exe" -m streamlit run app.py --server.address=0.0.0.0 --server.port=8501

pause
