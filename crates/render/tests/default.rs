/*
    Appellation: default <test>
    Created At: 2026.08.12:16:20:00
    Contrib: @FL03
*/
//! The determinism contract, asserted as a gate test.
//!
//! The conformance oracle compares `output_sha256` across implementations. That
//! comparison is only meaningful if rendering is reproducible within a single
//! implementation first, so that property is pinned here.

/// Rendering the same template with the same variables must produce identical
/// bytes. A template engine that iterates a hash map in address order passes a
/// single render and fails this.
#[test]
fn rendering_is_reproducible() {
    let template = "{% for k, v in items | dictsort %}{{ k }}={{ v }};{% endfor %}";
    let mut env = minijinja::Environment::new();
    env.add_template("probe", template)
        .expect("template must compile");
    let tmpl = env.get_template("probe").expect("template must resolve");

    let vars = minijinja::context! {
        items => minijinja::context! { beta => 2, alpha => 1, gamma => 3 },
    };

    let first = tmpl.render(&vars).expect("first render must succeed");
    for _ in 0..64 {
        assert_eq!(
            tmpl.render(&vars).expect("render must succeed"),
            first,
            "rendering must not vary between runs"
        );
    }
    assert_eq!(first, "alpha=1;beta=2;gamma=3;");
}

/// Provenance hashing is SHA-256 over the raw bytes, with no normalization.
/// Pinned against the NIST vector for "abc" so a future digest swap cannot pass
/// silently.
///
/// Note the hand-rolled hex: `sha2` 0.11 returns a `hybrid_array::Array`, which
/// does not implement `LowerHex` the way `generic_array` did on the 0.10 line.
/// `{:x}` compiles under 0.10 and fails under 0.11.
#[test]
fn provenance_hashing_is_sha256_over_raw_bytes() {
    use core::fmt::Write;
    use sha2::{Digest, Sha256};

    let digest = Sha256::digest(b"abc");
    let hex = digest.iter().fold(String::new(), |mut acc, byte| {
        write!(&mut acc, "{byte:02x}").expect("writing to a String cannot fail");
        acc
    });

    assert_eq!(
        hex,
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
}
