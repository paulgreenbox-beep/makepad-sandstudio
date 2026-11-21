# Linux AI Direct: first milestone

The Linux branch starts the existing MSS Python MCP router over local stdio.
It offers only `mss_server_info` and `mss_list_apps`. Server info identifies
the mode as `stdio_probe`; the catalog is empty. The probe does not read the
Windows catalog or accept any guest, process, sharing, build or input tool.
MSS does not launch Todo on Linux yet. This branch does not port Desktop or
change the Windows launch path.

## Verify the Linux probe

From the repository root on Linux with Python 3.12+:

```sh
python3 -I -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_linux_probe.py'
python3 -I -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_shared_store.py'
```

The first test runs the production entry point in a subprocess, negotiates MCP,
checks the advertised tools and frozen source record, and verifies that an
explicit attempt to launch Todo returns `UNSUPPORTED_PLATFORM`. It also checks
that the Windows catalog is ignored without modifying it. It is not a GUI test.

Use `python3 -I -B MSS_MCP/tools/mss_universal.py` as the local stdio MCP
command if you want to inspect the same two tools from a client.

## Next milestone: one owned Todo guest

Use [Makepad's Todo](https://github.com/makepad/makepad/tree/2271c0eb350cedd497c84373f17ad2b0b662cb72/examples/todo)
and its official Remote from the same pinned Makepad revision. Before enabling
launch in MSS, verify the upstream Todo UI harness on the intended Linux
host. That harness tests Makepad Remote, not the MSS router.

The Linux launcher must admit reviewed native binaries by exact path and
digest, bind the owned app to its process identity, and match its private
Remote discovery to that process. Never infer ownership from a PID, title,
or socket name alone. Use the official Remote client, not desktop-wide input.
Only enable app operations after the ownership, capability, and cleanup
checks have working Linux implementations.

A live MSS acceptance check is: launch a disposable Todo, add a distinctive
item through the app's addressed UI, read the item back independently,
capture the same app window, then verify cleanup of the owned guest.
This milestone is not yet implemented or run.

Owner: MSS MCP. See [verification contracts](testing.md).
