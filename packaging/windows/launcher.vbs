' Abre Nexo (dentro de WSL) sin mostrar ninguna consola.
Set sh = CreateObject("WScript.Shell")
sh.Run "wsl.exe -d Nexo --cd ~ -- env GDK_BACKEND=x11 nexo", 0, False
