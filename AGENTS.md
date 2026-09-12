# Repository Guidelines

## Project scope

This repository implements a small Linux TUN-to-UDP tunnel. Keep changes focused
and preserve the deliberately simple module boundaries:

- `main.py` parses arguments, configures the host, and runs the selector loop.
- `tun.py` owns the Linux TUN file descriptor and ioctl setup.
- `udp.py` owns framing, authentication checks, padding, and UDP transport.
- `crypto.py` owns the packet cipher implementation.
- `logger.py` owns traffic reporting.
- `client*.sh` and `server*.sh` modify routing, forwarding, and nftables state.
- `run-deployment-container.sh` and `run-deployment-container.sh` launch
  main.py in a docker container, passing their command line arguments to
main.py; if the command line arguments indicate that main.py is to be launched
as a server listening on a given port, docker is instructed to perform
appropriate port forwarding.

The code targets Python 3.5 or newer and uses only the standard library.  Keep
the shell scripts POSIX `sh` compatible.

## Protocol changes

Backward compatibility is of no concern. Client and server must remain
compatible, and encryption and decryption state transitions must stay
symmetric. When changing packet layout, padding, integer encoding, or
authentication behavior, update both directions and the README.md

## Network safety
Run end-to-end checks only in docker containers. E.g., server in one container,
client in the other. Do not run `main.py`, `client.sh`, `client-cleanup.sh`,
`server.sh`, or `server-cleanup.sh` outside docker containers, as they alter
network configuration and may disrupt internet access.

The Docker launchers intentionally use Docker's isolated network namespace.
When running a client, its setup and default-route replacement must affect only
the container, not the host, so the tunnel can be tested without disrupting the
host's Internet access. Do not add host networking to the containers.

## Validation

For ordinary Python changes, run:

```sh
python3 -m unittest discover -s tests
python3 -m py_compile main.py udp.py crypto.py tun.py logger.py
python3 -c "from crypto import Encrypter, Decrypter; p=b'round trip'; e=Encrypter(1).encrypt(p); assert Decrypter(1).decrypt(e) == p"
```

For shell-only changes, one can perform syntax checks without executing the scripts:

```sh
sh -n client.sh client-cleanup.sh server.sh server-cleanup.sh \
    run-development-container.sh run-deployment-container.sh
```

Add focused standard-library `unittest` coverage when changing behavior that
can be exercised without root access. Network-script tests must mock privileged
commands or use docker containers instead of modifying network configuration of
the host. Keep generated files such as `__pycache__` out of commits.

## Style and scope

Follow the existing compact style and avoid unrelated refactors. Prefer explicit
byte encodings and explicit byte-order markers in any new serialized data. Check
subprocess exit status when adding host-configuration commands. Keep README usage
and defaults synchronized with the implementation.

Ignore files matched by `.gitignore`, including Vim swap files. Do not inspect,
modify, delete, stage, or report ignored files unless explicitly requested.
