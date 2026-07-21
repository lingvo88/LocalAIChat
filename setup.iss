; LocalAIChat Setup Script
; Save this as: C:\Users\Mussa\Documents\LocalAIChat\setup.iss
; Then open with Inno Setup Compiler and click Build -> Compile

#define MyAppName "LocalAIChat"
#define MyAppVersion "1.0"
#define MyAppPublisher "Mussa"
#define MyAppExeName "LocalAIChat.exe"
#define MySourceDir "C:\Users\Mussa\Documents\LocalAIChat"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir={#MySourceDir}\installer
OutputBaseFilename=LocalAIChatSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Desktop app executable
Source: "{#MySourceDir}\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Server brain files
Source: "{#MySourceDir}\app.py"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "{#MySourceDir}\chat_store.py"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "{#MySourceDir}\templates\*"; DestDir: "{app}\server\templates"; Flags: ignoreversion recursesubdirs
Source: "{#MySourceDir}\static\*"; DestDir: "{app}\server\static"; Flags: ignoreversion recursesubdirs

; PowerShell and batch scripts
Source: "{#MySourceDir}\Toggle-ServerAutoStart.ps1"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "{#MySourceDir}\Toggle-AutoStart.ps1"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "{#MySourceDir}\Start-OpenWebUI.bat"; DestDir: "{app}\server"; Flags: ignoreversion

; Python installer — bundled, installed silently if Python not present
Source: "{#MySourceDir}\python-installer.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

; README dropped into install folder for reference
Source: "{#MySourceDir}\INSTALL_NOTES.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
; Start Menu
Name: "{group}\LocalAIChat"; Filename: "{app}\{#MyAppExeName}"; Comment: "Open Local AI Chat"
Name: "{group}\Start AI Server"; Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\server\Toggle-ServerAutoStart.ps1"" -Enable"; WorkingDir: "{app}\server"; Comment: "Enable AI server auto-start at login"
Name: "{group}\Uninstall LocalAIChat"; Filename: "{uninstallexe}"

; Desktop shortcut (optional, unchecked by default)
Name: "{autodesktop}\LocalAIChat"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Step 1: Install Python silently if not already installed
; /quiet = no UI, /passive = progress bar only
; PrependPath=1 adds Python to PATH so pip works immediately
Filename: "{tmp}\python-installer.exe"; Parameters: "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1"; StatusMsg: "Installing Python 3.12..."; Check: PythonNotInstalled; Flags: waituntilterminated

Filename: "cmd.exe"; Parameters: "/c python -m pip install --quiet flask requests ddgs 2>&1"; StatusMsg: "Installing dependencies (flask, requests, ddgs)..."; Flags: runhidden waituntilterminated

Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -Command ""Unblock-File '{app}\server\Toggle-ServerAutoStart.ps1'; Unblock-File '{app}\server\Toggle-AutoStart.ps1'"""; Flags: runhidden waituntilterminated

Filename: "{app}"; Description: "Open installation folder"; Flags: postinstall shellexec skipifsilent unchecked

; Step 2: Install pip dependencies
Filename: "cmd.exe"; \
    Parameters: "/c python -m pip install --quiet flask requests ddgs 2>&1"; \
    StatusMsg: "Installing dependencies (flask, requests, ddgs)..."; \
    Flags: runhidden waituntilterminated

; Step 3: Unblock the PowerShell scripts so they run without security prompts
Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -Command ""Unblock-File '{app}\server\Toggle-ServerAutoStart.ps1'; Unblock-File '{app}\server\Toggle-AutoStart.ps1'"""; \
    Flags: runhidden waituntilterminated

; Step 4: Open install folder after setup completes
Filename: "{app}"; \
    Description: "Open installation folder"; \
    Flags: postinstall shellexec skipifsilent unchecked

[UninstallRun]
; Remove the scheduled task if it was enabled
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName 'LocalAIChat-Server' -Confirm:$false -ErrorAction SilentlyContinue"""; Flags: runhidden waituntilterminated

[Code]
function PythonNotInstalled: Boolean;
var
  PythonPath: String;
begin
  // Check if python.exe is already on PATH or in common install locations
  if RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SOFTWARE\Python\PythonCore\3.12\InstallPath', '', PythonPath) then
  begin
    Result := False;  // Python 3.12 already installed
    Exit;
  end;
  if RegQueryStringValue(HKEY_CURRENT_USER,
    'SOFTWARE\Python\PythonCore\3.12\InstallPath', '', PythonPath) then
  begin
    Result := False;
    Exit;
  end;
  Result := True;  // Not found, needs installing
end;