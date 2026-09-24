import json
import os
from datetime import datetime, timezone

USERS_FILE = os.path.join(os.path.dirname(__file__), "..", "users.json")
AUDIT_LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "audit_log.jsonl")

# Urutan level, dari rendah ke tinggi
LEVELS = {"Public": 0, "Confidential": 1, "Secret": 2}

# RBAC: aksi apa yang boleh dilakukan tiap role
ROLE_PERMISSIONS = {
    "admin": {"upload", "download", "list", "delete"},
    "staff": {"upload", "download", "list"},
    "guest": {"download", "list"},
}


def load_users():
    with open(USERS_FILE, "r") as f:
        return json.load(f)


def find_user_by_token(token):
    users = load_users()
    for username, info in users.items():
        if info["token"] == token:
            return username, info
    return None, None


def write_audit_log(username, action, filename, decision, reason=""):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user": username,
        "action": action,
        "filename": filename,
        "decision": decision,
        "reason": reason,
    }
    with open(AUDIT_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[AUDIT] {decision} | user={username} action={action} file={filename} reason={reason}")


def check_authentication(token):
    """Cek apakah token valid. Return (username, user_info) atau (None, None)."""
    username, info = find_user_by_token(token)
    return username, info


def check_rbac(role, action):
    """Cek apakah role ini boleh melakukan action tertentu."""
    allowed_actions = ROLE_PERMISSIONS.get(role, set())
    return action in allowed_actions


def check_bell_lapadula(user_clearance, file_label, action):
    """
    Aturan:
    - Baca (download/list): user_clearance harus >= file_label (no read-up)
    - Tulis (upload): user_clearance harus <= file_label (no write-down)
    """
    user_level = LEVELS.get(user_clearance, 0)
    file_level = LEVELS.get(file_label, 0)

    if action in ("download", "list"):
        return user_level >= file_level
    elif action == "upload":
        return user_level <= file_level
    return True


def authorize(token, action, filename="-", file_label=None):
    """
    Fungsi utama: cek autentikasi, RBAC, dan Bell-LaPadula sekaligus.
    Return (allowed: bool, username: str, reason: str)
    """
    username, info = check_authentication(token)
    if username is None:
        write_audit_log("unknown", action, filename, "DENY", "Token tidak valid")
        return False, None, "Token tidak valid"

    if not check_rbac(info["role"], action):
        write_audit_log(username, action, filename, "DENY", f"Role '{info['role']}' tidak diizinkan melakukan '{action}'")
        return False, username, f"Role '{info['role']}' tidak diizinkan melakukan '{action}'"

    if file_label is not None:
        if not check_bell_lapadula(info["clearance"], file_label, action):
            write_audit_log(username, action, filename, "DENY", f"Clearance '{info['clearance']}' tidak boleh akses label '{file_label}'")
            return False, username, f"Clearance '{info['clearance']}' tidak boleh akses label '{file_label}'"

    write_audit_log(username, action, filename, "ALLOW")
    return True, username, "OK"
