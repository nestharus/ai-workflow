# winctl.ps1 - Windows control helper for web-gpt
# Called from WSL via: powershell.exe -File winctl.ps1 <command> [args...]
# Stays in Windows coordinate system for consistency.

param(
    [Parameter(Position=0)]
    [string]$Command,
    [Parameter(Position=1, ValueFromRemainingArguments)]
    [string[]]$Args
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# For SendInput mouse/keyboard
Add-Type @"
using System;
using System.Runtime.InteropServices;

public class WinInput {
    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT {
        public uint type;
        public INPUTUNION u;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct INPUTUNION {
        [FieldOffset(0)] public MOUSEINPUT mi;
        [FieldOffset(0)] public KEYBDINPUT ki;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct MOUSEINPUT {
        public int dx;
        public int dy;
        public uint mouseData;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int X, int Y);

    [DllImport("user32.dll")]
    public static extern bool GetCursorPos(out POINT lpPoint);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);

    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr FindWindowEx(IntPtr hwndParent, IntPtr hwndChildAfter, string lpszClass, string lpszWindow);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    public const uint INPUT_MOUSE = 0;
    public const uint INPUT_KEYBOARD = 1;
    public const uint MOUSEEVENTF_MOVE = 0x0001;
    public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    public const uint MOUSEEVENTF_LEFTUP = 0x0004;
    public const uint MOUSEEVENTF_ABSOLUTE = 0x8000;
    public const uint KEYEVENTF_KEYUP = 0x0002;
}
"@

function Screenshot {
    param([string]$Path, [string]$Monitor)

    if ($Monitor -eq "all") {
        $left = [System.Windows.Forms.SystemInformation]::VirtualScreen.Left
        $top = [System.Windows.Forms.SystemInformation]::VirtualScreen.Top
        $width = [System.Windows.Forms.SystemInformation]::VirtualScreen.Width
        $height = [System.Windows.Forms.SystemInformation]::VirtualScreen.Height
    } elseif ($Monitor -match '^\d+$') {
        $idx = [int]$Monitor - 1
        $screens = [System.Windows.Forms.Screen]::AllScreens
        if ($idx -lt 0 -or $idx -ge $screens.Length) {
            Write-Error "Monitor $Monitor not found (have $($screens.Length) monitors)"
            exit 1
        }
        $bounds = $screens[$idx].Bounds
        $left = $bounds.X
        $top = $bounds.Y
        $width = $bounds.Width
        $height = $bounds.Height
    } else {
        # Primary monitor
        $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $left = $bounds.X
        $top = $bounds.Y
        $width = $bounds.Width
        $height = $bounds.Height
    }

    $bmp = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bmp)
    $graphics.CopyFromScreen($left, $top, 0, 0, (New-Object System.Drawing.Size($width, $height)))
    $bmp.Save($Path)
    $graphics.Dispose()
    $bmp.Dispose()
    Write-Host "screenshot:$left,$top,$width,$height,$Path"
}

function NormalizeCoords {
    # Convert absolute screen coords to 0-65535 normalized coords for SendInput
    param([int]$X, [int]$Y)
    $vLeft = [System.Windows.Forms.SystemInformation]::VirtualScreen.Left
    $vTop = [System.Windows.Forms.SystemInformation]::VirtualScreen.Top
    $vWidth = [System.Windows.Forms.SystemInformation]::VirtualScreen.Width
    $vHeight = [System.Windows.Forms.SystemInformation]::VirtualScreen.Height
    $nx = [int]((($X - $vLeft) * 65535) / ($vWidth - 1))
    $ny = [int]((($Y - $vTop) * 65535) / ($vHeight - 1))
    return @($nx, $ny)
}

function MouseMove {
    param([int]$X, [int]$Y)
    [WinInput]::SetCursorPos($X, $Y) | Out-Null
    Write-Host "moved:$X,$Y"
}

function MouseClick {
    param([int]$X, [int]$Y)
    [WinInput]::SetCursorPos($X, $Y) | Out-Null
    Start-Sleep -Milliseconds 50

    $down = New-Object WinInput+INPUT
    $down.type = [WinInput]::INPUT_MOUSE
    $down.u.mi.dwFlags = [WinInput]::MOUSEEVENTF_LEFTDOWN

    $up = New-Object WinInput+INPUT
    $up.type = [WinInput]::INPUT_MOUSE
    $up.u.mi.dwFlags = [WinInput]::MOUSEEVENTF_LEFTUP

    [WinInput]::SendInput(1, @($down), [Runtime.InteropServices.Marshal]::SizeOf([type][WinInput+INPUT])) | Out-Null
    Start-Sleep -Milliseconds 30
    [WinInput]::SendInput(1, @($up), [Runtime.InteropServices.Marshal]::SizeOf([type][WinInput+INPUT])) | Out-Null
    Write-Host "clicked:$X,$Y"
}

function MousePos {
    $point = New-Object WinInput+POINT
    [WinInput]::GetCursorPos([ref]$point) | Out-Null
    Write-Host "pos:$($point.X),$($point.Y)"
}

function FocusFirefox {
    # Find and focus Firefox before sending keys
    $focused = $false
    $callback = [WinInput+EnumWindowsProc]{
        param($hwnd, $lParam)
        $sb = New-Object System.Text.StringBuilder(256)
        [WinInput]::GetWindowText($hwnd, $sb, 256) | Out-Null
        $title = $sb.ToString()
        if ($title -match "Mozilla Firefox" -and [WinInput]::IsWindowVisible($hwnd)) {
            [WinInput]::SetForegroundWindow($hwnd) | Out-Null
            $script:focused = $true
            return $false  # stop enumerating
        }
        return $true
    }
    [WinInput]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
    Start-Sleep -Milliseconds 100
    return $script:focused
}

function KeyPress {
    param([string]$Keys)
    FocusFirefox | Out-Null
    Start-Sleep -Milliseconds 50
    [System.Windows.Forms.SendKeys]::SendWait($Keys)
    Write-Host "key:$Keys"
}

function ClipSet {
    param([string]$Text)
    [System.Windows.Forms.Clipboard]::SetText($Text)
    # Re-focus Firefox after clipboard operation
    FocusFirefox | Out-Null
    Write-Host "clipboard:set"
}

function ClipSetFile {
    param([string]$FilePath)
    $text = [System.IO.File]::ReadAllText($FilePath)
    [System.Windows.Forms.Clipboard]::SetText($text)
    # Re-focus Firefox after clipboard operation
    FocusFirefox | Out-Null
    Write-Host "clipboard:set_from_file"
}

function ClipGet {
    $text = [System.Windows.Forms.Clipboard]::GetText()
    Write-Host "CLIPSTART"
    Write-Host $text
    Write-Host "CLIPEND"
}

function FindFirefox {
    $found = $false
    $callback = [WinInput+EnumWindowsProc]{
        param($hwnd, $lParam)
        $sb = New-Object System.Text.StringBuilder(256)
        [WinInput]::GetWindowText($hwnd, $sb, 256) | Out-Null
        $title = $sb.ToString()
        if ($title -match "Mozilla Firefox" -and [WinInput]::IsWindowVisible($hwnd)) {
            $rect = New-Object WinInput+RECT
            [WinInput]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
            Write-Host "firefox:$($hwnd.ToInt64()),$($rect.Left),$($rect.Top),$($rect.Right - $rect.Left),$($rect.Bottom - $rect.Top),$title"
            $script:found = $true
        }
        return $true
    }
    [WinInput]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
    if (-not $script:found) {
        Write-Host "firefox:notfound"
    }
}

function MoveFirefox {
    param([int]$X, [int]$Y, [int]$W, [int]$H)
    $callback = [WinInput+EnumWindowsProc]{
        param($hwnd, $lParam)
        $sb = New-Object System.Text.StringBuilder(256)
        [WinInput]::GetWindowText($hwnd, $sb, 256) | Out-Null
        $title = $sb.ToString()
        if ($title -match "Mozilla Firefox" -and [WinInput]::IsWindowVisible($hwnd)) {
            [WinInput]::MoveWindow($hwnd, $X, $Y, $W, $H, $true) | Out-Null
            [WinInput]::SetForegroundWindow($hwnd) | Out-Null
            Write-Host "moved_firefox:$X,$Y,$W,$H"
        }
        return $true
    }
    [WinInput]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
}

function ConsoleExec {
    # Execute a JS command in Firefox's Web Console (all in one PS process to preserve focus).
    # Reads the JS from a temp file to avoid escaping issues.
    param([string]$FilePath)

    $js = [System.IO.File]::ReadAllText($FilePath).Trim()

    # 1. Focus Firefox
    FocusFirefox | Out-Null
    Start-Sleep -Milliseconds 300

    # 2. Dismiss any open dialogs/popups (Escape twice for safety)
    [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
    Start-Sleep -Milliseconds 500

    # 3. Open Web Console (Ctrl+Shift+K)
    [System.Windows.Forms.SendKeys]::SendWait("^(+(k))")
    Start-Sleep -Milliseconds 3000

    # 4. Set clipboard to JS command (no FocusFirefox call — preserves console focus)
    [System.Windows.Forms.Clipboard]::SetText($js)
    Start-Sleep -Milliseconds 300

    # 5. Paste into console input (Ctrl+V)
    [System.Windows.Forms.SendKeys]::SendWait("^v")
    Start-Sleep -Milliseconds 500

    # 6. Execute (Enter)
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
    Start-Sleep -Milliseconds 2000

    # 7. Close Web Console
    [System.Windows.Forms.SendKeys]::SendWait("^(+(k))")
    Start-Sleep -Milliseconds 300

    Write-Host "console_exec:ok"
}

function MonitorInfo {
    foreach ($screen in [System.Windows.Forms.Screen]::AllScreens) {
        $b = $screen.Bounds
        Write-Host "monitor:$($screen.DeviceName),$($b.X),$($b.Y),$($b.Width),$($b.Height),$($screen.Primary)"
    }
}

# Dispatch
switch ($Command) {
    "screenshot"    { Screenshot -Path $Args[0] -Monitor $Args[1] }
    "mouse_move"    { MouseMove -X ([int]$Args[0]) -Y ([int]$Args[1]) }
    "mouse_click"   { MouseClick -X ([int]$Args[0]) -Y ([int]$Args[1]) }
    "mouse_pos"     { MousePos }
    "key"           { KeyPress -Keys $Args[0] }
    "clip_set"      { ClipSet -Text ($Args -join " ") }
    "clip_set_file" { ClipSetFile -FilePath $Args[0] }
    "clip_get"      { ClipGet }
    "find_firefox"  { FindFirefox }
    "move_firefox"  { MoveFirefox -X ([int]$Args[0]) -Y ([int]$Args[1]) -W ([int]$Args[2]) -H ([int]$Args[3]) }
    "monitors"      { MonitorInfo }
    "console_exec"  { ConsoleExec -FilePath $Args[0] }
    default         { Write-Host "Unknown command: $Command"; exit 1 }
}
