import os
import grpc

import storage_pb2
import storage_pb2_grpc

STORAGE_PRIMARY_TARGET = os.environ.get("STORAGE_PRIMARY_TARGET", "10.16.54.46:50053")
STORAGE_BACKUP_TARGET = os.environ.get("STORAGE_BACKUP_TARGET", "10.16.54.46:50054")


def _load_gateway_client_credentials():
    base = os.path.join(os.path.dirname(__file__), "..", "certs")

    with open(os.path.join(base, "gateway-key.pem"), "rb") as f:
        private_key = f.read()
    with open(os.path.join(base, "gateway-cert.pem"), "rb") as f:
        certificate_chain = f.read()
    with open(os.path.join(base, "ca-cert.pem"), "rb") as f:
        root_cert = f.read()

    return grpc.ssl_channel_credentials(
        root_certificates=root_cert,
        private_key=private_key,
        certificate_chain=certificate_chain,
    )


def _get_stub(target):
    credentials = _load_gateway_client_credentials()
    channel = grpc.secure_channel(target, credentials)
    return storage_pb2_grpc.StorageStub(channel)


def _try_call(target, method_name, request, timeout=3):
    try:
        stub = _get_stub(target)
        method = getattr(stub, method_name)
        return method(request, timeout=timeout)
    except grpc.RpcError as e:
        print(f"[STORAGE UNREACHABLE] target={target} method={method_name} error={e.code()}")
        return None


def upload_to_storage(token, username, filename, content, label):
    request = storage_pb2.UploadRequest(
        token=token, username=username, filename=filename,
        content=content, label=label,
    )
    reply = _try_call(STORAGE_PRIMARY_TARGET, "Upload", request)
    if reply is not None:
        return reply
    print("[FAILOVER] Primary down saat upload, mencoba Backup")
    return _try_call(STORAGE_BACKUP_TARGET, "Upload", request)


def download_from_storage(token, username, filename):
    request = storage_pb2.DownloadRequest(token=token, username=username, filename=filename)
    reply = _try_call(STORAGE_PRIMARY_TARGET, "Download", request)
    if reply is not None:
        return reply
    print("[FAILOVER] Primary down saat download, mengarahkan ke Backup")
    return _try_call(STORAGE_BACKUP_TARGET, "Download", request)


def list_from_storage(token, username):
    request = storage_pb2.ListRequest(token=token, username=username)
    reply = _try_call(STORAGE_PRIMARY_TARGET, "List", request)
    if reply is not None:
        return reply
    print("[FAILOVER] Primary down saat list, mengarahkan ke Backup")
    return _try_call(STORAGE_BACKUP_TARGET, "List", request)


def delete_from_storage(token, username, filename):
    request = storage_pb2.DeleteRequest(token=token, username=username, filename=filename)
    reply = _try_call(STORAGE_PRIMARY_TARGET, "Delete", request)
    if reply is not None:
        return reply
    print("[FAILOVER] Primary down saat delete, mengarahkan ke Backup")
    return _try_call(STORAGE_BACKUP_TARGET, "Delete", request)
