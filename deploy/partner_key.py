"""Append a stable private encryption key; never rotate or print it."""
import argparse
import os
from pathlib import Path
from cryptography.fernet import Fernet


def ensure(path):
    path=Path(path)
    if not path.is_file():raise ValueError('Сначала подготовьте .env основного бота.')
    text=path.read_text()
    found=[line.partition('=')[2].strip().strip('"\'') for line in text.splitlines() if line.startswith('PARTNER_BOT_KEY=')]
    os.chmod(path,0o600)
    if found:
        Fernet(found[-1].encode('ascii'));return False
    # O_APPEND and a single write avoid truncation.
    fd=os.open(path,os.O_WRONLY|os.O_APPEND)
    try:os.write(fd,('\nPARTNER_BOT_KEY='+Fernet.generate_key().decode()+'\n').encode());os.fsync(fd)
    finally:os.close(fd)
    return True


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--env',required=True);args=parser.parse_args()
    ensure(args.env);print('Ключ партнёрских ботов готов; значение не выводится.')
