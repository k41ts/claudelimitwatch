# PRD — Claude Limit Watcher

**Status:** v0.1.0 jalan di Windows 11; dukungan Linux ditulis dan diuji lewat
simulasi platform, belum dijalankan di desktop Linux sungguhan ·
**Terakhir diperbarui:** 19 Agustus 2026

---

## 1. Masalah

Pengguna Claude berlangganan (Pro/Max) punya kuota yang direset per 5 jam dan
per minggu, tapi satu-satunya cara melihat sisanya adalah membuka Claude Code
lalu mengetik `/usage`. Konsekuensinya:

- Kuota habis mendadak di tengah kerjaan, tanpa peringatan.
- Tidak ada cara melihat sisa kuota tanpa menghentikan apa yang sedang dikerjakan.
- Yang punya lebih dari satu akun harus login-logout untuk membandingkan.

## 2. Solusi

Overlay kecil yang selalu di atas jendela lain, menampilkan sisa kuota semua
akun sekaligus, plus notifikasi saat mendekati batas.

## 3. Pengguna sasaran

Pengguna Claude Code (Windows atau Linux) yang bekerja seharian dengan Claude,
terutama yang memegang lebih dari satu akun (pribadi + kerja/klien).

## 4. Tujuan

| # | Tujuan | Ukuran keberhasilan |
|---|---|---|
| G1 | Sisa kuota terlihat tanpa memutus pekerjaan | Angka terbaca tanpa klik apa pun |
| G2 | Beberapa akun dipantau bersamaan | ≥2 akun tampil di satu layar |
| G3 | Tetap akurat saat Claude Code tidak jalan | Data segar setelah 8 jam idle |
| G4 | Peringatan sebelum kuota habis | Notifikasi di 80% dan 95% |
| G5 | Nyala sendiri saat komputer dinyalakan | Muncul tanpa aksi pengguna |

## 5. Bukan tujuan (non-goals)

- **Bukan** alat penghitung biaya token per proyek — sudah ada `ccusage`.
- **Bukan** lintas platform penuh. Windows dan Linux (X11); macOS di luar
  lingkup karena Claude Code menyimpan kredensialnya di Keychain, bukan di
  `~/.claude/.credentials.json`.
- **Bukan** layanan berbagi/telemetri. Semua data tinggal di mesin pengguna.
- **Tidak** mengubah perilaku Claude Code, hanya membaca.
- **Tidak** menampilkan riwayat/grafik jangka panjang di v0.1.

## 6. Kebutuhan fungsional

### 6.1 Sumber data

| Aspek | Keputusan |
|---|---|
| Endpoint | `GET https://api.anthropic.com/api/oauth/usage` |
| Auth | Bearer token OAuth milik pengguna |
| Bucket | `limits[]` sebagai sumber utama; key legacy (`five_hour`, `seven_day`, `seven_day_opus`, `seven_day_sonnet`) sebagai pelengkap |
| Toleransi | Key tak dikenal tampil generik; key `null` dilewati; payload rusak → pesan error, bukan crash |

Endpoint ini **internal milik Claude Code**, bukan API publik bergaransi.
Diverifikasi terhadap CLI 2.1.234. Risiko dan mitigasinya di §9.

### 6.2 Akun

| ID | Kebutuhan |
|---|---|
| A1 | Akun yang sedang login di Claude Code terdeteksi otomatis tanpa setup |
| A2 | Akun tambahan lewat login browser, tanpa menyalin kode apa pun |
| A3 | Token akun tambahan disimpan seaman yang platform sediakan: DPAPI (Windows), keyring sesi (Linux), dan file 0600 sebagai fallback yang dilaporkan apa adanya |
| A4 | Refresh token akun tambahan tidak boleh mengganggu sesi Claude Code |
| A5 | Nama akun tidak boleh bergantung pada request yang bisa gagal |

### 6.3 Token Claude Code

Access token hanya hidup ~1 jam (8 jam setelah refresh). Agar tetap akurat
saat Claude Code tidak berjalan, aplikasi ikut me-refresh dan menulis balik ke
`~/.claude/.credentials.json`.

| ID | Kebutuhan |
|---|---|
| T1 | Penulisan atomic (`os.replace`) dan menyisakan backup |
| T2 | Semua field lain (`mcpOAuth`, `trustedDeviceToken`, dll.) dipertahankan utuh |
| T3 | Jika CLI menang balapan refresh, aplikasi mengalah dan memakai token CLI |
| T4 | Jika CLI merotasi token saat request kita berjalan, file tidak ditimpa |
| T5 | Ada mode read-only yang mematikan penulisan sepenuhnya |

### 6.4 Polling

| ID | Kebutuhan |
|---|---|
| P1 | Interval default 5 menit, mengikuti cache CLI (`i3b = 300000`) |
| P2 | Lantai keras 60 detik yang tidak bisa ditembus lewat Settings |
| P3 | Melambat jadi 15 menit saat overlay disembunyikan |
| P4 | Mempercepat jadi 2 menit saat ada bucket ≥80% |
| P5 | Backoff 5m → 10m → 15m → 30m saat error; header `Retry-After` menang |
| P6 | Satu error membuat seluruh loop mundur (rate limit berlaku per akun/IP) |
| P7 | Hanya satu instance aplikasi yang boleh berjalan |

### 6.5 Tampilan

| ID | Kebutuhan |
|---|---|
| U1 | Mini bar frameless, always-on-top, bisa digeser, posisi tersimpan |
| U2 | Satu baris per akun: nama, sisa 5 jam, sisa mingguan, waktu reset terdekat |
| U3 | Klik → panel detail semua bucket; klik kanan → menu |
| U4 | Tray icon berwarna sesuai kondisi terburuk + tooltip ringkas |
| U5 | Saat error, angka terakhir tetap tampil (diredupkan) + alasan singkat + hitung mundur retry |
| U6 | Dua tema: Cyberpunk (default) dan Dark |

### 6.6 Notifikasi

Toast saat sebuah bucket melewati 80% dan 95%, sekali per ambang per jendela,
dan kembali aktif setelah reset. Kondisi awal saat aplikasi dibuka tidak
memicu notifikasi.

### 6.7 Instalasi

| ID | Kebutuhan |
|---|---|
| I1 | Instalasi per-user, tanpa admin/sudo (Windows: tanpa UAC) |
| I2 | Terdaftar di manajer aplikasi OS (Windows: Settings → Apps; Linux: menu aplikasi + ikon) |
| I3 | Bisa nyala saat login, dan bisa dimatikan dari dalam aplikasi |
| I4 | Uninstall bersih; data akun dipertahankan kecuali diminta `-Purge` / `--purge` |
| I5 | Installer menghentikan instance lama sebelum memasang yang baru |

## 7. Kebutuhan non-fungsional

- **Privasi:** tidak ada telemetri, tidak ada koneksi selain ke API Anthropic.
  Token tidak pernah masuk log.
- **Sopan ke API:** tidak pernah polling lebih cepat dari CLI resmi.
- **Jejak ringan:** overlay diam saat tidak ada perubahan; timer kedip hanya
  aktif saat ada kondisi kritis.
- **Tahan gagal:** kehilangan jaringan, token kedaluwarsa, atau perubahan
  format respons tidak boleh membuat aplikasi mati.

## 8. Alur utama

1. **Pertama kali dijalankan** — akun Claude Code terdeteksi otomatis, angka
   muncul dalam hitungan detik.
2. **Menambah akun** — Tray → Accounts → Add account → Sign in with browser →
   browser kembali sendiri ke aplikasi.
3. **Mendekati batas** — meter menguning di 80%, toast muncul; memerah dan
   titik statusnya berkedip di 95%.
4. **API menolak** — angka terakhir tetap tampil dengan label `rate limited 12m`;
   tombol Refresh memaksa percobaan ulang segera.

## 9. Risiko

| Risiko | Mitigasi |
|---|---|
| Endpoint internal berubah sewaktu-waktu | Parser toleran; pesan jelas, bukan crash; versi CLI acuan dicatat |
| Balapan refresh token dengan CLI | Protokol baca-ulang sebelum & sesudah refresh (§6.3) |
| Rate limit | Interval mengikuti CLI + backoff + single instance |
| Token adalah kredensial penuh | Semua lokal, DPAPI/keyring, tidak pernah di-log |
| Overlay tertutup game fullscreen | Batasan Windows; didokumentasikan, bukan bug |
| Wayland mengabaikan always-on-top | Terdeteksi saat start dan diperingatkan; X11 berperilaku normal |

## 10. Status

**Windows** — semua kebutuhan di atas terpasang dan diverifikasi langsung di
Windows 11 (1920×1080, 150% scaling): overlay, multi-akun, refresh token,
installer, autostart.

**Linux** — jalur kodenya lengkap (backend autostart XDG, path XDG, keyring,
installer `install.sh`/`uninstall.sh`) dan diuji lewat simulasi platform di
suite yang sama, tapi **belum pernah dijalankan di desktop Linux sungguhan**.
Yang belum terbukti: rendering overlay, perilaku always-on-top, tray icon, dan
apakah desktop environment benar-benar menjalankan entri autostart-nya.

92 test otomatis.

Belum dikerjakan: riwayat/grafik pemakaian, dukungan akun Team/Enterprise
(`member_dashboard_available`), auto-update, dan binary siap pakai untuk Linux
(PyInstaller tidak bisa cross-compile, harus dibuild di Linux).
