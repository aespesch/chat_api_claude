@echo off
echo Site Finance
cd /d D:\USER\Toni\Financeiro\Site
call SyncGit.bat "Auto"

echo chat_api_claude
cd /d D:\USER\Toni\Cursos\LLM\Claude\chat_api_claude
call SyncGit.bat "Auto"

echo Python
cd /d d:\python
call SyncGit.bat "Auto"

echo Obsidian
cd /d D:\USER\Toni\Obsidian
call SyncGit.bat "Auto"

