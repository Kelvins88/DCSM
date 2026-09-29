import grpc
import os
from concurrent import futures

import storage_pb2
import storage_pb2_grpc
import policy
import storage_client


class GatewayServicer(storage_pb2_grpc.StorageServicer):

    def Upload(self, request, context):
        allowed, username, reason = policy.authorize(
            request.token, "upload", request.filename, request.label
        )
        if not allowed:
            return storage_pb2.UploadReply(success=False, message=f"Ditolak: {reason}")

        reply = storage_client.upload_to_storage(
            request.token, username, request.filename, request.content, request.label
        )
        if reply is None:
            return storage_pb2.UploadReply(success=False, message="Storage Node tidak dapat dihubungi (Primary & Backup down)")

        print(f"[UPLOAD via Gateway] {request.filename} by {username} -> Storage: success={reply.success}")
        return reply

    def Download(self, request, context):
        list_reply = storage_client.list_from_storage(request.token, request.username)
        file_label = None
        if list_reply is not None:
            for f in list_reply.files:
                if f.filename == request.filename:
                    file_label = f.label
                    break

        allowed, username, reason = policy.authorize(
            request.token, "download", request.filename, file_label
        )
        if not allowed:
            return storage_pb2.DownloadReply(success=False, message=f"Ditolak: {reason}")

        reply = storage_client.download_from_storage(request.token, username, request.filename)
        if reply is None:
            return storage_pb2.DownloadReply(success=False, message="Storage Node tidak dapat dihubungi (Primary & Backup down)")

        print(f"[DOWNLOAD via Gateway] {request.filename} by {username}: success={reply.success}")
        return reply

    def List(self, request, context):
        allowed, username, reason = policy.authorize(request.token, "list")
        if not allowed:
            return storage_pb2.ListReply()

        reply = storage_client.list_from_storage(request.token, username)
        if reply is None:
            return storage_pb2.ListReply()
        return reply

    def Delete(self, request, context):
        list_reply = storage_client.list_from_storage(request.token, request.username)
        file_label = None
        if list_reply is not None:
            for f in list_reply.files:
                if f.filename == request.filename:
                    file_label = f.label
                    break

        allowed, username, reason = policy.authorize(
            request.token, "delete", request.filename, file_label
        )
        if not allowed:
            return storage_pb2.DeleteReply(success=False, message=f"Ditolak: {reason}")

        reply = storage_client.delete_from_storage(request.token, username, request.filename)
        if reply is None:
            return storage_pb2.DeleteReply(success=False, message="Storage Node tidak dapat dihubungi (Primary & Backup down)")

        print(f"[DELETE via Gateway] {request.filename} by {username}: success={reply.success}")
        return reply


def load_credentials():
    base = os.path.join(os.path.dirname(__file__), "..", "certs")

    with open(os.path.join(base, "gateway-key.pem"), "rb") as f:
        private_key = f.read()
    with open(os.path.join(base, "gateway-cert.pem"), "rb") as f:
        certificate_chain = f.read()
    with open(os.path.join(base, "ca-cert.pem"), "rb") as f:
        root_cert = f.read()

    return grpc.ssl_server_credentials(
        [(private_key, certificate_chain)],
        root_certificates=root_cert,
        require_client_auth=True,
    )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    storage_pb2_grpc.add_StorageServicer_to_server(GatewayServicer(), server)

    credentials = load_credentials()
    server.add_secure_port("[::]:50052", credentials)

    server.start()
    print("Gateway server running SECURELY (mTLS) on port 50052")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
