import tomllib
from pathlib import Path

from app import main as application
from app.styles.theme import apply_global_theme, build_global_css
from app.styles.tokens import DESIGN_TOKENS, css_custom_properties

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _relative_luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def test_design_tokens_match_the_approved_palette() -> None:
    colours = DESIGN_TOKENS.colours

    assert colours.application_background == "#F6F8FB"
    assert colours.surface_background == "#FFFFFF"
    assert colours.primary_text == "#172033"
    assert colours.secondary_text == "#667085"
    assert colours.muted_text == "#98A2B3"
    assert colours.border == "#E4E7EC"
    assert colours.primary == "#4F46E5"
    assert colours.primary_hover == "#4338CA"
    assert colours.success == "#16A34A"
    assert colours.warning == "#D97706"
    assert colours.error == "#DC2626"
    assert colours.information == "#2563EB"


def test_css_custom_properties_include_layout_and_typography_tokens() -> None:
    css = css_custom_properties()

    assert "--rf-layout-content-max-width: 1440px;" in css
    assert "--rf-layout-card-radius: 0.75rem;" in css
    assert "--rf-layout-control-radius: 0.5625rem;" in css
    assert "--rf-layout-control-height: 2.75rem;" in css
    assert "--rf-type-font-family: ui-sans-serif" in css
    assert "--rf-color-primary-text: #172033;" in css


def test_global_css_is_local_organised_and_contains_semantic_classes() -> None:
    css = build_global_css()

    assert '[data-testid="stAppViewContainer"]' in css
    assert '[data-testid="stFileUploader"]' in css
    assert ".rf-alert--success" in css
    assert ".rf-alert--warning" in css
    assert ".rf-alert--error" in css
    assert ":focus-visible" in css
    assert "@media (max-width: 1100px)" in css
    assert '[data-testid="stDataFrame"]' in css
    assert "overflow: auto" in css
    assert "flex-wrap: wrap" in css
    assert "!important" not in css
    assert "http://" not in css
    assert "https://" not in css


def test_missing_stylesheet_retains_readable_token_defaults(tmp_path: Path) -> None:
    css = build_global_css(tmp_path / "missing.css")

    assert "--rf-color-application-background: #F6F8FB;" in css
    assert "--rf-color-primary-text: #172033;" in css


def test_theme_injection_writes_one_trusted_style_block(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []

    def capture(markup: str, *, unsafe_allow_html: bool) -> None:
        calls.append((markup, unsafe_allow_html))

    monkeypatch.setattr("app.styles.theme.st.markdown", capture)

    apply_global_theme()

    assert len(calls) == 1
    assert calls[0][0].startswith("<style>:root {")
    assert calls[0][0].endswith("</style>")
    assert calls[0][1] is True


def test_application_initialises_the_shared_theme_once(monkeypatch) -> None:
    loaded_stylesheets: list[Path] = []
    monkeypatch.setattr(application.st, "set_page_config", lambda **kwargs: None)
    monkeypatch.setattr(application, "load_local_css", loaded_stylesheets.append)
    monkeypatch.setattr(application, "_render_application", lambda: None)

    application.main()

    assert loaded_stylesheets == [Path(application.__file__).with_name("styles.css")]


def test_streamlit_theme_uses_tokens_and_supported_shell_configuration() -> None:
    with (PROJECT_ROOT / ".streamlit" / "config.toml").open("rb") as config_file:
        config = tomllib.load(config_file)

    theme = config["theme"]
    colours = DESIGN_TOKENS.colours
    assert theme["base"] == "light"
    assert theme["primaryColor"] == colours.primary
    assert theme["backgroundColor"] == colours.application_background
    assert theme["secondaryBackgroundColor"] == colours.surface_background
    assert theme["textColor"] == colours.primary_text
    assert theme["borderColor"] == colours.border
    assert config["client"] == {
        "showSidebarNavigation": False,
        "toolbarMode": "viewer",
        "showErrorLinks": False,
    }


def test_text_and_semantic_surface_pairs_meet_wcag_aa_contrast() -> None:
    colours = DESIGN_TOKENS.colours
    pairs = (
        (colours.primary_text, colours.application_background),
        (colours.primary_text, colours.surface_background),
        (colours.secondary_text, colours.surface_background),
        (colours.surface_background, colours.primary),
        (colours.success_text, colours.success_surface),
        (colours.warning_text, colours.warning_surface),
        (colours.error_text, colours.error_surface),
        (colours.information_text, colours.information_surface),
    )

    assert all(_contrast_ratio(text, background) >= 4.5 for text, background in pairs)
