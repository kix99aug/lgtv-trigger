# LGTV Trigger

在 Windows 背景執行的小工具，讓電腦控制 LG 電視（webOS）和 Sony Soundbar：

| 動作 | 結果 |
| --- | --- |
| 按滑鼠**中鍵**，或 `Win + Shift + W` | 開啟電視（Wake-on-LAN）並切換到 `HDMI_1`；電視已開著時只切換輸入源 |
| Windows 關閉螢幕（電源計畫逾時） | `lgtv off` 關閉電視 |
| 鎖定畫面（`Win + L` 或自動鎖定） | `lgtv off` 關閉電視 |
| 鍵盤音量鍵／音量滾輪 | 攔截掉，不改 Windows 音量，改送到 Soundbar 控制程式（`127.0.0.1:9105`） |

偵測到 **Sunshine** 或 **Parsec** 有遠端連線時，開機與音量功能會暫停，遠端操作不會動到客廳的電視。

## 運作方式

`main.py` 是單一腳本，內含：

- **鍵盤／滑鼠 hook**（`pynput`）：偵測喚醒按鍵。音量鍵在 `win32_event_filter` 中被攔截（`SuppressException`），100 ms 內的連續操作會合併成一次 `up N` / `down N`，以 TCP 送給 `127.0.0.1:9105`。
- **`SystemEventListener`**：建立一個隱藏視窗，註冊 `GUID_CONSOLE_DISPLAY_STATE` 與 WTS session 通知，收到「螢幕關閉」或「工作階段鎖定」時關電視。
- **`WakeController`**：喚醒流程為 `lgtv power-status` → `lgtv on` → 每 2 秒輪詢最多 30 秒 → `lgtv input HDMI_1`。觸發之間有冷卻時間（預設 10 秒），同時間只會跑一次。
- **`RemoteStreamingDetector`**：每秒讀取 Sunshine（`%ProgramFiles%\Sunshine\config\sunshine.log`）與 Parsec（`%ProgramData%\Parsec\log.txt` 或 `%AppData%\Parsec\log.txt`）的 log，計算目前連線數。

以 `pythonw.exe` 執行時沒有 console，stdout/stderr 會寫入 `lgtv-trigger.log`。

## 外部依賴

- **`lgtv` 指令**：[lgtvremote-cli](https://pypi.org/project/lgtvremote-cli/)，用 `uv tool install lgtvremote-cli` 安裝，並先執行 `lgtv pair` 配對電視。
- **Soundbar 控制程式**（`bravia_control.py`，**不在此 repo**）：需另外在背景監聽 `127.0.0.1:9105`，否則音量鍵只會被吃掉，log 會出現 `Failed to route volume to Soundbar`。

## 安裝

```powershell
uv sync
```

## 使用

```powershell
uv run python main.py                 # 前景執行
uv run python main.py --verbose       # 顯示被冷卻／遠端連線擋下的事件
uv run python main.py --wake-now      # 只執行一次喚醒流程後結束（適合開機腳本）
```

| 參數 | 說明 |
| --- | --- |
| `--cooldown N` | 兩次喚醒之間的冷卻秒數，預設 `10` |
| `--verbose` | 顯示偵錯訊息 |
| `--wake-now` | 立刻喚醒電視並切到 `HDMI_1`，然後結束 |
| `--timeout N` | 已棄用，會被忽略（保留只為相容舊的排程設定） |

## 開機自動執行（工作排程器）

目前用名為 `LGTVTrigger` 的排程工作在登入時啟動。它用的是 **uv 管理的基礎 `pythonw.exe`**，不是 `.venv` 裡的那個；`main.py` 開頭會自己把 `.venv\Lib\site-packages` 加進 `sys.path`，所以仍然讀得到 `pynput`。

以系統管理員身分在 PowerShell 註冊：

```powershell
$action = New-ScheduledTaskAction `
  -Execute "$env:APPDATA\uv\python\cpython-3.13-windows-x86_64-none\pythonw.exe" `
  -Argument "main.py" `
  -WorkingDirectory "C:\Users\kix\lgtv-trigger"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
# ExecutionTimeLimit 0 = 不限時；省略的話工作排程器預設 72 小時後會砍掉
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "LGTVTrigger" -Action $action -Trigger $trigger -Principal $principal -Settings $settings
```

必須是 `Interactive` 登入類型（跑在使用者的 session），鍵盤／滑鼠 hook 和工作階段通知才收得到。

管理指令：

```powershell
Start-ScheduledTask      -TaskName "LGTVTrigger"
Stop-ScheduledTask       -TaskName "LGTVTrigger"
Get-ScheduledTask        -TaskName "LGTVTrigger"
Unregister-ScheduledTask -TaskName "LGTVTrigger" -Confirm:$false
```

改完 `main.py` 後要 Stop + Start 才會生效。

## `fix-lgtv-cert.py`

較新的 LG 韌體會拒絕 lgtvremote-cli 內建的 `test-signing-cert` 簽章，配對時出現：

```
Error: Registration failed: 403 Pairing rejected: blacklisted certificate detected
```

這個腳本會把已安裝的 `lgtvremote_cli.py` 中的 `"signatures"` 區塊移除（與 aiowebostv 0.9.2 的修法相同）。每次 `uv tool upgrade lgtvremote-cli` 或強制重裝後都要重跑：

```powershell
python fix-lgtv-cert.py           # 套用 patch（可重複執行）
python fix-lgtv-cert.py --check   # 只檢查，不寫入
python fix-lgtv-cert.py --path X  # 指定 lgtvremote_cli.py 路徑
```

之後若電視仍拒絕，執行 `lgtv pair` 重新配對。

## 疑難排解

- 看 `lgtv-trigger.log`。
- 喚醒沒反應：先手動跑 `lgtv power-status`、`lgtv on` 確認 CLI 能連到電視；出現 403 就跑 `fix-lgtv-cert.py`。
- 按鍵完全沒反應：確認沒有遠端串流連線（log 會印 `client connected`），或用 `--verbose` 看是否被冷卻擋掉。
