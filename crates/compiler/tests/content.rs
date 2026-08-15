use std::fs;

use shepherd_compiler::content::{ContentError, embedded_compile_input, load_compile_input};

#[test]
fn embedded_content_is_the_canonical_compile_input() {
    let input = embedded_compile_input().expect("canonical content");
    assert!(!input.roles.is_empty());
    assert!(!input.skills.is_empty());
    assert!(
        input
            .roles
            .iter()
            .any(|role| role.source_path == "content/roles/coder.md")
    );
    assert!(
        input
            .skills
            .iter()
            .any(|skill| skill.source_path == "content/skills/thinking/SKILL.md")
    );
    assert!(
        input
            .roles
            .iter()
            .all(|role| !role.source_content.is_empty())
    );
    assert!(
        input
            .skills
            .iter()
            .all(|skill| !skill.source_content.is_empty())
    );
}

#[test]
fn filesystem_loader_uses_the_same_typed_contract() {
    let root =
        std::env::temp_dir().join(format!("shepherd-compiler-content-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(root.join("roles")).expect("roles directory");
    fs::create_dir_all(root.join("skills/thinking")).expect("skills directory");
    fs::write(
        root.join("roles/coder.md"),
        "---\nrole: coder\ndescription: A test role.\nsource: test\nmodel_hint: standard\nwrite_eligible: true\ndispatchable: true\ncapabilities: [read]\nwrite_scope: test\n---\n\nBody\n",
    )
    .expect("role source");
    fs::write(
        root.join("skills/thinking/SKILL.md"),
        "---\nname: thinking\ndescription: A test skill.\nsource: test\nportability: cross-harness\n---\n\nSkill body\n",
    )
    .expect("skill source");

    let input = load_compile_input(&root).expect("fixture content");
    assert_eq!(input.roles[0].role, "coder");
    assert_eq!(input.skills[0].name, "thinking");
    assert!(input.roles[0].source_path.ends_with("roles/coder.md"));
    assert!(
        input.skills[0]
            .source_path
            .ends_with("skills/thinking/SKILL.md")
    );
    let _ = fs::remove_dir_all(&root);
}

#[test]
fn malformed_canonical_content_fails_closed() {
    let root = std::env::temp_dir().join(format!(
        "shepherd-compiler-content-invalid-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(root.join("roles")).expect("roles directory");
    fs::create_dir_all(root.join("skills/thinking")).expect("skills directory");
    fs::write(root.join("roles/coder.md"), "not frontmatter").expect("role source");
    fs::write(
        root.join("skills/thinking/SKILL.md"),
        "---\nname: thinking\ndescription: A test skill.\nsource: test\nportability: cross-harness\n---\n\nSkill body\n",
    )
    .expect("skill source");

    let error = load_compile_input(&root).expect_err("invalid role must fail");
    assert!(matches!(error, ContentError::InvalidFrontmatter { .. }));
    let _ = fs::remove_dir_all(&root);
}

#[test]
fn filesystem_loader_accepts_crlf_authored_content() {
    let root = std::env::temp_dir().join(format!(
        "shepherd-compiler-content-crlf-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(root.join("roles")).expect("roles directory");
    fs::create_dir_all(root.join("skills/thinking")).expect("skills directory");
    fs::write(
        root.join("roles/coder.md"),
        "---\r\nrole: coder\r\ndescription: A test role.\r\nsource: test\r\nmodel_hint: standard\r\nwrite_eligible: true\r\ndispatchable: true\r\ncapabilities: [read]\r\nwrite_scope: test\r\n---\r\n\r\nBody\r\n",
    )
    .expect("role source");
    fs::write(
        root.join("skills/thinking/SKILL.md"),
        "---\r\nname: thinking\r\ndescription: A test skill.\r\nsource: test\r\nportability: cross-harness\r\n---\r\n\r\nSkill body\r\n",
    )
    .expect("skill source");

    let input = load_compile_input(&root).expect("CRLF fixture content");
    assert!(input.roles[0].source_path.ends_with("roles/coder.md"));
    assert!(
        input.skills[0]
            .source_path
            .ends_with("skills/thinking/SKILL.md")
    );
    let _ = fs::remove_dir_all(&root);
}
