import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from test_payments import config
from services.session_audit import _clean
from telethon.tl.functions.account import ResetAuthorizationRequest

class Client:
    def __init__(self,before,after):
        self.connect=AsyncMock();self.get_me=AsyncMock(return_value=NS(id=42));self.states=iter([before,after]);self.resets=[]
    async def __call__(self,request):
        if isinstance(request,ResetAuthorizationRequest): self.resets.append(request.hash);return True
        return NS(authorizations=next(self.states))

class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_other_sessions_are_revoked_and_result_verified(self):
        current=NS(current=True,hash=11);other=NS(current=False,hash=22)
        client=Client([current,other],[current])
        result=await _clean(client,42)
        self.assertEqual(client.resets,[22]);self.assertEqual(result['status'],'cleaned')

    async def test_remaining_sessions_report_failure(self):
        states=[NS(current=True,hash=11),NS(current=False,hash=22)]
        client=Client(states,states)
        self.assertEqual((await _clean(client,42))['status'],'failed')

    async def test_missing_current_session_or_wrong_identity_never_revokes(self):
        for expected,states in [(99,[NS(current=True,hash=11)]),(42,[NS(current=False,hash=22)])]:
            client=Client(states,states)
            self.assertEqual((await _clean(client,expected))['status'],'failed')
            self.assertEqual(client.resets,[])


class ExportTests(unittest.TestCase):
    def test_sqlite_export_preserves_auth_key_and_dc(self):
        import tempfile
        from pathlib import Path
        from telethon.sessions import StringSession, SQLiteSession
        from telethon.crypto import AuthKey
        from services.session_audit import session_file_bytes
        source=StringSession();source.set_dc(2,'149.154.167.51',443);source.auth_key=AuthKey(bytes(range(256)))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.session';path.write_bytes(session_file_bytes(source.save()))
            session=SQLiteSession(str(path))
            try:
                self.assertEqual(session.auth_key.key,source.auth_key.key)
                self.assertEqual(session.dc_id,2)
            finally:
                session.close()
