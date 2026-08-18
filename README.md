# Claude Limit Watcher

Overlay kecil buat **Windows dan Linux** yang nempel di atas window lain dan
nunjukin **sisa limit usage Claude** — session 5 jam, weekly, weekly per-model, plus usage
credits — buat satu atau banyak akun sekaligus.

```
● Vina   5h 54% ▰▰▰▱▱   7d 52% ▰▰▰▱▱   reset 59m
```

Klik mini bar → panel detail. Klik kanan → menu. Ada juga tray icon yang
warnanya ikut kondisi limit dan ngasih notifikasi waktu kelewat ambang.

## Install (Linux)

Belum ada binary siap pakai untuk Linux — pasang dari source (butuh `python3`
dan `git`):

```bash
git clone https://github.com/k41ts/claudelimitwatch.git
cd claudelimitwatch
./installer/linux/install.sh
```

Semuanya di dalam `$HOME`, **tanpa sudo**: venv sendiri di
`~/.local/share/climitwatch`, launcher `~/.local/bin/climitwatch`, entri menu
aplikasi, ikon, dan autostart XDG di `~/.config/autostart`.

Flag: `--no-autostart`, `--no-launch`, dan `--binary PATH` kalau kamu sudah
punya binary hasil PyInstaller.

Bikin binary sendiri (harus dijalankan **di** Linux, PyInstaller nggak bisa
cross-compile):

```bash
pip install pyinstaller
python tools/make_icon.py
pyinstaller --noconsole --onefile --name ClimitWatch --paths src launcher.py
./installer/linux/install.sh --binary dist/ClimitWatch
```

Cabut: `./installer/linux/uninstall.sh` (tambah `--purge` untuk sekalian menghapus
akun dan pengaturan).

### Yang perlu diperhatikan di Linux

- **Wayland**: compositor yang menentukan urutan tumpukan window, jadi
  always-on-top bisa diabaikan. Sesi **X11/Xorg** berperilaku seperti yang
  diharapkan. Aplikasi mendeteksi ini dan menulis peringatan di log saat mulai.
- **Tray icon**: butuh host StatusNotifier. KDE dan XFCE bawaan; GNOME perlu
  ekstensi seperti *AppIndicator Support*. Tanpa itu, mini bar tetap jalan,
  cuma tray-nya nggak muncul.
- **Penyimpanan token akun tambahan**: pakai keyring sesi (SecretStorage) kalau
  tersedia dan tidak terkunci; kalau tidak, jatuh ke file `0600` yang **tidak
  terenkripsi** — sama seperti `~/.claude/.credentials.json` milik Claude Code
  sendiri. Aplikasi melaporkan mana yang dipakai, tidak mengklaim lebih.
- Lokasi file mengikuti XDG: pengaturan di `~/.config/climitwatch`, data di
  `~/.local/share/climitwatch`.

## Install (Windows)

Build `.exe`-nya dulu, lalu jalanin installer per-user (nggak butuh admin):

```bash
.venv/Scripts/python.exe tools/make_icon.py
.venv/Scripts/pyinstaller.exe --noconsole --onefile --name ClimitWatch --paths src \n  --icon assets/climitwatch.ico --version-file installer/windows/version_info.txt launcher.py
```

```bash
powershell -ExecutionPolicy Bypass -File installer/windows/install.ps1
```

Ikon dan `--version-file` itu **bukan kosmetik**: tanpa `FileDescription` dan
`CompanyName` di exe, entri startup-nya nggak muncul di **Settings → Apps →
Startup** (halaman itu nampilin nama dari `FileDescription` dan publisher dari
`CompanyName`). Ikonnya digambar dari kode di `tools/make_icon.py`, jadi nggak
ada aset biner yang perlu dititipin di repo.

Yang dilakukan installer, semuanya di dalam profil user (`HKCU` + `%LOCALAPPDATA%`,
nggak nyentuh `Program Files` atau `HKLM`):

| Item | Lokasi |
|---|---|
| Aplikasi | `%LOCALAPPDATA%\Programs\ClimitWatch\ClimitWatch.exe` |
| Shortcut | Start Menu + Desktop |
| Start saat login | `HKCU\...\CurrentVersion\Run` |
| Entri uninstall | muncul di **Settings → Apps** |
| Data (akun, settings) | `%LOCALAPPDATA%\ClimitWatch` |

Flag yang tersedia: `-NoAutostart`, `-NoDesktopShortcut`, `-NoLaunch`, dan
`-Source <path ke exe>`.

**Uninstall** lewat Settings → Apps, atau:

```bash
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA/Programs/ClimitWatch/uninstall.ps1"
```

Secara default akun dan settings tetap disimpan biar install ulang nggak perlu
login lagi; tambahin `-Purge` kalau mau dihapus sekalian. Folder `~/.claude`
nggak pernah disentuh uninstaller.

**Start saat login** juga bisa dinyalain/dimatiin kapan aja dari dalam app:
**Settings → Start with Windows**. Registry yang jadi acuan, bukan file
settings — jadi kalau kamu matiin lewat Task Manager → Startup, app-nya ikut
tahu.

## Jalanin dari source


```bash
python -m venv .venv && .venv/Scripts/python.exe -m pip install -e ".[dev]"
```

```bash
.venv/Scripts/pythonw.exe -m climitwatch
```

Cek data tanpa GUI (berguna buat debug):

```bash
.venv/Scripts/python.exe -m climitwatch.debug
```

Bikin `.exe` mandiri:

```bash
.venv/Scripts/python.exe tools/make_icon.py
.venv/Scripts/pyinstaller.exe --noconsole --onefile --name ClimitWatch --paths src \n  --icon assets/climitwatch.ico --version-file installer/windows/version_info.txt launcher.py
```

## Tampilan

Dua tema, diganti di **Settings → Theme** (berlaku setelah restart):

- **Cyberpunk** (default) — sudut chamfer, border acid yellow, meter segmen
  miring dengan glow neon, scanline halus, teks mono kapital. Warna status:
  cyan aman → kuning ≥80% → pink ≥95%, dan titik status berkedip pas kondisi
  pink.
- **Dark** — versi tenang: sudut membulat, meter bar polos, teks normal.

Semua warna terpusat di `src/climitwatch/ui/theme.py` (`Palette`), jadi bikin
tema baru tinggal nambah satu entri di `PALETTES`.

## Akun

Ada dua sumber akun:

1. **Akun Claude Code** — dibaca dari `~/.claude/.credentials.json`, otomatis
   muncul tanpa setup. Access token cuma hidup ~1 jam, jadi app ini ikut
   me-refresh token itu dan nulis balik ke file yang sama (atomic, plus backup
   `.credentials.json.climitwatch.bak`). Kalau Claude Code kebetulan refresh
   duluan, app ngalah dan pakai token milik CLI; kalau CLI refresh pas request
   kita lagi jalan, hasil refresh kita cuma dipakai di memori dan file-nya
   nggak ditimpa. Nggak nyaman sama write-back? Nyalain **Settings → Never
   write ~/.claude/.credentials.json**; konsekuensinya angka jadi basi sekitar
   sejam setelah Claude Code terakhir dipakai.
2. **Akun tambahan** — lewat **Accounts → Add account… → Sign in with browser**.
   App nyalain listener lokal di `http://localhost:<port>/callback` (dual-stack,
   jadi `::1` maupun `127.0.0.1` kena) dan browser balik sendiri ke app begitu
   kamu approve — nggak ada kode yang perlu di-copy. Kalau listener-nya kehalang
   firewall, tombol **Use a code instead** balik ke alur copy-paste. Token akun
   ini disimpan di `%LOCALAPPDATA%/ClimitWatch/accounts.dat` (dienkripsi DPAPI,
   scope user saat ini), terpisah total dari login Claude Code.

## Cara kerjanya

Sumber datanya `GET https://api.anthropic.com/api/oauth/usage` — endpoint yang
sama yang dipakai layar `/usage` di Claude Code (dicek terhadap CLI 2.1.234).
Responsnya berisi array `limits[]` (`kind`, `percent`, `severity`, `resets_at`,
`scope.model`) plus key legacy `five_hour` / `seven_day` / `seven_day_opus` /
`seven_day_sonnet`. Parser-nya toleran: key baru yang belum dikenal tetap
tampil sebagai baris generik, key `null` dilewati.

Polling default **5 menit**, jadi 15 menit kalau mini bar disembunyiin dan 2
menit kalau ada limit ≥80%. Angka itu bukan asal: di dalam CLI, Claude Code
nyimpen hasil `/usage` dengan throttle tulis 5 menit (`i3b = 300000`) dan
nganggap datanya valid sampai 1 jam (`o3b = 3600000`). Polling lebih cepat dari
itu — apalagi barengan Claude Code yang juga manggil endpoint yang sama —
bakal kena **HTTP 429 `rate_limit_error`**. Ada lantai keras 60 detik yang
nggak bisa ditembus lewat Settings.

Kalau tetap kena error: seluruh loop mundur 5m → 10m → 15m → 30m, dan kalau
server ngirim header `Retry-After` itu yang dipakai. Angka terakhir tetap
ditampilin (diredupkan, dengan label alasan singkat kayak `RATE LIMITED BY THE
API`), bukan diganti dump JSON.

Cuma boleh ada **satu instance** yang jalan — dua salinan bikin request dobel.
Launch kedua bakal nyuruh yang lagi jalan buat munculin panelnya, lalu keluar.

## Batasan & catatan

- `/api/oauth/usage` itu **endpoint internal Claude Code**, bukan API publik.
  Bisa berubah kapan saja; kalau formatnya berubah, app nampilin pesan error,
  bukan crash.
- Overlay nggak bisa nutupin aplikasi **exclusive fullscreen** (game). Itu
  batasan Windows. Mode borderless/windowed fullscreen aman.
- Token adalah kredensial penuh akun. App ini 100% lokal: nggak ada telemetry,
  nggak ada upload, dan token nggak pernah masuk log.
- Jangan set interval polling di bawah 30 detik.

## Dokumen

| Dokumen | Isi |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Masalah, tujuan, kebutuhan, batasan, risiko |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Peta modul, alur data, keputusan teknis |
| [CHANGELOG.md](CHANGELOG.md) | Riwayat rilis |

## Struktur

| Path | Isi |
|---|---|
| `src/climitwatch/api/usage.py` | parser respons usage |
| `src/climitwatch/auth/cc_credentials.py` | baca/refresh kredensial Claude Code |
| `src/climitwatch/auth/oauth.py` | PKCE login + refresh token |
| `src/climitwatch/auth/store.py` | store akun tambahan (DPAPI) |
| `src/climitwatch/poller.py` | loop polling adaptif |
| `src/climitwatch/notify.py` | logika notifikasi ambang |
| `src/climitwatch/ui/` | mini bar, panel, tray, dialog |

Tes: `.venv/Scripts/python.exe -m pytest`
