from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_g45_default_project_shell_has_one_bounded_row():
    css = source("motorcad_studio/static/ui-convergence-g4.css")
    selector = 'body:not([data-user-mode="expert"]):not([data-user-mode="developer"]) #projectShell'
    assert selector in css
    assert "grid-template-rows:56px!important" in css
    assert "height:56px!important" in css
    assert "max-height:56px!important" in css
    assert "overflow:hidden!important" in css


def test_g45_navigation_owns_row_and_focus_bar_is_hidden():
    css = source("motorcad_studio/static/ui-convergence-g4.css")
    assert "#projectShell>.project-stage-nav" in css
    assert "#projectShell>#engineerFocusBarV089F" in css
    assert "grid-row:1!important" in css
    assert "height:56px!important" in css
    assert "#projectShell>#engineerFocusBarV089F" in css
    assert "display:none!important" in css


def test_g44_redundant_context_surfaces_are_hidden_in_default_mode():
    css = source("motorcad_studio/static/ui-convergence-g4.css")
    assert "#projectShell>#engineeringContextBreadcrumbV089A" in css
    assert "#projectShell>#engineerJourneyCueV086R" in css
    assert "display:none!important" in css


def test_g44_four_stage_labels_stay_inside_the_bounded_navigation_row():
    css = source("motorcad_studio/static/ui-convergence-g4.css")
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in css
    assert "text-overflow:ellipsis!important" in css
    assert "white-space:nowrap!important" in css
