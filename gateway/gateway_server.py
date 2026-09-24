import grpc
import os
import json
import hashlib
from concurrent import futures

import storage_pb2
import storage_pb2_grpc
import policy

DATA_DIR = os.environ.get("DATA_DIR", "./data")
META_FILE = os.path.join(DATA_DIR, "metadata.json")


def ensure_dirs():
    os.makedirs(os.path.join(DATA_DIR, "files"), exist_ok=True)
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


class GatewayServicer(storage_pb2_grpc.StorageServicer):

    def Upload(self, request, context):
        allowed, username, reason = policy.authorize(
            request.token, "upload", request.filename, request.label
        )
        if not allowed:
            return storage_pb2.UploadReply(success=False, message=f"Ditolak: {reason}")

        path = os.path.join(DATA_DIR, "files", request.filename)
        with open(path, "wb") as f:
            f.write(request.content)

        checksum = sha256_bytes(request.content)

        meta = load_meta()
        meta[request.filename] = {
            "label": request.label or "Public",
            "checksum": checksum,
            "owner": username,
        }
        save_meta(meta)

        print(f"[UPLOAD] {request.filename} by {username} label={request.label} sha256={checksum[:16]}...")
        return storage_pb2.UploadReply(
            success=True,
            message="File tersimpan",
            checksum=checksum,
        )

    def Download(self, request, context):
        meta = load_meta()
        file_label = meta.get(request.filename, {}).get("label")

        allowed, username, reason = policy.authorize(
            request.token, "download", request.filename, file_label
        )
        if not allowed:
            return storage_pb2.DownloadReply(success=False, message=f"Ditolak: {reason}")

        if request.filename not in meta:
            return storage_pb2.DownloadReply(success=False, message="File tidak ditemukan")

        path = os.path.join(DATA_DIR, "files", request.filename)
        if not os.path.exists(path):
            return storage_pb2.DownloadReply(success=False, message="File hilang di disk")

        with open(path, "rb") as f:
            content = f.read()

        actual = sha256_bytes(content)
        expected = meta[request.filename]["checksum"]

        if actual != expected:
            print(f"[INTEGRITY FAIL] {request.filename}")
            return storage_pb2.DownloadReply(
                success=False,
                message="Integritas file rusak: SHA-256 tidak cocok",
            )

        print(f"[DOWNLOAD] {request.filename} by {username}")
        return storage_pb2.DownloadReply(
            success=True,
            message="OK",
            content=content,
            checksum=actual,
        )

    def List(self, request, context):
        allowed, username, reason = policy.authorize(request.token, "list")
        if not allowed:
            return storage_pb2.ListReply()

        meta = load_meta()
        files = [
            storage_pb2.FileInfo(
                filename=name,
                label=info["label"],
                checksum=info["checksum"],
                owner=info["owner"],
            )
            for name, info in meta.items()
        ]
        return storage_pb2.ListReply(files=files)

    def Delete(self, request, context):
        meta = load_meta()
        file_label = meta.get(request.filename, {}).get("label")

        allowed, username, reason = policy.authorize(
            request.token, "delete", request.filename, file_label
        )
        if not allowed:
            return storage_pb2.DeleteReply(success=False, message=f"Ditolak: {reason}")

        if request.filename not in meta:
            return storage_pb2.DeleteReply(success=False, message="File tidak ditemukan")

        path = os.path.join(DATA_DIR, "files", request.filename)
        if os.path.exists(path):
            os.remove(path)

        del meta[request.filename]
        save_meta(meta)

        print(f"[DELETE] {request.filename} by {username}")
        return storage_pb2.DeleteReply(success=True, message="File dihapus")


def serve():
    ensure_dirs()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    storage_pb2_grpc.add_StorageServicer_to_server(GatewayServicer(), server)
    server.add_insecure_port("[::]:50052")
    server.start()
    print("Gateway server running on port 50052")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
