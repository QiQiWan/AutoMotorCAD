from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_v089b_action_registry_is_loaded_before_product_handlers_and_has_operator_panel():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '/static/hmi/action-registry.js?v=0.89.9' in html
    assert html.index('/static/hmi/action-registry.js?v=') < html.index('/static/i18n.js?v=')
    assert 'id="hmiQualificationPanelV089B"' in html
    assert 'id="runHmiQualificationV089B"' in html
    assert 'id="exportHmiQualificationV089B"' in html
    assert 'id="hmiQualificationSummaryV089B"' in html


def test_v089b_every_fixed_button_has_a_stable_source_identity_or_semantic_action_attribute():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    buttons = re.findall(r"<button\b([^>]*)>(.*?)</button>", html, re.S | re.I)
    assert len(buttons) >= 87
    semantic = (
        "data-tab=", "data-go=", "data-engineer-stage=", "data-analysis-step-v076=",
        "data-fea-mode-v022=", "data-event-filter=", "data-viewer-mode=",
    )
    missing = []
    for index, (attrs, body) in enumerate(buttons, 1):
        if re.search(r"\bid=\"[^\"]+\"", attrs):
            continue
        if any(token in attrs for token in semantic):
            continue
        label = re.sub(r"<[^>]+>", " ", body)
        missing.append((index, re.sub(r"\s+", " ", label).strip(), attrs.strip()))
    assert missing == []


def test_v089b_registry_contract_tracks_fixed_dynamic_binding_and_release_metrics():
    source = (STATIC / "hmi" / "action-registry.js").read_text(encoding="utf-8")
    for token in (
        "HMIActionQualificationAuthorityV1",
        "fixed_qualification_percent",
        "qualification_percent",
        "handler_evidence",
        "stable_identity",
        "observed_dynamic_families",
        "declared-delegated-family",
        "deferred-page-owner",
        "MutationObserver",
        "destructive",
    ):
        assert token in source
