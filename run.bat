@echo off
rem Clipvault launcher for Windows - double-click this file.
title Clipvault
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" set "PY="%%D\python.exe""
  )
)
if not defined PY (
  for /d %%D in ("C:\Python3*" "%ProgramFiles%\Python3*") do (
    if exist "%%D\python.exe" set "PY="%%D\python.exe""
  )
)
if not defined PY (
  echo.
  echo  Python was not found.
  echo  Install it from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" during setup.
  echo.
  pause
  exit /b 1
)

%PY% app.py %*
if errorlevel 1 (
  echo.
  echo  Clipvault stopped with an error. See the messages above.
  pause
)
