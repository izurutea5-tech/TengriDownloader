"""Үйлдлийн системээс хамаарах жижиг туслахууд: хавтас нээх, хавтас/файл сонгох цонх (Windows, macOS, Linux)."""
import os
import shutil
import subprocess
import sys

WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")
NOWIN = 0x08000000 if WIN else 0  # CREATE_NO_WINDOW


def platform_name():
    return "windows" if WIN else "macos" if MAC else "linux"


def open_path(path):
    """Хавтас эсвэл файлыг системийн файл хөтөчөөр нээнэ."""
    if not path or not os.path.exists(path):
        return False
    try:
        if WIN:
            os.startfile(path)  # noqa
        elif MAC:
            subprocess.Popen(["open", path])
        else:
            opener = shutil.which("xdg-open") or shutil.which("gio")
            if not opener:
                return False
            subprocess.Popen([opener, "open", path] if opener.endswith("gio") else [opener, path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def _run(cmd, timeout=600):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def pick(kind="folder", title="Сонгох"):
    """Системийн сонгох цонх. kind: folder | zip (архив) | file. Цуцалбал хоосон мөр."""
    folder = kind == "folder"
    if WIN:
        if folder:
            ps = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$d=New-Object System.Windows.Forms.FolderBrowserDialog;$d.Description='%s';"
                  "if($d.ShowDialog() -eq 'OK'){[Console]::OutputEncoding=[Text.Encoding]::UTF8;$d.SelectedPath}") % title
        else:
            flt = "Archives (*.zip;*.tar.gz;*.tgz)|*.zip;*.tar.gz;*.tgz|All files (*.*)|*.*" if kind == "zip" else "All files (*.*)|*.*"
            ps = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$d=New-Object System.Windows.Forms.OpenFileDialog;$d.Filter='%s';"
                  "if($d.ShowDialog() -eq 'OK'){[Console]::OutputEncoding=[Text.Encoding]::UTF8;$d.FileName}") % flt
        return _run(["powershell", "-NoProfile", "-STA", "-Command", ps])
    if MAC:
        what = "choose folder" if folder else "choose file"
        return _run(["osascript", "-e", f'POSIX path of ({what} with prompt "{title}")']).rstrip("/") or ""
    # Linux
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", f"--title={title}"]
        if folder:
            cmd.append("--directory")
        elif kind == "zip":
            cmd.append("--file-filter=Archives | *.zip *.tar.gz *.tgz")
        return _run(cmd)
    if shutil.which("kdialog"):
        home = os.path.expanduser("~")
        return _run(["kdialog", "--getexistingdirectory", home] if folder
                    else ["kdialog", "--getopenfilename", home, "*.zip *.tar.gz *.tgz" if kind == "zip" else "*"])
    # Сүүлийн арга: tkinter (тусдаа процесст — үндсэн thread-ийг саатуулахгүй)
    code = ("import tkinter as t,tkinter.filedialog as f;r=t.Tk();r.withdraw();r.attributes('-topmost',1);"
            + ("print(f.askdirectory() or '')" if folder else "print(f.askopenfilename() or '')"))
    if not getattr(sys, "frozen", False):
        return _run([sys.executable, "-c", code])
    return ""
