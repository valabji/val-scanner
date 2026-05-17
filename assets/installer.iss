; Inno Setup script for ValScanner
; Requires Inno Setup 6+ — https://jrsoftware.org/isinfo.php
; Run: ISCC.exe assets\installer.iss   (from the repo root)

[Setup]
AppName=ValScanner
AppVersion=0.1.3
AppPublisher=Abdalrahman Valabji
AppPublisherURL=https://github.com/valabji/valscanner
AppSupportURL=https://github.com/valabji/valscanner/issues
DefaultDirName={autopf}\ValScanner
DefaultGroupName=ValScanner
AllowNoIcons=yes
OutputDir=..\dist
OutputBaseFilename=ValScanner-0.1.3-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\ValScanner.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; \
    Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; \
    Flags: unchecked

[Files]
Source: "..\dist\ValScanner\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ValScanner"; \
    Filename: "{app}\ValScanner.exe"; \
    WorkingDir: "{app}"
Name: "{group}\Uninstall ValScanner"; \
    Filename: "{uninstallexe}"
Name: "{commondesktop}\ValScanner"; \
    Filename: "{app}\ValScanner.exe"; \
    WorkingDir: "{app}"; \
    Tasks: desktopicon

[Registry]
; Associate .db files opened from Explorer with ValScanner
Root: HKCU; \
    Subkey: "Software\Classes\.db\OpenWithProgids"; \
    ValueType: string; ValueName: "ValScanner.Database"; ValueData: ""; \
    Flags: uninsdeletevalue
Root: HKCU; \
    Subkey: "Software\Classes\ValScanner.Database"; \
    ValueType: string; ValueData: "ValScanner Database"; \
    Flags: uninsdeletekey
Root: HKCU; \
    Subkey: "Software\Classes\ValScanner.Database\DefaultIcon"; \
    ValueType: string; ValueData: "{app}\ValScanner.exe,0"
Root: HKCU; \
    Subkey: "Software\Classes\ValScanner.Database\shell\open\command"; \
    ValueType: string; ValueData: """{app}\ValScanner.exe"" ""%1"""

[Run]
Filename: "{app}\ValScanner.exe"; \
    Description: "{cm:LaunchProgram,ValScanner}"; \
    Flags: nowait postinstall skipifsilent
