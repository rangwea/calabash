"""Keep a Windows control read off the CRT's standard-input descriptor lock."""
import os
import sys
from contextlib import contextmanager


@contextmanager
def control_reader(stream):
    # Native libraries can query standard descriptors during DLL initialization.
    # A blocking CRT read on fd 0 can then deadlock that initialization on Windows
    # (numpy/numpy#24290). A private, non-inheritable descriptor keeps lazy imports
    # possible without eagerly loading office libraries or changing the protocol.
    if sys.platform != 'win32':
        yield stream
        return
    descriptor = os.dup(stream.fileno())
    try:
        reader = os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise
    with reader:
        yield reader
