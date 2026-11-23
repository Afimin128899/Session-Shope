"""Durable copies of a new authorization, independent of temporary work files."""
import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SavedSession:
    session: Path
    metadata: Path
    archive: Path


def persist_new_session(root, owner, task_id, phase, source, metadata):
    # owner/task_id originate inside the bot. Still reject path components here.
    parts = (str(owner), str(task_id), str(phase))
    if any(not part or part in {'.', '..'} or '/' in part or '\\' in part for part in parts):
        raise ValueError('Invalid result path')
    directory = Path(root).joinpath('new_sessions', *parts)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    session = directory / 'account.session'
    meta = directory / 'account.json'
    archive = directory / 'account.zip'
    pending = []
    try:
        for target, writer in (
            (session, lambda out: _copy(source, out)),
            (meta, lambda out: out.write(json.dumps({**metadata, 'session_file': 'account.session'}, ensure_ascii=False).encode('utf-8'))),
        ):
            temp = target.with_suffix(target.suffix + '.tmp')
            pending.append(temp)
            with open(temp, 'wb') as out:
                os.chmod(temp, 0o600)
                writer(out)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, target)
        temp = archive.with_suffix('.zip.tmp')
        pending.append(temp)
        with open(temp, 'w+b') as out:
            os.chmod(temp, 0o600)
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as bundle:
                bundle.write(session, 'account.session')
                bundle.write(meta, 'account.json')
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, archive)
        # Sync every directory up to the Volume root, including newly created parents.
        current = directory
        root = Path(root)
        while True:
            descriptor = os.open(current, os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if current == root or current.parent == current:
                break
            current = current.parent
        return SavedSession(session, meta, archive)
    finally:
        for temp in pending:
            temp.unlink(missing_ok=True)


def _copy(source, out):
    with open(source, 'rb') as file:
        shutil.copyfileobj(file, out)
