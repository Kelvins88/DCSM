import grpc
import sys

import storage_pb2
import storage_pb2_grpc

TARGET = "localhost:50052"  # arahkan ke GATEWAY, bukan storage langsung


def get_stub():
    channel = grpc.insecure_channel(TARGET)
    return storage_pb2_grpc.StorageStub(channel)


def do_upload(username, filepath, label):
    with open(filepath, "rb") as f:
        content = f.read()

    filename = filepath.split("/")[-1].split("\\")[-1]
    stub = get_stub()
    reply = stub.Upload(storage_pb2.UploadRequest(
        username=username,
        filename=filename,
        content=content,
        label=label,
    ))
    print("Success:", reply.success)
    print("Message:", reply.message)
    print("Checksum:", reply.checksum)


def do_download(username, filename):
    stub = get_stub()
    reply = stub.Download(storage_pb2.DownloadRequest(
        username=username,
        filename=filename,
    ))
    print("Success:", reply.success)
    print("Message:", reply.message)
    if reply.success:
        out = "downloaded_" + filename
        with open(out, "wb") as f:
            f.write(reply.content)
        print("Tersimpan sebagai:", out)
        print("Checksum:", reply.checksum)


def do_list(username):
    stub = get_stub()
    reply = stub.List(storage_pb2.ListRequest(username=username))
    if not reply.files:
        print("(kosong)")
    for f in reply.files:
        print(f"{f.filename:25} | {f.label:12} | owner={f.owner} | {f.checksum[:16]}...")


def do_delete(username, filename):
    stub = get_stub()
    reply = stub.Delete(storage_pb2.DeleteRequest(
        username=username,
        filename=filename,
    ))
    print("Success:", reply.success)
    print("Message:", reply.message)


def usage():
    print("Cara pakai:")
    print("  python client.py upload   <user> <filepath> <label>")
    print("  python client.py download <user> <filename>")
    print("  python client.py list     <user>")
    print("  python client.py delete   <user> <filename>")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "upload" and len(sys.argv) == 5:
        do_upload(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "download" and len(sys.argv) == 4:
        do_download(sys.argv[2], sys.argv[3])
    elif cmd == "list" and len(sys.argv) == 3:
        do_list(sys.argv[2])
    elif cmd == "delete" and len(sys.argv) == 4:
        do_delete(sys.argv[2], sys.argv[3])
    else:
        usage()
