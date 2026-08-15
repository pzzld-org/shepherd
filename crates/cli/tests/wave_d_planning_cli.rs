use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    time::{SystemTime, UNIX_EPOCH},
};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

fn fixture(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "shepherd-wave-d-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("create fixture");
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("initialize fixture git repository");
    assert!(status.success(), "git init must succeed");
    root
}

fn invoke(root: &Path, args: &[&str]) -> Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .output()
        .expect("run shepherd binary")
}

fn text(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes).into_owned()
}

fn setup_run(root: &Path) {
    let init = invoke(root, &["init", "--confirm"]);
    assert!(init.status.success(), "init stderr={}", text(&init.stderr));
    let run = invoke(root, &["run", "init", "v900"]);
    assert!(
        run.status.success(),
        "run init stderr={}",
        text(&run.stderr)
    );
}

#[test]
fn plan_hash_validate_topology_and_reports_are_run_scoped() {
    let root = fixture("plan-report");
    setup_run(&root);
    let run = root.join(".shepherd/runs/v900");
    fs::write(run.join("plan.md"), "# Sprint\nlane: l2\nlane: l1\n").expect("write plan");
    fs::create_dir_all(run.join("audits")).expect("create audit fixture");
    fs::create_dir_all(run.join("reports")).expect("create report fixture");
    fs::write(run.join("audits/review.md"), "# Audit\npass\n").expect("write audit");
    fs::write(
        run.join("reports/discovery-pass.md"),
        "# Discovery\nfound\n",
    )
    .expect("write discovery");

    let validate = invoke(&root, &["plan", "validate", "--run", "v900"]);
    assert_eq!(validate.status.code(), Some(0));
    assert_eq!(
        text(&validate.stdout),
        "OK: 1 heading(s), 2 declared lane(s)\n"
    );

    let hash = invoke(&root, &["plan", "hash", "--run", "v900"]);
    assert_eq!(hash.status.code(), Some(0));
    assert_eq!(
        text(&hash.stdout),
        "0716f6a0b7c6756d689b6059ea838828ede3979298e5b33166a675593a9afd1c\n"
    );

    let topology = invoke(&root, &["plan", "topology", "--run", "v900", "--json"]);
    assert_eq!(topology.status.code(), Some(0));
    let topology: serde_json::Value =
        serde_json::from_slice(&topology.stdout).expect("topology json");
    assert_eq!(topology["schema"], "shepherd.plan-topology/1");
    assert_eq!(topology["lanes"], serde_json::json!(["l1", "l2"]));

    let audit = invoke(&root, &["report", "audit", "--run", "v900"]);
    assert_eq!(audit.status.code(), Some(0));
    assert!(text(&audit.stdout).contains("# Audit"));
    let discovery = invoke(&root, &["discovery", "--run", "v900"]);
    assert_eq!(discovery.status.code(), Some(0));
    assert!(text(&discovery.stdout).contains("# Discovery"));

    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn render_uses_project_template_root_and_returns_provenance() {
    let root = fixture("render");
    setup_run(&root);
    let missing = invoke(&root, &["render", "absent"]);
    assert_eq!(missing.status.code(), Some(3));
    fs::create_dir_all(root.join(".shepherd/templates")).expect("create template root");
    fs::write(
        root.join(".shepherd/templates/greeting.j2"),
        "{{ greeting }}, {{ name }}!\n",
    )
    .expect("write template");

    let rendered = invoke(
        &root,
        &[
            "render",
            "greeting",
            "--vars-json",
            r#"{"greeting":"Hello","name":"Base"}"#,
            "--var",
            "name=Shepherd",
            "--json",
        ],
    );
    assert_eq!(
        rendered.status.code(),
        Some(0),
        "stderr={}",
        text(&rendered.stderr)
    );
    let value: serde_json::Value = serde_json::from_slice(&rendered.stdout).expect("render json");
    assert_eq!(value["text"], "Hello, Shepherd!\n");
    assert_eq!(
        value["manifest"]["template_sha256"].as_str().map(str::len),
        Some(64)
    );
    assert_eq!(
        value["manifest"]["vars_sha256"].as_str().map(str::len),
        Some(64)
    );
    assert_eq!(
        value["manifest"]["output_sha256"].as_str().map(str::len),
        Some(64)
    );

    let escape = invoke(&root, &["render", "../greeting"]);
    assert_eq!(escape.status.code(), Some(2));
    assert!(text(&escape.stderr).contains("safe relative path"));
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn graph_is_read_only_and_malformed_state_fails_closed() {
    let root = fixture("graph");
    setup_run(&root);
    let graph = root.join(".shepherd/runs/v900/graph");
    fs::create_dir_all(&graph).expect("create graph fixture");
    fs::write(
        graph.join("state.json"),
        r#"{"nodes":[{"id":"start","label":"Start"},{"id":"finish"}],"edges":[{"from":"start","to":"finish"}]}"#,
    )
    .expect("write state");
    fs::write(graph.join("trace.jsonl"), "{\"event\":\"start\"}\n").expect("write trace");

    let diagram = invoke(&root, &["graph", "diagram", "--run", "v900"]);
    assert_eq!(
        diagram.status.code(),
        Some(0),
        "stderr={}",
        text(&diagram.stderr)
    );
    assert_eq!(
        text(&diagram.stdout),
        "flowchart TD\n  start[\"Start\"]\n  finish[\"finish\"]\n  start --> finish\n"
    );
    let trace = invoke(&root, &["graph", "trace", "--run", "v900", "--json"]);
    assert_eq!(trace.status.code(), Some(0));
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&trace.stdout).expect("trace json")["records"],
        serde_json::json!([{"event":"start"}])
    );

    fs::write(
        graph.join("state.json"),
        "{\"nodes\":[{\"id\":\"bad-id\"}],\"edges\":[]}",
    )
    .expect("write malformed state");
    let malformed = invoke(&root, &["graph", "diagram", "--run", "v900"]);
    assert_eq!(malformed.status.code(), Some(6));
    assert!(text(&malformed.stderr).contains("Mermaid-safe"));
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn close_lane_updates_only_the_registered_lane_in_the_run_ledger() {
    let root = fixture("close-lane");
    setup_run(&root);
    let add = invoke(
        &root,
        &[
            "run",
            "lane",
            "add",
            "v900",
            "l1-engine",
            "--branch",
            "lane/l1",
        ],
    );
    assert_eq!(add.status.code(), Some(0), "stderr={}", text(&add.stderr));

    let clean = invoke(
        &root,
        &[
            "close-lane",
            "--run",
            "v900",
            "l1-engine",
            "--status",
            "clean",
        ],
    );
    assert_eq!(clean.status.code(), Some(0));
    assert_eq!(
        text(&clean.stdout),
        "lane l1-engine closed in v900 (clean)\n"
    );
    let complete = invoke(&root, &["run", "show", "v900"]);
    assert!(text(&complete.stdout).contains("l1-engine: complete"));

    let partial = invoke(
        &root,
        &[
            "close-lane",
            "--run",
            "v900",
            "l1-engine",
            "--status",
            "partial",
        ],
    );
    assert_eq!(partial.status.code(), Some(0));
    let error = invoke(&root, &["run", "show", "v900"]);
    assert!(text(&error.stdout).contains("l1-engine: error"));

    let invalid = invoke(
        &root,
        &[
            "close-lane",
            "--run",
            "v900",
            "l1-engine",
            "--status",
            "bogus",
        ],
    );
    assert_eq!(invalid.status.code(), Some(2));
    let unchanged = invoke(&root, &["run", "show", "v900"]);
    assert!(text(&unchanged.stdout).contains("l1-engine: error"));
    fs::remove_dir_all(root).expect("cleanup");
}

#[cfg(unix)]
#[test]
fn artifact_and_template_symlinks_are_refused_without_reading_targets() {
    use std::os::unix::fs::symlink;

    let root = fixture("symlinks");
    setup_run(&root);
    let run = root.join(".shepherd/runs/v900");
    let outside = root.join("outside.md");
    fs::write(&outside, "OUTSIDE-SENTINEL\n").expect("write outside fixture");
    symlink(&outside, run.join("plan.md")).expect("link plan");

    let plan = invoke(&root, &["plan", "hash", "--run", "v900"]);
    assert_eq!(plan.status.code(), Some(2));
    assert!(!text(&plan.stdout).contains("OUTSIDE-SENTINEL"));

    let outside_audits = root.join("outside-audits");
    fs::create_dir_all(&outside_audits).expect("create outside audit directory");
    fs::write(outside_audits.join("audit.md"), "OUTSIDE-SENTINEL\n").expect("write audit");
    symlink(&outside_audits, run.join("audits")).expect("link audits");
    let audit = invoke(&root, &["report", "audit", "--run", "v900"]);
    assert_eq!(audit.status.code(), Some(2));
    assert!(!text(&audit.stdout).contains("OUTSIDE-SENTINEL"));

    fs::create_dir_all(root.join(".shepherd/templates")).expect("create template root");
    symlink(&outside, root.join(".shepherd/templates/greeting.j2")).expect("link template");
    let render = invoke(&root, &["render", "greeting", "--var", "name=Shepherd"]);
    assert_eq!(render.status.code(), Some(2));
    assert!(!text(&render.stdout).contains("OUTSIDE-SENTINEL"));
    fs::remove_dir_all(root).expect("cleanup");
}

#[cfg(unix)]
#[test]
fn descriptor_read_never_returns_content_from_a_raced_symlink_swap() {
    use std::{
        os::unix::fs::symlink,
        sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
        },
        thread,
    };

    let root = fixture("swap");
    setup_run(&root);
    let run = root.join(".shepherd/runs/v900");
    let target = run.join("plan.md");
    let parked = run.join("plan.parked.md");
    let outside = root.join("outside.md");
    fs::write(&target, "# Safe\n").expect("write safe plan");
    fs::write(&outside, "OUTSIDE-SENTINEL\n").expect("write outside plan");
    let baseline = invoke(&root, &["plan", "hash", "--run", "v900"]);
    assert_eq!(baseline.status.code(), Some(0));
    let safe_hash = text(&baseline.stdout);

    let stop = Arc::new(AtomicBool::new(false));
    let thread_stop = Arc::clone(&stop);
    let swap_target = target.clone();
    let swap_parked = parked.clone();
    let swap_outside = outside.clone();
    let swapper = thread::spawn(move || {
        while !thread_stop.load(Ordering::Relaxed) {
            let _ = fs::rename(&swap_target, &swap_parked);
            let _ = symlink(&swap_outside, &swap_target);
            let _ = fs::remove_file(&swap_target);
            let _ = fs::rename(&swap_parked, &swap_target);
        }
    });
    for _ in 0..64 {
        let result = invoke(&root, &["plan", "hash", "--run", "v900"]);
        if result.status.success() {
            assert_eq!(text(&result.stdout), safe_hash);
        }
        assert!(!text(&result.stdout).contains("OUTSIDE-SENTINEL"));
        assert!(!text(&result.stderr).contains("OUTSIDE-SENTINEL"));
    }
    stop.store(true, Ordering::Relaxed);
    swapper.join().expect("join swapper");
    fs::remove_dir_all(root).expect("cleanup");
}
