# pimux-managed: send a masked terminal response directly to system OpenSSH.
import os
import select
import stat
import sys
import termios
import time


def main():
    path = os.environ['PIMUX_AUTH_TTY']
    if not path.startswith('/dev/'): raise ValueError('No authentication terminal')
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
    saved = None
    try:
        if not os.isatty(fd) or not stat.S_ISCHR(os.fstat(fd).st_mode): raise ValueError('Invalid terminal')
        saved = termios.tcgetattr(fd)
        hidden = termios.tcgetattr(fd); hidden[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, hidden)
        termios.tcflush(fd, termios.TCIFLUSH)
        prompt = ''.join(char if char.isprintable() else '?' for char in sys.argv[1])[:500]
        os.write(fd, ('\n' + prompt + ' ').encode())
        end = time.monotonic() + 90
        secret = bytearray()
        while time.monotonic() < end:
            if not select.select([fd], [], [], .2)[0]: continue
            part = os.read(fd, 4096)
            if not part: raise ValueError('Authentication cancelled')
            secret.extend(part)
            if len(secret) > 4096: raise ValueError('Authentication response limit')
            if b'\n' in secret: break
        else: raise TimeoutError('Authentication response timeout')
        os.write(1, bytes(secret).split(b'\n', 1)[0] + b'\n')
        secret.clear()
    finally:
        if saved is not None:
            termios.tcsetattr(fd, termios.TCSANOW, saved)
            termios.tcflush(fd, termios.TCIFLUSH)
        os.write(fd, b'\n'); os.close(fd)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, TimeoutError): raise SystemExit(1) from None
