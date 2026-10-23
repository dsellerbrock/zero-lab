; Zero Lab for Windows: a per-user install wizard (no admin), built by tools/make-windows-installer.sh:
;   makensis -DVERSION=<v> -DSTAGE=<dir> -DOUTFILE=<setup.exe> windows/installer.nsi
; STAGE holds "Zero Lab.cmd", icon.ico, LICENSE.txt and zero-lab\ (app, samples, kernel, qemu, python).
; The Pi's disk images and layouts live in %LOCALAPPDATA%\Zero Lab, which an uninstall keeps unless asked.
Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

!define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zero Lab"
Name "Zero Lab"
OutFile "${OUTFILE}"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\Zero Lab"
InstallDirRegKey HKCU "${UNINST}" "InstallLocation"
SetCompressor /SOLID lzma

!define MUI_ICON "${STAGE}\icon.ico"
!define MUI_UNICON "${STAGE}\icon.ico"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Launch Zero Lab"
!define MUI_FINISHPAGE_RUN_FUNCTION Launch
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${STAGE}\LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_COMPONENTS
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function Launch
  ExecShell "" "$INSTDIR\Zero Lab.cmd" "" SW_SHOWMINIMIZED
FunctionEnd

Section "Zero Lab"
  SetOutPath "$INSTDIR"
  RMDir /r "$INSTDIR\zero-lab"  ; an update replaces the app; the user's data is elsewhere
  File /r "${STAGE}\*"
  WriteUninstaller "$INSTDIR\Uninstall Zero Lab.exe"
  ; minimised: the console window is only there so closing it stops the Pi
  CreateShortCut "$SMPROGRAMS\Zero Lab.lnk" "$INSTDIR\Zero Lab.cmd" "" "$INSTDIR\icon.ico" 0 SW_SHOWMINIMIZED
  CreateShortCut "$DESKTOP\Zero Lab.lnk" "$INSTDIR\Zero Lab.cmd" "" "$INSTDIR\icon.ico" 0 SW_SHOWMINIMIZED
  WriteRegStr HKCU "${UNINST}" "DisplayName" "Zero Lab"
  WriteRegStr HKCU "${UNINST}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST}" "Publisher" "Zero Lab"
  WriteRegStr HKCU "${UNINST}" "URLInfoAbout" "https://github.com/dsellerbrock/zero-lab"
  WriteRegStr HKCU "${UNINST}" "DisplayIcon" "$INSTDIR\icon.ico"
  WriteRegStr HKCU "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST}" "UninstallString" '"$INSTDIR\Uninstall Zero Lab.exe"'
  WriteRegStr HKCU "${UNINST}" "QuietUninstallString" '"$INSTDIR\Uninstall Zero Lab.exe" /S'
  WriteRegDWORD HKCU "${UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "${UNINST}" "EstimatedSize" $0
SectionEnd

Section "un.Zero Lab (the app)"
  SectionIn RO
  Delete "$SMPROGRAMS\Zero Lab.lnk"
  Delete "$DESKTOP\Zero Lab.lnk"
  ; only what the installer put there: the folder may have been chosen by the user
  RMDir /r "$INSTDIR\zero-lab"
  Delete "$INSTDIR\Zero Lab.cmd"
  Delete "$INSTDIR\icon.ico"
  Delete "$INSTDIR\LICENSE.txt"
  Delete "$INSTDIR\Uninstall Zero Lab.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINST}"
SectionEnd

Section /o "un.Also remove my Pi data (disk images, layouts, settings)"
  RMDir /r "$LOCALAPPDATA\Zero Lab"
SectionEnd
