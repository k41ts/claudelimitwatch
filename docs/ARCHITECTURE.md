# Arsitektur

Catatan teknis Claude Limit Watcher: bentuk modul, alur data, dan keputusan
yang tidak jelas dari membaca kode saja.

## Peta modul

```
installer/
├── windows/                 install.ps1, uninstall.ps1, version_info.txt
└── linux/                   install.sh, uninstall.sh
launcher.py                  entry PyInstaller + entri logon (menaruh src/ di sys.path)
src/climitwatch/
├── __main__.py              QApplication, single-instance guard
├── app.py                   controller: menyambung poller ke widget
├── config.py                path, endpoint, Settings (JSON)
├── models.py                LimitBucket, UsageSnapshot, SpendInfo, Account
├── formatting.py            durasi, waktu lokal, teks ringkas
├── poller.py                loop polling di QThread + backoff
├── notify.py                logika ambang notifikasi (bebas Qt, mudah dites)
├── cache.py                 snapshot + identitas akun terakhir
├── autostart.py             Startup shortcut (Windows) / XDG entry (Linux)
├── single_instance.py       QLocalServer lock
├── accounts.py              registry akun: Claude Code + akun tambahan
├── api/
│   ├── client.py            HTTP, klasifikasi error, pesan untuk pengguna
│   └── usage.py             parser respons /api/oauth/usage
├── auth/
│   ├── cc_credentials.py    baca/refresh ~/.claude/.credentials.json
│   ├── oauth.py             PKCE, tukar kode, refresh token
│   ├── callback_server.py   listener loopback untuk login browser
│   └── store.py             akun tambahan: DPAPI / keyring / file 0600
└── ui/
    ├── theme.py             Palette + MeterBar + helper gambar
    ├── minibar.py           overlay always-on-top
    ├── panel.py             panel detail
    ├── tray.py              tray icon + menu
    ├── login_dialog.py      alur login browser
    ├── accounts_dialog.py   daftar akun
    ├── settings_dialog.py   preferensi
    └── win.py               tweak jendela Windows + peringatan Wayland
```

## Alur data

```
PollerWorker (QThread)
  └─ AccountManager.poll(source)
       ├─ source.ensure_fresh()        → refresh token bila perlu
       ├─ UsageClient.fetch_usage()    → GET /api/oauth/usage
       └─ parse_usage(payload)         → UsageSnapshot
  └─ signal snapshot_ready ──(queued)──▶ WatcherApp._on_snapshot
                                            ├─ simpan snapshot terakhir yang baik
                                            ├─ simpan pesan error terpisah
                                            ├─ ThresholdNotifier.check() → toast
                                            └─ render() → MiniBar / DetailPanel / Tray
```

Semua sinyal lintas thread memakai `Qt.ConnectionType.QueuedConnection`; widget
hanya disentuh dari thread UI.

## Keputusan penting

### Snapshot terakhir dipisah dari error

`WatcherApp` menyimpan dua dict: `snapshots` (hasil baik terakhir) dan `errors`
(alasan singkat). Polling gagal tidak pernah menghapus angka yang sudah ada —
angka lama diredupkan dan diberi label. Sebelumnya error menimpa snapshot, dan
overlay jadi kosong persis saat pengguna paling butuh melihat angkanya.

### Interval polling mengikuti CLI

Claude Code menyimpan hasil `/usage` dengan throttle tulis 5 menit
(`i3b = 300000`) dan menganggapnya valid sampai 1 jam (`o3b = 3600000`).
Angka-angka itu diambil dari bundle CLI 2.1.234 dan menjadi acuan default
aplikasi ini. Polling 60 detik (nilai awal yang sempat dipakai) memicu
`HTTP 429 rate_limit_error`.

### Protokol balapan token

`~/.claude/.credentials.json` dipakai bersama CLI, dan refresh token dirotasi
server. Urutan di `cc_credentials.ensure_fresh()`:

1. Refresh hanya jika sisa umur < 5 menit.
2. Baca ulang file tepat sebelum refresh — kalau CLI sudah merotasi, pakai
   token CLI dan batalkan.
3. Setelah refresh, baca ulang lagi — kalau file berubah selama request kita
   berjalan, **jangan** timpa; simpan token kita di memori saja.
4. Penulisan atomic lewat file sementara di direktori yang sama + `os.replace`.

### Identitas akun di-cache

Nama akun berasal dari `/api/oauth/profile`. Kalau request itu gagal (rate
limit), fallback-nya `~/.claude.json` — yang bisa menyebut akun berbeda dari
pemilik token sebenarnya. Karena itu identitas hasil resolve disimpan di
`cache.py` dan dipakai sejak startup, dengan pembeda otomatis kalau dua akun
tetap bernama sama.

### Body kartu dibangun ulang, bukan dibersihkan manual

Panel dirender ulang setiap beberapa detik. Membersihkan layout dengan tangan
melewatkan widget yang bersarang lebih dari satu level: label menumpuk (+6 tiap
render) sampai menutupi header. Sekarang body tiap kartu hidup di container
widget sendiri yang dibuang utuh (`deleteLater`) lalu dibuat ulang.

### Autostart: folder Startup (Windows), entri XDG (Linux)

Entri `HKCU\...\Run` berjalan saat logon tapi tidak muncul di
**Settings → Apps → Startup** pada Windows 11 yang diuji — halaman itu
menampilkan inventaris `StartupApproved`, bukan isi `Run` secara langsung.
Shortcut di folder Startup terlihat di Explorer, membawa nama dan ikon
aplikasi, dan tetap didampingi record `StartupApproved` (`0x02` = aktif) supaya
punya status On/Off. Entri `Run` versi lama dihapus saat enable, agar tidak ada
yang jalan dua kali.

Di Linux mekanismenya berbeda tapi API-nya sama: satu file
`~/.config/autostart/climitwatch.desktop`. Perlu diingat desktop kadang
mematikannya dengan menulis `X-GNOME-Autostart-enabled=false`, bukan menghapus
file-nya, jadi `is_enabled()` membaca isi file, bukan sekadar keberadaannya.

Exe wajib punya `FileDescription` dan `CompanyName` (lihat
`installer/windows/version_info.txt`) — tanpa itu Windows tidak punya nama maupun
publisher untuk ditampilkan.

### Single instance

Dua salinan menggandakan beban request. `single_instance.py` memegang
`QLocalServer`; peluncuran kedua mengirim ping lalu keluar, dan instance yang
berjalan memunculkan panelnya. Installer juga menghentikan instance lama
(termasuk yang dijalankan dari source lewat `pythonw`) sebelum memasang, lalu
memverifikasi aplikasi benar-benar hidup.

### Penyimpanan token lintas platform

Windows memakai DPAPI. Linux memakai keyring sesi lewat SecretStorage kalau
tersedia dan tidak terkunci; kalau tidak, file `0600` yang **tidak terenkripsi**.
`store.protection()` melaporkan mana yang berlaku supaya dokumen dan UI tidak
mengklaim proteksi yang tidak ada.

## Menjalankan test

```bash
.venv/Scripts/python.exe -m pytest
```

Test Qt memakai satu `QApplication` bersama dari `tests/conftest.py`. Membuat
`QCoreApplication` lebih dulu di modul lain membuat konstruksi widget
menggantung selamanya — itu sebabnya fixture-nya dipusatkan.

Test yang menyentuh registry menulis ke namespace `HKCU\Software\ClimitWatchTests\<uuid>`
dan membersihkannya; konfigurasi logon asli tidak pernah disentuh. Test
single-instance memakai nama socket unik agar tidak bentrok dengan aplikasi
yang sedang berjalan.
