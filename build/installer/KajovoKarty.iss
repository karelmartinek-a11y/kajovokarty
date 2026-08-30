#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppName "KájovoKarty"
#define AppExeName "KajovoKarty.exe"

[Setup]
AppId={{9BEEFC0F-7FD8-4B67-B341-BA7F291EB0EF}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Kájovo
DefaultDirName={localappdata}\Programs\KajovoKarty
DefaultGroupName=KájovoKarty
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=KajovoKarty-Setup-x64-{#AppVersion}
SetupIconFile=..\..\resources\icons\kajovokarty.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\release\KajovoKarty.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\THIRD_PARTY_LICENSES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\docs\USER_GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\KájovoKarty"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\KájovoKarty"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Vytvořit ikonu na ploše"; GroupDescription: "Další ikony:"; Flags: unchecked

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Spustit KájovoKarty"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Uživatelská databáze v %LOCALAPPDATA%\KajovoKarty se záměrně nemaže.
Type: filesandordirs; Name: "{app}"
