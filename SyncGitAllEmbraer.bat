@echo off
echo chat_api_claude
cd /d C:\DATA\chat_api_claude
call SyncGit.bat "Auto"

echo Python
cd /d C:\DATA\Python
call SyncGit.bat "Auto"

echo Obsidian
cd /d C:\DATA\obsidian
call SyncGit.bat "Auto"
