; Instalador de Nexo NATIVO para Windows (sin WSL), Inno Setup 6.
; Empaqueta la carpeta que deja PyInstaller (dist\Nexo). Lo compila la CI de Windows:
;   iscc /DAppVersion=x.y.z /DSrc=<ruta a dist\Nexo> /DRoot=<raíz del repo> packaging\windows\nexo-nativo.iss
; Se instala por usuario (sin pedir administrador). La bóveda vive en %APPDATA%\nexo y
; desinstalar NO la borra.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Src
  #define Src "..\..\dist\Nexo"
#endif
#ifndef Root
  #define Root "..\.."
#endif

[Setup]
AppId={{3B9F2C71-6E0A-4C4B-8D1E-5A7F9C2E1B64}
AppName=Nexo
AppVersion={#AppVersion}
AppVerName=Nexo {#AppVersion}
AppPublisher=D4rksit3
AppPublisherURL=https://github.com/D4rksit3/nexo
AppSupportURL=https://github.com/D4rksit3/nexo/issues
DefaultDirName={localappdata}\Programs\Nexo-nativo
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
LicenseFile={#Root}\LICENSE
SetupIconFile={#Root}\packaging\windows\nexo.ico
UninstallDisplayIcon={app}\Nexo.exe
UninstallDisplayName=Nexo
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir={#Root}\dist
OutputBaseFilename=Nexo-nativo-Setup-{#AppVersion}
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "{#Src}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Nexo"; Filename: "{app}\Nexo.exe"; Comment: "SSH, SFTP, túneles, RDP y bases de datos"
Name: "{autodesktop}\Nexo"; Filename: "{app}\Nexo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Nexo.exe"; Description: "Abrir Nexo"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; solo lo que deja PyInstaller; %APPDATA%\nexo (bóveda) se conserva
Type: filesandordirs; Name: "{app}\_internal"
