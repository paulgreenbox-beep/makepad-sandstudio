//! Production entry point remains fail-closed until the complete trust boundary
//! is qualified. Protocol acceptance alone never authorizes process execution.
use mss_native_check_broker::protocol::{MAX_BYTES, parse_request};
use std::io::{self, Read};

fn main() {
    // stdout is reserved for actual receipt arrays, never request or host data.
    if std::env::args_os().len() != 1 {
        eprintln!("BLOCKED: BROKER_ARGUMENTS_FORBIDDEN");
        std::process::exit(2);
    }
    let mut raw = Vec::new();
    if io::stdin()
        .take((MAX_BYTES + 1) as u64)
        .read_to_end(&mut raw)
        .is_err()
        || raw.len() > MAX_BYTES
    {
        eprintln!("BLOCKED: REQUEST_TOO_LARGE_OR_UNREADABLE");
        std::process::exit(2);
    }
    match parse_request(&raw) {
        Err(code) => eprintln!("BLOCKED: {code}"),
        Ok(_) => eprintln!(
            "BLOCKED: CALLER_IDENTITY_PROTECTED_SOURCE_AND_NETWORK_BOUNDARY_NOT_QUALIFIED"
        ),
    }
    // Native supervisor probes are separate tests, not a production grant.
    // Do not launch Git/checks, mint receipts, or infer PASS from valid JSON.
    std::process::exit(3);
}
