use shepherd_compiler::{
    BudgetClass, BudgetError, BudgetLimits, TOKENIZER_VERSION, measure_text, validate_budget,
};

#[test]
fn versioned_measurement_uses_unicode_words_and_utf8_bytes() {
    let measured = measure_text("naïve can't \u{4f60}\u{597d}\n");

    assert_eq!(TOKENIZER_VERSION, "shepherd-prompt-v1-uax29");
    assert_eq!(measured.lines, 1);
    // UAX #29 treats the two Han ideographs as separate words.
    assert_eq!(measured.words, 4);
    assert_eq!(measured.utf8_bytes, 20);
    assert!(measured.prompt_tokens >= 3);
}

#[test]
fn every_hard_budget_is_pinned_as_data() {
    assert_eq!(
        BudgetLimits::for_class(BudgetClass::Skill),
        (100, 500, 6 * 1024)
    );
    assert_eq!(
        BudgetLimits::for_class(BudgetClass::AlwaysLoadedSkill),
        (60, 200, 3 * 1024)
    );
    assert_eq!(
        BudgetLimits::for_class(BudgetClass::Role),
        (100, 600, 7 * 1024)
    );
    assert_eq!(
        BudgetLimits::for_class(BudgetClass::Reference),
        (220, 1_500, 16 * 1024)
    );
    assert_eq!(
        BudgetLimits::for_class(BudgetClass::Doctrine),
        (160, 1_000, 12 * 1024)
    );
    assert_eq!(
        BudgetLimits::for_class(BudgetClass::Command),
        (140, 750, 9 * 1024)
    );
    assert_eq!(
        BudgetLimits::for_class(BudgetClass::AlwaysLoadedBundle),
        (300, 2_000, 22 * 1024)
    );
    assert_eq!(
        BudgetLimits::for_class(BudgetClass::HarnessSkillSet),
        (700, 3_500, 42 * 1024)
    );
}

#[test]
fn zero_input_and_each_overage_fail_closed() {
    assert_eq!(
        validate_budget("skill", BudgetClass::Skill, ""),
        Err(BudgetError::Empty {
            name: "skill".into()
        })
    );

    let too_many_lines = "word\n".repeat(101);
    assert!(matches!(
        validate_budget("skill", BudgetClass::Skill, &too_many_lines),
        Err(BudgetError::Exceeded {
            metric: "lines",
            ..
        })
    ));

    let too_many_words = format!("{}\n", "word ".repeat(501));
    assert!(matches!(
        validate_budget("skill", BudgetClass::Skill, &too_many_words),
        Err(BudgetError::Exceeded {
            metric: "words",
            ..
        })
    ));

    let too_many_bytes = format!("{}\n", "x".repeat(6 * 1024));
    assert!(matches!(
        validate_budget("skill", BudgetClass::Skill, &too_many_bytes),
        Err(BudgetError::Exceeded {
            metric: "utf8_bytes",
            ..
        })
    ));
}

#[test]
fn every_budget_class_rejects_each_measured_dimension() {
    for class in [
        BudgetClass::Skill,
        BudgetClass::AlwaysLoadedSkill,
        BudgetClass::Role,
        BudgetClass::Reference,
        BudgetClass::Doctrine,
        BudgetClass::Command,
        BudgetClass::AlwaysLoadedBundle,
        BudgetClass::HarnessSkillSet,
    ] {
        let (line_limit, word_limit, byte_limit) = BudgetLimits::for_class(class);
        let name = format!("{class:?}");

        let too_many_lines = "word\n".repeat(line_limit + 1);
        assert!(matches!(
            validate_budget(&name, class, &too_many_lines),
            Err(BudgetError::Exceeded {
                metric: "lines",
                ..
            })
        ));

        let too_many_words = format!("{}\n", "word ".repeat(word_limit + 1));
        assert!(matches!(
            validate_budget(&name, class, &too_many_words),
            Err(BudgetError::Exceeded {
                metric: "words",
                ..
            })
        ));

        let too_many_bytes = format!("{}\n", "x".repeat(byte_limit));
        assert!(matches!(
            validate_budget(&name, class, &too_many_bytes),
            Err(BudgetError::Exceeded {
                metric: "utf8_bytes",
                ..
            })
        ));
    }
}

#[test]
fn exact_budget_boundaries_pass() {
    let exact = format!("{}\n", "word ".repeat(500));
    let measured = validate_budget("skill", BudgetClass::Skill, &exact).expect("at limit");
    assert_eq!(measured.words, 500);
}
