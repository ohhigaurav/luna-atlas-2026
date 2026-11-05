# Running Luna Atlas on Windows

You need the file `luna-atlas-complete.tar.gz` (code + data in one) and an internet connection
for the first start (it installs Python and Node packages). Everything runs inside WSL, a real
Ubuntu inside Windows, so the commands are the same as on the team's Linux machines.

## Once: install WSL

Open **PowerShell as administrator** (Start menu → type PowerShell → right-click → Run as
administrator) and run:

```
wsl --install
```

Restart Windows when it asks. Then open **Ubuntu** from the Start menu and pick a user name and
password (the password is what `sudo` asks for later; typing shows nothing, that is normal).

## Once: unpack and set up

In the Ubuntu window, one line at a time. Replace `YOUR_NAME` with your Windows user name (the
folder name under `C:\Users\`). Unpack inside Ubuntu, not with Windows Explorer: Explorer breaks
the scripts.

```
cd ~
tar xzf /mnt/c/Users/YOUR_NAME/Downloads/luna-atlas-complete.tar.gz
cd luna-atlas
bash scripts/setup_wsl.sh
```

The first start takes several minutes (packages, then building the app). When the window shows
`Uvicorn running on http://127.0.0.1:8000`, open **http://127.0.0.1:8000** in your normal Windows
browser (Chrome or Edge).

On the very first opening the pins take a few minutes to turn green; the top right says how long
is left. Leave the Ubuntu window open while you use the app; Ctrl+C in it stops the server.

## Every time after that

Open Ubuntu, then:

```
cd ~/luna-atlas
bash scripts/run_local.sh
```

## A newer version

You get a new `luna-atlas-complete.tar.gz`. In Ubuntu:

```
cd ~
rm -rf luna-atlas
tar xzf /mnt/c/Users/YOUR_NAME/Downloads/luna-atlas-complete.tar.gz
cd luna-atlas
bash scripts/run_local.sh
```

## If something goes wrong

- `wsl --install` says WSL is already installed: just open Ubuntu from the Start menu.
- The browser says it cannot connect: the Ubuntu window must still be running the server.
- The page says "The Luna Atlas app is not built yet": run `bash scripts/run_local.sh` again with
  internet on (the app build needs to download Node packages once).
- Anything else: copy the last 30 lines of the Ubuntu window and send them to the team.

`PACKAGED_FROM_COMMIT.txt` says which version of the code you have.
