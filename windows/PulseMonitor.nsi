; Strix Pulse Monitor — per-user NSIS installer (setup wizard).
; Build the exe first (build.bat), then: makensis PulseMonitor.nsi
; Produces: Strix-Pulse-Monitor-Setup.exe

Unicode true
!define APP    "Strix Pulse Monitor"
!ifndef VER
!define VER    "1.0.4"
!endif
!define EXE    "Strix Pulse Monitor.exe"
!define COMPANY "Strix Advanced Tools"

Name "${APP}"
OutFile "Strix-Pulse-Monitor-Setup.exe"
InstallDir "$LOCALAPPDATA\${APP}"
RequestExecutionLevel user      ; per-user install, no admin prompt
SetCompressor /SOLID lzma
BrandingText "${COMPANY}"

Page directory
Page components
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Strix Pulse Monitor (required)" SecCore
  SectionIn RO
  SetOutPath "$INSTDIR"
  File "dist\${EXE}"
  File /nonfatal "pulse.ico"

  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortCut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\pulse.ico"
  CreateShortCut "$SMPROGRAMS\${APP}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ; Add/Remove Programs entry (per-user)
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "DisplayName" "${APP}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "DisplayVersion" "${VER}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "Publisher" "${COMPANY}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "DisplayIcon" "$INSTDIR\pulse.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "UninstallString" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Desktop shortcut" SecDesktop
  CreateShortCut "$DESKTOP\${APP}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\pulse.ico"
SectionEnd

Section "Start with Windows" SecAutostart
  CreateShortCut "$SMSTARTUP\${APP}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\pulse.ico"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\pulse.ico"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$SMPROGRAMS\${APP}\${APP}.lnk"
  Delete "$SMPROGRAMS\${APP}\Uninstall.lnk"
  RMDir  "$SMPROGRAMS\${APP}"
  Delete "$DESKTOP\${APP}.lnk"
  Delete "$SMSTARTUP\${APP}.lnk"
  RMDir  "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"
SectionEnd
