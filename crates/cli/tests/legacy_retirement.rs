use std::process::Command;

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

#[test]
fn unported_legacy_command_fails_at_the_native_boundary_without_a_fallback() {
    let output = Command::new(binary())
        .args(["style"])
        .output()
        .expect("run shepherd");

    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert_eq!(
        String::from_utf8(output.stderr).expect("utf-8 diagnostic"),
        "ERROR: command `style` is unavailable in the canonical Rust CLI; legacy Python, Bash, and Node command authorities are retired\n"
    );
}
