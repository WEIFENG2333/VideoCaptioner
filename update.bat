@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM VideoCaptioner 一键更新脚本（适用于 Windows）
REM 作者：VideoCaptioner 团队
REM 版本：v1.0

echo ========================================
echo     VideoCaptioner 一键更新脚本
echo ========================================
echo.

REM 检查是否为 Git 仓库
if not exist ".git" (
    echo [错误] 当前目录不是 Git 仓库
    echo 请确保您是从 GitHub 克隆的项目，而不是下载的压缩包
    echo 克隆命令：git clone https://github.com/WEIFENG2333/VideoCaptioner.git
    pause
    exit /b 1
)

REM 检查 Git 是否安装
git --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未安装 Git
    echo 请下载并安装 Git：https://git-scm.com/download/win
    pause
    exit /b 1
)

REM 获取当前版本信息
echo [信息] 获取当前版本信息...
for /f %%i in ('git rev-parse HEAD 2^>nul') do set CURRENT_COMMIT=%%i
for /f %%i in ('git branch --show-current 2^>nul') do set CURRENT_BRANCH=%%i
if "!CURRENT_COMMIT!"=="" set CURRENT_COMMIT=unknown
if "!CURRENT_BRANCH!"=="" set CURRENT_BRANCH=unknown

echo [信息] 当前分支：!CURRENT_BRANCH!
echo [信息] 当前提交：!CURRENT_COMMIT:~0,8!
echo.

REM 备份用户数据
echo [备份] 正在备份用户数据...
set BACKUP_DIR=backup_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set BACKUP_DIR=%BACKUP_DIR: =0%
mkdir "%BACKUP_DIR%" >nul 2>&1

if exist "AppData" (
    xcopy "AppData" "%BACKUP_DIR%\AppData" /E /I /H /Y >nul 2>&1
    echo [成功] ✓ 已备份 AppData
)

if exist "work-dir" (
    xcopy "work-dir" "%BACKUP_DIR%\work-dir" /E /I /H /Y >nul 2>&1
    echo [成功] ✓ 已备份 work-dir
)

if exist "venv" (
    echo [注意] 虚拟环境将在更新后重新创建
)

echo [成功] 用户数据已备份到：%BACKUP_DIR%
echo.

REM 检查远程更新
echo [检查] 正在检查远程更新...
git fetch origin >nul 2>&1

REM 获取远程提交ID
for /f %%i in ('git rev-parse HEAD 2^>nul') do set LOCAL_COMMIT=%%i
for /f %%i in ('git rev-parse origin/main 2^>nul') do set REMOTE_COMMIT=%%i
if "!REMOTE_COMMIT!"=="" (
    for /f %%i in ('git rev-parse origin/master 2^>nul') do set REMOTE_COMMIT=%%i
)

if "!LOCAL_COMMIT!"=="!REMOTE_COMMIT!" (
    echo [信息] 您的代码已是最新版本！
    set /p "continue=是否仍要继续更新？(y/N): "
    if /i not "!continue!"=="y" (
        echo 更新已取消
        pause
        exit /b 0
    )
) else (
    echo [发现] 发现新的更新！
    echo [信息] 远程版本：!REMOTE_COMMIT:~0,8!
)
echo.

REM 检查本地更改
git diff-index --quiet HEAD -- >nul 2>&1
if errorlevel 1 (
    echo [警告] 检测到本地更改，这些更改将被保存：
    git status --short
    echo.
    set /p "continue=是否继续更新？本地更改将被暂存 (y/N): "
    if /i not "!continue!"=="y" (
        echo 更新已取消
        pause
        exit /b 0
    )
    
    REM 暂存本地更改
    echo [暂存] 正在暂存本地更改...
    git stash push -m "Auto-stash before update %date% %time%" >nul 2>&1
    set STASHED=true
) else (
    set STASHED=false
)

REM 确定主分支名称
for /f "tokens=5" %%i in ('git remote show origin ^| findstr "HEAD branch"') do set MAIN_BRANCH=%%i
if "!MAIN_BRANCH!"=="" set MAIN_BRANCH=main

REM 执行更新
echo [更新] 正在更新代码...
git pull origin !MAIN_BRANCH!
if errorlevel 1 (
    echo [错误] 代码更新失败
    pause
    exit /b 1
)
echo [成功] 代码更新完成！
echo.

REM 恢复本地更改
if "!STASHED!"=="true" (
    echo [恢复] 正在恢复本地更改...
    git stash pop >nul 2>&1
    if errorlevel 1 (
        echo [警告] 恢复本地更改时发生冲突，请手动解决
        echo 使用 'git stash list' 查看暂存的更改
        echo 使用 'git stash apply' 手动恢复更改
    ) else (
        echo [成功] 本地更改已恢复
    )
    echo.
)

REM 更新依赖
echo [更新] 正在更新 Python 依赖...

if exist "venv" (
    echo [删除] 正在删除旧的虚拟环境...
    rmdir /s /q "venv" >nul 2>&1
)

REM 重新创建虚拟环境
echo [创建] 正在创建新的虚拟环境...
python -m venv venv
if errorlevel 1 (
    echo [错误] 创建虚拟环境失败
    pause
    exit /b 1
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 升级 pip
echo [升级] 正在升级 pip...
python -m pip install --upgrade pip >nul 2>&1

REM 安装依赖
if exist "requirements.txt" (
    echo [安装] 正在安装依赖包...
    pip install -r requirements.txt >nul 2>&1
    if errorlevel 1 (
        echo [错误] 安装依赖失败
        pause
        exit /b 1
    )
    echo [成功] 依赖更新完成
) else (
    echo [警告] 未找到 requirements.txt 文件
)
echo.

REM 清理临时文件
echo [清理] 正在清理临时文件...

REM 清理 Python 缓存
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" >nul 2>&1
del /s /q *.pyc >nul 2>&1

REM 清理应用缓存（保留用户数据）
if exist "AppData\cache" (
    del /s /q "AppData\cache\*" >nul 2>&1
    echo [成功] ✓ 已清理应用缓存
)

REM 显示更新结果
echo.
echo ============ 更新完成 ============

for /f %%i in ('git rev-parse HEAD 2^>nul') do set NEW_COMMIT=%%i
echo [成功] 新版本：!NEW_COMMIT:~0,8!

REM 显示更新日志
if not "!CURRENT_COMMIT!"=="unknown" if not "!CURRENT_COMMIT!"=="!NEW_COMMIT!" (
    echo.
    echo [日志] 更新日志：
    git log --oneline !CURRENT_COMMIT!..!NEW_COMMIT! | head -10
)

echo.
echo [完成] 更新成功！您现在可以运行 start.bat 启动程序
echo.
pause