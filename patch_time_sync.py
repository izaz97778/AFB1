import time
from pyrogram.session.session import Session


def patch_pyrogram_time_sync():
    original_generate_msg_id = Session._generate_msg_id

    def patched_generate_msg_id(self):
        # Ignore Pyrogram's time calculation and use real time
        now = time.time()
        seconds = int(now)
        nanoseconds = int((now - seconds) * 1e9)
        return ((seconds << 32) | (nanoseconds << 2)) & 0x7FFFFFFFFFFFFFFF

    Session._generate_msg_id = patched_generate_msg_id
