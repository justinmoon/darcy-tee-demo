"""One real prompt in the owned confidential Sandbox; stop compute afterward."""

import argparse

from sandbox import attest, lifecycle
from sandbox_e2e import Tunnel, initialize, install, wait_started


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    args = parser.parse_args()
    try:
        lifecycle("start")
        wait_started()
        print(attest(), flush=True)
        install()
        with Tunnel() as remote:
            initialize(remote)
            result = remote.request("run", prompt=args.prompt)
            print(result["answer"], flush=True)
            print("Tools: " + ", ".join(result["tools"]), flush=True)
    finally:
        lifecycle("stop")


if __name__ == "__main__":
    main()
