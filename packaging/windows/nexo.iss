; Instalador de Nexo para Windows (Inno Setup 6).
; Lo compila packaging/build-windows.sh; AppVersion llega con /DAppVersion=x.y.z

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8E3C6B1A-4D2F-4F7B-9A57-2C1E0B9D6A41}
AppName=Nexo
AppVersion={#AppVersion}
AppVerName=Nexo {#AppVersion}
AppPublisher=D4rksit3
AppPublisherURL=https://github.com/D4rksit3/nexo
AppSupportURL=https://github.com/D4rksit3/nexo/issues
DefaultDirName={localappdata}\Programs\Nexo
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible or arm64
ArchitecturesInstallIn64BitMode=x64compatible or arm64
MinVersion=10.0.19044
LicenseFile=LICENSE.txt
SetupIconFile=nexo.ico
UninstallDisplayIcon={app}\nexo.ico
UninstallDisplayName=Nexo
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=out
OutputBaseFilename=NexoSetup-{#AppVersion}
ShowLanguageDialog=no
CloseApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
es.WelcomeLabel2=Se instalará Nexo {#AppVersion}: SSH, SFTP, túneles, RDP y bases de datos con bóveda cifrada.%n%nNexo funciona sobre WSL2: el instalador crea una distribución WSL propia llamada «Nexo» (Ubuntu 24.04 oficial). Si WSL no está activado, lo activará y pedirá reiniciar.%n%nNecesitas Windows 10 21H2 o Windows 11 y unos 2 GB libres.

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "nexo.deb";          DestDir: "{app}"; Flags: ignoreversion
Source: "setup-wsl.ps1";     DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall-wsl.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "provision.sh";      DestDir: "{app}"; Flags: ignoreversion
Source: "launcher.vbs";      DestDir: "{app}"; Flags: ignoreversion
Source: "nexo.ico";          DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt";       DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Nexo"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\nexo.ico"; Comment: "SSH, SFTP, RDP y bases de datos"
Name: "{autodesktop}\Nexo"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\nexo.ico"; Tasks: desktopicon

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\launcher.vbs"""; Description: "Abrir Nexo"; Flags: postinstall nowait skipifsilent; Check: InstallOk

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall-wsl.ps1"" -NoPause"; RunOnceId: "NexoWSL"; Flags: waituntilterminated

[Code]
var
  WslRc: Integer;

function InstallOk: Boolean;
begin
  Result := (WslRc = 0);
end;

function NeedRestart: Boolean;
begin
  Result := (WslRc = 3010);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Preparando WSL e instalando Nexo (la primera vez tarda varios minutos)...';
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
                '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup-wsl.ps1') + '" -NoPause',
                ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, WslRc) then
      WslRc := -1;
    if (WslRc <> 0) and (WslRc <> 3010) then
      MsgBox('La preparación de Nexo dentro de WSL no terminó (código ' + IntToStr(WslRc) + ').' + #13#10#13#10 +
             'Revisa el registro en %LOCALAPPDATA%\Nexo\instalacion.log y vuelve a ejecutar el instalador.',
             mbError, MB_OK);
  end;
end;
