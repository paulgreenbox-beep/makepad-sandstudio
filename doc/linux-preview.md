# Linux AI Direct: owned Todo experiment

MSS can run its existing Python MCP entry point on Linux. With no Linux pins it only offers
`mss_server_info` and an empty `mss_list_apps` (`stdio_probe`). A local operator can configure
one experimental Todo profile. The router accepts only one active instance per MCP connection
and drives it through the official Makepad Remote client, not physical desktop input.
It permits semantic text replacement on the Todo input and a press on Add, as well as
status, observation, capture and owner cleanup. Sharing, arbitrary executable launch,
Windows build management, raw input and Desktop are not part of this experiment.
Windows uses the existing catalog and launcher.

## Setup

Use Linux with Python 3.12+, Linux pidfds, local Unix-domain sockets, and an offscreen-capable EGL/OpenGL runtime.
Build [Makepad Todo](https://github.com/makepad/makepad/tree/2271c0eb350cedd497c84373f17ad2b0b662cb72/examples/todo)
and its official Remote from the same reviewed Makepad revision, `2271c0eb350cedd497c84373f17ad2b0b662cb72`.
See the pinned [Linux build prerequisites](https://github.com/makepad/makepad/blob/2271c0eb350cedd497c84373f17ad2b0b662cb72/tools/linux_deps.sh).
Review the prerequisites before installing anything. In that Makepad checkout:

```sh
cargo build --release -p makepad-example-todo -p makepad-remote
export MSS_LINUX_TODO_EXE="$PWD/target/release/makepad-example-todo"
export MSS_LINUX_REMOTE_EXE="$PWD/target/release/makepad-remote"
export MSS_LINUX_TODO_CWD="$PWD/examples/todo"
export MSS_LINUX_TODO_SHA256="$(sha256sum "$MSS_LINUX_TODO_EXE" | cut -d ' ' -f 1)"
export MSS_LINUX_REMOTE_SHA256="$(sha256sum "$MSS_LINUX_REMOTE_EXE" | cut -d ' ' -f 1)"
```

Use absolute, canonical paths and exact hashes of binaries you trust. Never supply pins
through tool arguments. Initialize a fresh local MCP client with
`python3 -I -B MSS_MCP/tools/mss_universal.py` from the MSS checkout. Use the App ID
returned by `mss_launch_app` and the current window/node from that app. Do not expose the
stdio server or Makepad endpoint to other users. The trusted same-user development
model is **not an OS sandbox**.

## Verify

From the MSS checkout:

```sh
python3 -I -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_linux_probe.py'
python3 -I -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_linux_todo_router.py'
python3 -I -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_linux_todo_live.py'
```

The first command verifies the unconfigured real stdio transport, the second exercises router
policy with a synthetic peer, and the third is the opt-in Todo GUI acceptance.
The live case requires the executable pins above. It checks independent readback of the
added item, native pixel capture, and verified owned-process exit. Set
`MSS_LINUX_TODO_SCREENSHOT` to a fresh absolute path to keep the verified PNG.
A source check, synthetic peer or an EGL context alone does not establish native Todo behavior.
A transport error after dispatch is an unknown outcome and is not retried automatically.

Owner: MSS MCP. See [verification contracts](testing.md).
