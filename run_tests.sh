cd "$(dirname "$0")" || exit 1
[ -f venv/bin/activate ] && source venv/bin/activate

NAME="tc_laporan.txt"
FILE="/tmp/$NAME"
REMOTE_DIR="${REMOTE_PRIMARY_DIR:-~/dcsm-project/storage-primary/data/files}"
AUDIT="logs/audit_log.jsonl"
[ -f "$AUDIT" ] || AUDIT="audit_log.jsonl"

GREEN='\033[32m'; RED='\033[31m'; YELLOW='\033[33m'; BOLD='\033[1m'; NC='\033[0m'
PASS=0; FAIL=0

ok()    { echo -e "  ${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); }
bad()   { echo -e "  ${RED}[FAIL]${NC} $1"; FAIL=$((FAIL+1)); }
info()  { echo -e "  ${YELLOW}[INFO]${NC} $1"; }
title() { echo -e "\n${BOLD}== $1 ==${NC}"; }
show()  { echo "$1" | sed 's/^/      /'; }
pause() { echo -e "  ${YELLOW}>>> $1${NC}"; read -r -p "      Tekan Enter jika sudah... " _; }
cli()   { (cd client && python client.py "$@" 2>&1); }

if docker compose ps --services --status running 2>/dev/null | grep -qx "storage-primary"; then
  MODE="otomatis (Storage lokal di Docker)"; AUTO=1
else
  MODE="manual (Storage di laptop lain)"; AUTO=0
fi
echo -e "${BOLD}Pengujian Secure Distributed File Storage System${NC}"
echo "Mode: $MODE"

# ---------------------------------------------------------------- TC-01
title "TC-01: Upload oleh user berwenang"
echo "ini file rahasia perusahaan" > "$FILE"
OUT=$(cli upload budi "$FILE" Confidential); show "$OUT"
echo "$OUT" | grep -q "Success: True" && ok "Upload budi (label Confidential) berhasil" || bad "Upload gagal"
SUM=$(echo "$OUT" | awk '/Checksum:/ {print $2}')

cli list budi | grep -q "$NAME" && ok "Berkas muncul pada list" || bad "Berkas tidak muncul pada list"

OUT=$(cli download budi "$NAME"); show "$OUT"
if echo "$OUT" | grep -q "Success: True" && [ -n "$SUM" ] && echo "$OUT" | grep -q "$SUM"; then
  ok "Download berhasil, checksum SHA-256 sama dengan saat upload"
else
  bad "Download gagal atau checksum berbeda"
fi

if [ "$AUTO" = 1 ]; then
  docker compose exec -T storage-backup ls /data/files 2>/dev/null | grep -q "$NAME" \
    && ok "Berkas tereplikasi ke Backup" || bad "Berkas tidak ditemukan di Backup"
else
  info "Replikasi: tunjukkan di laptop Storage dengan ls pada folder data Backup"
fi
[ -f "$AUDIT" ] && tail -n 10 "$AUDIT" | grep '"user": "budi"' | grep -q '"decision": "ALLOW"' \
  && ok "Audit log mencatat ALLOW" || info "Audit log tidak ditemukan di $AUDIT"

# ---------------------------------------------------------------- TC-02
title "TC-02: Pelanggaran Bell-LaPadula (user Public membaca berkas Confidential)"
OUT=$(cli download citra "$NAME"); show "$OUT"
if echo "$OUT" | grep -q "Success: False" && echo "$OUT" | grep -q "Clearance"; then
  ok "citra (Public) ditolak mengunduh berkas Confidential"
else
  bad "citra seharusnya ditolak"
fi
if cli list citra | grep -q "$NAME"; then
  bad "list citra masih menampilkan berkas Confidential"
else
  ok "list citra tidak menampilkan berkas Confidential"
fi
[ -f "$AUDIT" ] && tail -n 20 "$AUDIT" | grep '"user": "citra"' | grep -q '"decision": "DENY"' \
  && ok "Audit log mencatat DENY" || info "Audit log DENY tidak ditemukan di $AUDIT"

# ---------------------------------------------------------------- TC-03
title "TC-03: Integritas berkas (SHA-256)"
if [ "$AUTO" = 1 ]; then
  docker compose exec -T storage-primary sh -c "echo DIUBAH-ILEGAL >> /data/files/$NAME"
else
  pause "Di laptop Storage, ubah berkas Primary:\n      echo DIUBAH-ILEGAL >> $REMOTE_DIR/$NAME"
fi
OUT=$(cli download budi "$NAME"); show "$OUT"
if echo "$OUT" | grep -q "Success: False" && echo "$OUT" | grep -q "Integritas"; then
  ok "Berkas yang diubah di disk terdeteksi rusak saat download"
else
  bad "Perubahan berkas tidak terdeteksi"
fi
info "Memulihkan berkas (hapus oleh admin1, upload ulang oleh budi)"
cli delete admin1 "$NAME" > /dev/null
cli upload budi "$FILE" Confidential > /dev/null

# ---------------------------------------------------------------- TC-04
title "TC-04: Koneksi tanpa sertifikat client"
TARGET=$(grep -m1 '^TARGET' client/client.py | cut -d'"' -f2)
OUT=$(TARGET="$TARGET" CA="ca certificate/ca-cert.pem" python - 2>&1 << 'PYEOF'
import grpc, os
target = os.environ["TARGET"]
with open(os.environ["CA"], "rb") as f:
    root = f.read()

def rejected(channel):
    try:
        grpc.channel_ready_future(channel).result(timeout=5)
        return False
    except grpc.FutureTimeoutError:
        return True

r1 = rejected(grpc.secure_channel(target, grpc.ssl_channel_credentials(root_certificates=root)))
r2 = rejected(grpc.insecure_channel(target))
print("TLS_TANPA_SERTIFIKAT=" + ("DITOLAK" if r1 else "TERSAMBUNG"))
print("TANPA_TLS=" + ("DITOLAK" if r2 else "TERSAMBUNG"))
PYEOF
)
show "$OUT"
echo "$OUT" | grep -q "TLS_TANPA_SERTIFIKAT=DITOLAK" && ok "TLS tanpa sertifikat client ditolak" || bad "TLS tanpa sertifikat client tersambung"
echo "$OUT" | grep -q "TANPA_TLS=DITOLAK" && ok "Koneksi tanpa TLS ditolak" || bad "Koneksi tanpa TLS tersambung"

# ---------------------------------------------------------------- TC-05
title "TC-05: Failover ke Backup saat Primary mati"
KILL_HINT='kill $(ss -ltnp | grep ":50053" | grep -o "pid=[0-9]*" | cut -d= -f2)'
if [ "$AUTO" = 1 ]; then
  docker compose stop storage-primary > /dev/null 2>&1
else
  pause "Di laptop Storage, matikan HANYA Primary:\n      $KILL_HINT"
fi
OUT=$(cli download budi "$NAME"); show "$OUT"
if echo "$OUT" | grep -q "Success: True" && [ -n "$SUM" ] && echo "$OUT" | grep -q "$SUM"; then
  ok "Download tetap berhasil dari Backup, checksum identik"
else
  bad "Failover gagal"
fi
if [ "$AUTO" = 1 ]; then
  docker compose start storage-primary > /dev/null 2>&1; sleep 5
else
  pause "Di laptop Storage, nyalakan kembali dengan ./start_storage.sh"
fi

# ---------------------------------------------------------------- Selesai
cli delete admin1 "$NAME" > /dev/null
rm -f "client/downloaded_$NAME" "$FILE"

title "Ringkasan"
echo -e "  ${GREEN}PASS: $PASS${NC}   ${RED}FAIL: $FAIL${NC}"
[ "$FAIL" -eq 0 ]
