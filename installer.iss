#define MyAppIcon "C:\Users\HomePC\Documents\Online Motor Spare Pos System\motor_spares_pos\assets\michoe-tech-labs.ico"
#define MyAppSourceDir "C:\Users\HomePC\Documents\Online Motor Spare Pos System\motor_spares_pos\dist\MichoeTechLabsPOS"
#define MyAppName "Michoe Tech Labs POS"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Michoe Tech Labs"
#define MyAppExeName "MichoeTechLabsPOS.exe"

[Setup]
AppId={{MICHOE-TECH-LABS-POS}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
SetupIconFile={#MyAppIcon}

DefaultDirName={autopf}\Michoe Tech Labs POS
DefaultGroupName=Michoe Tech Labs POS

OutputDir=installer
OutputBaseFilename=MichoeTechLabsPOS-Setup

Compression=lzma
SolidCompression=yes

ArchitecturesInstallIn64BitMode=x64compatible

PrivilegesRequired=admin

UninstallDisplayName=Michoe Tech Labs POS

[Files]
Source: "C:\Users\HomePC\Documents\Online Motor Spare Pos System\motor_spares_pos\dist\MichoeTechLabsPOS\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Michoe Tech Labs POS"; \
    Filename: "{app}\MichoeTechLabsPOS.exe"; \
    WorkingDir: "{app}"; \
    IconFilename: "{app}\MichoeTechLabsPOS.exe"

Name: "{autodesktop}\Michoe Tech Labs POS"; \
    Filename: "{app}\MichoeTechLabsPOS.exe"; \
    WorkingDir: "{app}"; \
    IconFilename: "{app}\MichoeTechLabsPOS.exe"

[Run]
Filename: "{app}\MichoeTechLabsPOS.exe"; \
    Description: "Launch Michoe Tech Labs POS"; \
    Flags: nowait postinstall skipifsilent