@echo off
title Open WebUI - Local AI Assistant
echo Starting Ollama service check...
ollama list >nul 2>&1
if errorlevel 1 (
    echo Ollama does not appear to be running or installed correctly.
    echo Please make sure Ollama is installed and try again.
    pause
    exit /b 1
)

echo Ollama is available. Starting Open WebUI...
echo.
echo Once loaded, open your browser to: http://localhost:8080
echo Press Ctrl+C in this window to stop the server.
echo.

open-webui serve

pause
