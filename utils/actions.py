"""Reject overlapping UI actions; financial correctness remains in DB transactions."""
from contextlib import asynccontextmanager

_running = set()


@asynccontextmanager
async def single_action(user_id, action):
    key = (user_id, action)
    if key in _running:
        yield False
        return
    _running.add(key)
    try:
        yield True
    finally:
        _running.discard(key)
