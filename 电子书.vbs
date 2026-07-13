' VideoCaptioner 桌面版启动脚本
' 双击运行，无黑框

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 获取脚本所在目录
scriptPath = fso.GetParentFolderName(WScript.ScriptFullName)

' Python 路径和主程序路径
pythonExe = "D:\Software\Anaconda3\python.exe"
mainPy = scriptPath & "\desktop_app\main.py"

' 切换到脚本目录并运行（0 = 隐藏窗口）
WshShell.CurrentDirectory = scriptPath
WshShell.Run """" & pythonExe & """ """ & mainPy & """", 0, False
