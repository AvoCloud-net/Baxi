"""File transport to the Baxi server: SFTP, FTPS, plain FTP (opt-in) or a local folder.

All paths are relative to the server's data/safetext directory (`remote_dir`).
"""
from __future__ import annotations

import ftplib
import os
import posixpath
import shutil
from pathlib import Path


class Remote:
    def get(self, name: str, local: Path) -> bool: ...
    def put(self, local: Path, name: str) -> None: ...
    def size(self, name: str) -> int | None: ...
    def mkdir(self, name: str) -> None: ...
    def rename(self, old: str, new: str) -> None: ...
    def listdir(self, name: str) -> list[str]: ...
    def rmtree(self, name: str) -> None: ...
    def close(self) -> None: ...

    def put_text(self, text: str, name: str, tmp_dir: Path) -> None:
        """Write *name* atomically: upload to name.tmp, then rename over it."""
        local = tmp_dir / (posixpath.basename(name) + ".upload")
        local.write_text(text, encoding="utf-8")
        self.put(local, name + ".tmp")
        try:
            self.rename(name + ".tmp", name)
        except Exception:
            # FTP servers refuse to rename onto an existing file
            try:
                self._delete(name)
            except Exception:
                pass
            self.rename(name + ".tmp", name)

    def _delete(self, name: str) -> None: ...


class LocalRemote(Remote):
    """A local folder that mirrors the server's data/safetext (tests, mounted shares)."""

    def __init__(self, root: str):
        self.root = Path(root)

    def _p(self, name: str) -> Path:
        return self.root / name

    def get(self, name, local):
        if not self._p(name).exists():
            return False
        local.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._p(name), local)
        return True

    def put(self, local, name):
        self._p(name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, self._p(name))

    def size(self, name):
        p = self._p(name)
        return p.stat().st_size if p.exists() else None

    def mkdir(self, name):
        self._p(name).mkdir(parents=True, exist_ok=True)

    def rename(self, old, new):
        os.replace(self._p(old), self._p(new))

    def listdir(self, name):
        p = self._p(name)
        return sorted(x.name for x in p.iterdir()) if p.is_dir() else []

    def rmtree(self, name):
        shutil.rmtree(self._p(name), ignore_errors=True)

    def _delete(self, name):
        self._p(name).unlink(missing_ok=True)

    def close(self):
        pass


class SFTPRemote(Remote):
    def __init__(self, host, port, user, password, key_file, remote_dir):
        import paramiko
        self.base = remote_dir.rstrip("/")
        self.transport = paramiko.Transport((host, int(port or 22)))
        pkey = paramiko.RSAKey.from_private_key_file(key_file) if key_file else None
        self.transport.connect(username=user, password=password or None, pkey=pkey)
        self.sftp = paramiko.SFTPClient.from_transport(self.transport)

    def _p(self, name):
        return posixpath.join(self.base, name)

    def get(self, name, local):
        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.sftp.get(self._p(name), str(local))
            return True
        except FileNotFoundError:
            return False

    def put(self, local, name):
        self.sftp.put(str(local), self._p(name))

    def size(self, name):
        try:
            return self.sftp.stat(self._p(name)).st_size
        except FileNotFoundError:
            return None

    def mkdir(self, name):
        path = ""
        for part in name.split("/"):
            path = posixpath.join(path, part) if path else part
            try:
                self.sftp.mkdir(self._p(path))
            except OSError:
                pass

    def rename(self, old, new):
        try:
            self.sftp.posix_rename(self._p(old), self._p(new))
        except (OSError, AttributeError):
            self.sftp.rename(self._p(old), self._p(new))

    def listdir(self, name):
        try:
            return sorted(self.sftp.listdir(self._p(name)))
        except FileNotFoundError:
            return []

    def rmtree(self, name):
        import stat
        for entry in self.sftp.listdir_attr(self._p(name)):
            child = posixpath.join(name, entry.filename)
            if stat.S_ISDIR(entry.st_mode):
                self.rmtree(child)
            else:
                self.sftp.remove(self._p(child))
        self.sftp.rmdir(self._p(name))

    def _delete(self, name):
        self.sftp.remove(self._p(name))

    def close(self):
        self.sftp.close()
        self.transport.close()


class FTPRemote(Remote):
    def __init__(self, host, port, user, password, remote_dir, tls: bool):
        self.base = remote_dir.rstrip("/")
        self.ftp = ftplib.FTP_TLS() if tls else ftplib.FTP()
        self.ftp.connect(host, int(port or 21), timeout=60)
        self.ftp.login(user, password)
        if tls:
            self.ftp.prot_p()   # encrypt the data channel too, not only the login

    def _p(self, name):
        return posixpath.join(self.base, name)

    def get(self, name, local):
        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            with local.open("wb") as fh:
                self.ftp.retrbinary(f"RETR {self._p(name)}", fh.write)
            return True
        except ftplib.error_perm:
            local.unlink(missing_ok=True)
            return False

    def put(self, local, name):
        with local.open("rb") as fh:
            self.ftp.storbinary(f"STOR {self._p(name)}", fh)

    def size(self, name):
        try:
            self.ftp.voidcmd("TYPE I")
            return self.ftp.size(self._p(name))
        except ftplib.error_perm:
            return None

    def mkdir(self, name):
        path = ""
        for part in name.split("/"):
            path = posixpath.join(path, part) if path else part
            try:
                self.ftp.mkd(self._p(path))
            except ftplib.error_perm:
                pass

    def rename(self, old, new):
        self.ftp.rename(self._p(old), self._p(new))

    def listdir(self, name):
        try:
            return sorted(posixpath.basename(x) for x in self.ftp.nlst(self._p(name)))
        except ftplib.error_perm:
            return []

    def rmtree(self, name):
        for child in self.listdir(name):
            path = posixpath.join(name, child)
            try:
                self.ftp.delete(self._p(path))
            except ftplib.error_perm:
                self.rmtree(path)
        self.ftp.rmd(self._p(name))

    def _delete(self, name):
        self.ftp.delete(self._p(name))

    def close(self):
        try:
            self.ftp.quit()
        except Exception:
            self.ftp.close()


def connect(cfg: dict, local_dir: str | None = None) -> Remote:
    if local_dir:
        return LocalRemote(local_dir)
    server = cfg["server"]
    protocol = server.get("protocol", "sftp").lower()
    password = os.environ.get("BAXI_TRAINER_PASSWORD") or server.get("password", "")
    if not password and not server.get("key_file"):
        import getpass
        password = getpass.getpass(f"Passwort für {server.get('user')}@{server['host']}: ")
    remote_dir = server["remote_dir"]
    if protocol == "sftp":
        return SFTPRemote(server["host"], server.get("port"), server["user"], password,
                          server.get("key_file"), remote_dir)
    if protocol == "ftps":
        return FTPRemote(server["host"], server.get("port"), server["user"], password, remote_dir, tls=True)
    if protocol == "ftp":
        if not server.get("allow_insecure_ftp"):
            raise SystemExit(
                "Unverschlüsseltes FTP überträgt Passwort und Chat-Nachrichten im Klartext.\n"
                "Nutze protocol = \"sftp\" oder \"ftps\" - oder setze allow_insecure_ftp = true, "
                "wenn du das wirklich willst."
            )
        return FTPRemote(server["host"], server.get("port"), server["user"], password, remote_dir, tls=False)
    raise SystemExit(f"Unbekanntes protocol: {protocol} (sftp | ftps | ftp)")
