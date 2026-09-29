import grpc
import os
import json
import hashlib
import logging
from datetime import datetime, timezone
from concurrent import futures

import storage_pb2
import storage_pb2_grpc

ROLE = os.environ.get("STORAGE_ROLE", "primary")          # "primary" atau "backup"
PORT = os.environ.get("STORAGE_PORT", "50053")
DATA_DIR = os.environ.get("DATA_DIR", "./data")
CERT_DIR = os.environ.get("CERT_DIR", "./certs")
REPLICATE_TO = os.environ.get("REPLICATE_TO")              # cth "192.168.1.20:50054", cuma diisi di Primary
AUDIT_LOG_FILE = os.path.join(DATA_DIR, "storage_audit_log.jsonl")

META_FILE = os.path.join(DATA_DIR, "metadata.json")
FILES_DIR = os.path.join(DATA_DIR, "files")

logging.basicConfig(level=logging.INFO, format=f"[{ROLE.upper()}] %(message)s")
log = logging.getLogger(__name__)


def ensure_dirs():
    os.makedirs(FILES_DIR, exist_ok=True)
    if not os.path.exists(META_FILE):
        with open(META_FILE, "w") as f:
            json.dump({}, f)


def load_meta():
    with open(META_FILE, "r") as f:
        return json.load(f)


def save_meta(meta):
    with open(META_FILE, "w") as f:
        json.dump(meta, f, indent=2)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_audit(action, filename, decision, detail=""):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "role": ROLE,
        "action": action,
        "filename": filename,
        "decision": decision,
        "detail": detail,
    }
    with open(AUDIT_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    log.info(f"{decision} | action={action} file={filename} {detail}")


def get_backup_stub():
    """Bikin koneksi mTLS ke Backup — cuma dipanggil kalau ROLE=primary & REPLICATE_TO diset."""
    with open(os.path.join(CERT_DIR, f"storage-{ROLE}-key.pem"), "rb") as f:
        private_key = f.read()
    with open(os.path.join(CERT_DIR, f"storage-{ROLE}-cert.pem"), "rb") as f:
        cert_chain = f.read()
    with open(os.path.join(CERT_DIR, "ca-cert.pem"), "rb") as f:
        ca_cert = f.read()

    creds = grpc.ssl_channel_credentials(
        root_certificates=ca_cert,
        private_key=private_key,
        certificate_chain=cert_chain,
    )
    channel = grpc.secure_channel(REPLICATE_TO, creds)
    return storage_pb2_grpc.StorageStub(channel)


def replicate_upload(request):
    """Forward Upload ke Backup. Best-effort — kalau Backup mati, Primary tetap sukses,
    cuma dicatat sebagai warning di audit log (bukan hard-fail)."""
    if not REPLICATE_TO:
        return
    try:
        stub = get_backup_stub()
        reply = stub.Upload(request, timeout=5)
        if reply.success:
            write_audit("replicate_upload", request.filename, "ALLOW", "berhasil sync ke backup")
        else:
            write_audit("replicate_upload", request.filename, "WARN", f"backup menolak: {reply.message}")
    except grpc.RpcError as e:
        write_audit("replicate_upload", request.filename, "WARN", f"backup unreachable: {e.code()}")


def replicate_delete(request):
    if not REPLICATE_TO:
        return
    try:
        stub = get_backup_stub()
        reply = stub.Delete(request, timeout=5)
        write_audit("replicate_delete", request.filename,
                     "ALLOW" if reply.success else "WARN", reply.message)
    except grpc.RpcError as e:
        write_audit("replicate_delete", request.filename, "WARN", f"backup unreachable: {e.code()}")


class StorageServicer(storage_pb2_grpc.StorageServicer):

    def Upload(self, request, context):
        path = os.path.join(FILES_DIR, request.filename)
        with open(path, "wb") as f:
            f.write(request.content)

        checksum = sha256_bytes(request.content)
        meta = load_meta()
        meta[request.filename] = {
            "label": request.label or "Public",
            "checksum": checksum,
            "owner": request.username,
        }
        save_meta(meta)
        write_audit("upload", request.filename, "ALLOW", f"by={request.username} sha256={checksum[:16]}...")

        if ROLE == "primary":
            replicate_upload(request)

        return storage_pb2.UploadReply(success=True, message="File tersimpan", checksum=checksum)

    def Download(self, request, context):
        meta = load_meta()
        if request.filename not in meta:
            write_audit("download", request.filename, "DENY", "tidak ditemukan")
            return storage_pb2.DownloadReply(success=False, message="File tidak ditemukan")

        path = os.path.join(FILES_DIR, request.filename)
        if not os.path.exists(path):
            write_audit("download", request.filename, "DENY", "hilang di disk")
            return storage_pb2.DownloadReply(success=False, message="File hilang di disk")

        with open(path, "rb") as f:
            content = f.read()

        actual = sha256_bytes(content)
        expected = meta[request.filename]["checksum"]

        if actual != expected:
            write_audit("download", request.filename, "DENY", "checksum mismatch — integritas rusak")
            return storage_pb2.DownloadReply(success=False, message="Integritas file rusak: SHA-256 tidak cocok")

        write_audit("download", request.filename, "ALLOW", f"by={request.username}")
        return storage_pb2.DownloadReply(success=True, message="OK", content=content, checksum=actual)

    def List(self, request, context):
        meta = load_meta()
        files = [
            storage_pb2.FileInfo(filename=name, label=info["label"],
                                  checksum=info["checksum"], owner=info["owner"])
            for name, info in meta.items()
        ]
        write_audit("list", "-", "ALLOW", f"by={request.username} count={len(files)}")
        return storage_pb2.ListReply(files=files)

    def Delete(self, request, context):
        meta = load_meta()
        if request.filename not in meta:
            write_audit("delete", request.filename, "DENY", "tidak ditemukan")
            return storage_pb2.DeleteReply(success=False, message="File tidak ditemukan")

        path = os.path.join(FILES_DIR, request.filename)
        if os.path.exists(path):
            os.remove(path)
        del meta[request.filename]
        save_meta(meta)
        write_audit("delete", request.filename, "ALLOW", f"by={request.username}")

        if ROLE == "primary":
            replicate_delete(request)

        return storage_pb2.DeleteReply(success=True, message="File dihapus")


def load_server_credentials():
    with open(os.path.join(CERT_DIR, f"storage-{ROLE}-key.pem"), "rb") as f:
        private_key = f.read()
    with open(os.path.join(CERT_DIR, f"storage-{ROLE}-cert.pem"), "rb") as f:
        cert_chain = f.read()
    with open(os.path.join(CERT_DIR, "ca-cert.pem"), "rb") as f:
        ca_cert = f.read()

    return grpc.ssl_server_credentials(
        [(private_key, cert_chain)],
        root_certificates=ca_cert,
        require_client_auth=True,   # ini yang bikin "mutual" — client (Gateway) wajib kirim cert juga
    )


def serve():
    ensure_dirs()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    storage_pb2_grpc.add_StorageServicer_to_server(StorageServicer(), server)

    creds = load_server_credentials()
    server.add_secure_port(f"[::]:{PORT}", creds)
    server.start()
    log.info(f"Storage {ROLE} running on port {PORT} (mTLS aktif)")
    if ROLE == "primary" and REPLICATE_TO:
        log.info(f"Replikasi aktif ke {REPLICATE_TO}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
