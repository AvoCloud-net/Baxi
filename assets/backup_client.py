"""Minimaler Client für den Backup Manager – nur Standardbibliothek, einfach in andere Projekte kopierbar.

    from backup_client import BackupClient
    client = BackupClient("https://backup.example.com", "prj_xxxxxxxxxx", "bks_...")
    client.upload("dump.sql.gz", note="nightly")

CLI: BACKUP_URL / BACKUP_PROJECT / BACKUP_KEY setzen, dann `python backup_client.py dump.sql.gz`.
"""
import hashlib
import http.client
import json
import os
import sys
import urllib.parse
from pathlib import Path


class BackupError(RuntimeError):
    pass


class BackupClient:
    def __init__(self, url, project_id, key, timeout=3600):
        self.url, self.project_id, self.key, self.timeout = url.rstrip("/"), project_id, key, timeout

    def _headers(self, extra=None):
        h = {"X-Project-Id": self.project_id, "Authorization": f"Bearer {self.key}"}
        h.update(extra or {})
        return h

    def _request(self, method, path, body=None, headers=None):
        u = urllib.parse.urlsplit(self.url + path)
        conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(u.netloc, timeout=self.timeout)
        try:
            conn.request(method, u.path + (f"?{u.query}" if u.query else ""), body=body,
                         headers=self._headers(headers))
            resp = conn.getresponse()
            data = resp.read()
        finally:
            conn.close()
        payload = json.loads(data) if data and resp.getheader("Content-Type", "").startswith("application/json") else data
        if resp.status >= 400:
            raise BackupError(f"HTTP {resp.status}: {payload.get('error') if isinstance(payload, dict) else payload}")
        return payload

    def ping(self):
        return self._request("GET", "/api/v1/ping")

    def upload(self, path, name=None, note=""):
        """Lädt eine Datei gestreamt hoch und gibt die Metadaten des Servers zurück."""
        path = Path(path)
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                sha.update(chunk)
        headers = {
            "X-Checksum-SHA256": sha.hexdigest(),
            "Content-Length": str(path.stat().st_size),
            "Content-Type": "application/octet-stream",
        }
        if note:
            headers["X-Backup-Note"] = note
        with open(path, "rb") as f:
            return self._request("PUT", "/api/v1/backups/" + urllib.parse.quote(name or path.name), f, headers)

    def list(self):
        return self._request("GET", "/api/v1/backups")["backups"]

    def download(self, backup_id, dest):
        data = self._request("GET", f"/api/v1/backups/{int(backup_id)}/download")
        Path(dest).write_bytes(data)

    def delete(self, backup_id):
        return self._request("DELETE", f"/api/v1/backups/{int(backup_id)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: backup_client.py <datei> [notiz]")
    c = BackupClient(os.environ["BACKUP_URL"], os.environ["BACKUP_PROJECT"], os.environ["BACKUP_KEY"])
    print(json.dumps(c.upload(sys.argv[1], note=" ".join(sys.argv[2:])), indent=2))
