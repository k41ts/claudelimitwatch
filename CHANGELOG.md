# Changelog

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
