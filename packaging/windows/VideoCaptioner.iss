; VideoCaptioner Windows 安装器（Inno Setup 6）。
;
; per-user 安装到 %LOCALAPPDATA%\Programs\VideoCaptioner：免管理员，且安装目录可写 ——
; 应用内自更新（core/update 的 rm+mv 换装）因此照常生效。带开始菜单/桌面快捷方式 + 卸载程序。
; 便携 zip 仍单独产出，两者基于同一 PyInstaller onedir 产物。
;
; 版本/源目录/输出由 scripts/build_windows_installer.py 通过 /D 注入：
;   ISCC /DAppVersion=2.1.0 /DSourceDir=...\dist\VideoCaptioner /DOutputDir=...\artifacts /DOutputBase=...

#define AppName "VideoCaptioner"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\VideoCaptioner"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\artifacts"
#endif
#ifndef OutputBase
  #define OutputBase "VideoCaptioner-setup"
#endif

[Setup]
; AppId 跨版本固定，升级时原地覆盖同一安装。
AppId={{B7C4E2F1-9A3D-4E5B-8C6F-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Weifeng
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
