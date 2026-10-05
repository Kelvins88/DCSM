# Secure Distributed File Storage System

Proyek UTS Distributed Computing Security Model. Sistem penyimpanan berkas terdistribusi dengan keamanan transport (mTLS), otorisasi (RBAC dan Bell-LaPadula), integritas berkas (SHA-256), replikasi Primary-Backup, dan audit log JSON.

## Arsitektur

Client -> API Gateway (gRPC, mTLS, port 50052) -> Storage Primary (port 50053) -> Storage Backup (replikasi sinkron).
Jika Primary tidak dapat dihubungi, Gateway beralih otomatis ke Backup.

## Struktur Folder

| Folder / berkas | Isi |
| --- | --- |
| `proto/storage.proto` | Kontrak gRPC: Upload, Download, List, Delete |
| `gateway/` | API Gateway (autentikasi token, RBAC, Bell-LaPadula, audit log, failover) |
| `storage/storage-primary`, `storage/storage-backup` | Storage Node beserta sertifikatnya |
| `client/` | Client baris perintah |
| `ca certificate/` | Sertifikat CA dan sertifikat client |
| `users.json` | Daftar pengguna uji (token, peran, clearance) |
| `docker-compose.yml`, `docker-compose.override.yml` | Deployment satu mesin |
| `docker-compose.zerotier.yml` | Override untuk Storage di laptop terpisah |
| `run_tests.sh` | Skrip pengujian TC-01 sampai TC-05 |

## Prasyarat

- Docker dan Docker Compose v2
- Python 3.11+ untuk client: `pip install grpcio==1.84.0 protobuf==7.36.2`

## Menjalankan (satu mesin)

Kunci privat Gateway tidak disertakan di repository karena alasan keamanan. Siapkan folder `certs/` terlebih dahulu:

```bash
mkdir -p certs
cp "ca certificate/ca-cert.pem" "ca certificate/gateway-cert.pem" certs/
# letakkan gateway-key.pem (disediakan terpisah oleh tim) di certs/
```

Lalu jalankan seluruh sistem:

```bash
docker compose up --build -d
docker compose ps
```

## Pengguna Uji

| Pengguna | Peran | Clearance | Hak akses |
| --- | --- | --- | --- |
| admin1 | admin | Secret | upload, download, list, delete |
| budi | staff | Confidential | upload, download, list |
| citra | guest | Public | download, list |

Aturan Bell-LaPadula: membaca dan menampilkan daftar hanya untuk berkas berlabel setara atau di bawah clearance (no read-up). Mengunggah hanya ke label setara atau di atas clearance (no write-down).

## Memakai Client

```bash
cd client
python client.py upload budi /tmp/laporan.txt Confidential
python client.py list budi
python client.py download budi laporan.txt
python client.py delete admin1 laporan.txt
```

## Pengujian

```bash
./run_tests.sh
```

| ID | Skenario | Cara |
| --- | --- | --- |
| TC-01 | Upload oleh user berwenang, tereplikasi, audit ALLOW | `run_tests.sh` |
| TC-02 | Pelanggaran Bell-LaPadula, audit DENY | `run_tests.sh` |
| TC-03 | Berkas diubah di disk terdeteksi (SHA-256) | `run_tests.sh` |
| TC-04 | Koneksi tanpa sertifikat ditolak | `run_tests.sh` |
| TC-05 | Primary mati, baca dialihkan ke Backup | `run_tests.sh` |
| TC-06 | `docker compose up` kurang dari 3 menit | `time docker compose up --build -d` |

## Mode Laptop Terpisah (ZeroTier)

Storage dijalankan di laptop lain yang tergabung dalam jaringan ZeroTier yang sama (Primary port 50053, Backup port 50054). Pada laptop Gateway, jalankan hanya Gateway:

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.zerotier.yml up -d --build --no-deps gateway
```

## Catatan Keamanan

Seluruh token dan kunci pada repository ini adalah data uji untuk keperluan tugas kuliah, tidak untuk lingkungan produksi. Audit log Gateway tersimpan di `logs/audit_log.jsonl`.
