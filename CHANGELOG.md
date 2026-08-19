# Changelog

## v0.2.1 — 19 Agustus 2026

### Perbaikan

- **Akun tampil dengan nama yang salah.** Baris akun Claude Code dinamai dari
  `~/.claude.json`, yang hanya mencatat akun terakhir yang login di file itu —
  bisa berbeda dari pemilik token di `.credentials.json`. Akibatnya dua baris
  bisa bernama sama, dan pemakaian satu akun terbaca di bawah nama akun lain.
  Panggilan profil yang seharusnya mengoreksi ini tidak pernah jalan sejak
  v0.2.0, karena syaratnya cuma "email sudah terisi" — padahal tebakan dari
  `~/.claude.json` juga berbentuk email. Sekarang identitas hanya dianggap
  sah kalau benar-benar berasal dari `/api/oauth/profile`.
- Menambah atau menghapus akun tidak lagi mengembalikan nama ke tebakan awal.

## v0.2.0 — 19 Agustus 2026

### Linux

- Berjalan di Linux, bukan cuma Windows. Autostart lewat entri XDG di
  `~/.config/autostart`, lokasi file mengikuti XDG base directory, dan token
  akun tambahan disimpan di keyring sesi (SecretStorage) kalau tersedia —
  kalau tidak, file `0600` yang dilaporkan apa adanya, tanpa mengklaim
  enkripsi yang tidak ada.
- `installer/linux/install.sh` dan `uninstall.sh`: pasang per-user tanpa sudo,
  lengkap dengan entri menu aplikasi, ikon, dan autostart.
- Peringatan saat sesi Wayland, karena compositor bisa mengabaikan
  always-on-top. Sesi X11 berperilaku normal.
- Belum ada binary siap pakai untuk Linux: PyInstaller tidak bisa
  cross-compile, jadi harus dibuild di Linux.

### Perbaikan

- Restart aplikasi tidak lagi memicu request API kalau data di cache masih
  segar, dan panggilan profil dilewati setelah nama akun diketahui. Ini yang
  sebelumnya memicu `HTTP 429` saat pengembangan.
- Diagnostik jujur: `current_command()` membaca shortcut yang benar-benar
  terpasang, dan CLI debug memakai cache identitas yang sama dengan overlay.

### Struktur

- `installer/` dipisah menjadi `installer/windows/` dan `installer/linux/`.

## v0.1.0 — 19 Agustus 2026

Rilis pertama.

### Fitur

- Overlay mini bar always-on-top: sisa kuota 5 jam dan mingguan per akun,
  waktu reset terdekat, bisa digeser, posisi tersimpan.
- Panel detail: semua bucket per akun (termasuk weekly per-model), waktu reset
  absolut dan relatif, status usage credits.
- Multi-akun: akun Claude Code terdeteksi otomatis; akun lain ditambah lewat
  login browser (loopback redirect, tanpa menyalin kode).
- Token Claude Code di-refresh sendiri dan ditulis balik secara atomic, jadi
  angka tetap segar walau Claude Code tidak dijalankan.
- Tray icon berwarna sesuai kondisi terburuk, plus notifikasi di ambang 80%
  dan 95% dan saat kuota reset.
- Dua tema: Cyberpunk (default) dan Dark.
- Installer per-user tanpa admin: Start Menu, desktop, entri uninstall di
  Settings → Apps, dan opsi nyala saat login.

### Catatan teknis

- Interval polling default 5 menit, mengikuti cache Claude Code sendiri.
  Lantai keras 60 detik. Backoff 5m → 10m → 15m → 30m saat error, dan header
  `Retry-After` selalu menang.
- Saat API menolak, angka terakhir tetap ditampilkan (diredupkan) dengan alasan
  singkat dan hitung mundur percobaan berikutnya.
- Hanya satu instance yang boleh berjalan; peluncuran kedua memunculkan panel
  instance yang sudah jalan.
- Semua data lokal: tidak ada telemetri, token tidak pernah masuk log, akun
  tambahan disimpan terenkripsi DPAPI.
