# Repository Guidelines

## Project scope

This repository implements a small Linux TUN-to-UDP tunnel. Keep changes focused
and preserve the deliberately simple module boundaries:

- `main.py` parses arguments, configures the host, and runs the selector loop.
- `tun.py` owns the Linux TUN file descriptor and ioctl setup.
- `udp.py` owns framing, authentication checks, padding, and UDP transport.
- `crypto.py` owns the packet cipher implementation.
- `logger.py` owns traffic reporting.
- `client*.sh` and `server*.sh` modify routing, forwarding, and NAT state.

The code targets Python 3.5 or newer and uses only the standard library. Avoid
syntax or APIs introduced after Python 3.5 unless the supported version is
intentionally raised and documented. Keep the shell scripts POSIX `sh`
compatible.

## Protocol changes

Treat the UDP framing and cipher as a wire protocol. Client and server must
remain compatible, and encryption and decryption state transitions must stay
symmetric. When changing packet layout, padding, integer encoding, or
authentication behavior, update both directions and document the compatibility
impact in `README.md`.

Do not describe the custom cipher or authentication prefix as production-grade
cryptography. New security-sensitive code should use established primitives
rather than extending the custom design without a clear compatibility reason.

## Network safety

Do not run `main.py`, `client.sh`, `client-cleanup.sh`, `server.sh`, or
`server-cleanup.sh` as routine validation. They require elevated network
permissions and can replace the default route, enable forwarding, or alter
iptables rules. Run end-to-end checks only when explicitly requested, using an
isolated VM or network namespace with a recovery plan.

## Validation

There is currently no automated test suite. For ordinary Python changes, run:

```sh
python3 -m py_compile main.py udp.py crypto.py tun.py logger.py
python3 -c "from crypto import Encrypter, Decrypter; p=b'round trip'; e=Encrypter(1).encrypt(p); assert Decrypter(1).decrypt(e) == p"
```

For shell-only changes, perform syntax checks without executing the scripts:

```sh
sh -n client.sh client-cleanup.sh server.sh server-cleanup.sh
```

Add focused standard-library `unittest` coverage when changing behavior that can
be exercised without root access. Keep generated files such as `__pycache__`
out of commits.

## Style and scope

Follow the existing compact style and avoid unrelated refactors. Prefer explicit
byte encodings and explicit byte-order markers in any new serialized data. Check
subprocess exit status when adding host-configuration commands. Keep README usage
and defaults synchronized with the implementation.
