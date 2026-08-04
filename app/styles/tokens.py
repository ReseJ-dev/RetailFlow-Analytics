"""Typed design tokens shared by the Streamlit theme and local CSS."""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class ColourTokens:
    """Accessible application and semantic colour palette."""

    application_background: str = "#F6F8FB"
    surface_background: str = "#FFFFFF"
    primary_text: str = "#172033"
    secondary_text: str = "#667085"
    muted_text: str = "#98A2B3"
    border: str = "#E4E7EC"
    primary: str = "#4F46E5"
    primary_hover: str = "#4338CA"
    success: str = "#16A34A"
    warning: str = "#D97706"
    error: str = "#DC2626"
    information: str = "#2563EB"
    success_surface: str = "#F0FDF4"
    success_text: str = "#166534"
    warning_surface: str = "#FFFBEB"
    warning_text: str = "#92400E"
    error_surface: str = "#FEF2F2"
    error_text: str = "#B91C1C"
    information_surface: str = "#EFF6FF"
    information_text: str = "#1D4ED8"
    control_background: str = "#FFFFFF"
    disabled_background: str = "#F2F4F7"
    disabled_text: str = "#667085"
    focus_ring: str = "#A5B4FC"


@dataclass(frozen=True, slots=True)
class LayoutTokens:
    """Content sizing, spacing, and corner-radius scale."""

    content_max_width: str = "1440px"
    desktop_horizontal_padding: str = "clamp(2rem, 3vw, 3rem)"
    mobile_horizontal_padding: str = "1rem"
    card_radius: str = "0.75rem"
    control_radius: str = "0.5625rem"
    space_1: str = "0.25rem"
    space_2: str = "0.5rem"
    space_3: str = "0.75rem"
    space_4: str = "1rem"
    space_6: str = "1.5rem"
    space_8: str = "2rem"
    space_12: str = "3rem"
    control_height: str = "2.625rem"


@dataclass(frozen=True, slots=True)
class TypographyTokens:
    """Local system-font stack and readable type scale."""

    font_family: str = (
        "ui-sans-serif, -apple-system, BlinkMacSystemFont, \"Segoe UI\", "
        "Roboto, Helvetica, Arial, sans-serif"
    )
    body_size: str = "1rem"
    body_line_height: str = "1.55"
    page_title_size: str = "2.25rem"
    page_title_line_height: str = "1.2"
    heading_two_size: str = "1.5rem"
    heading_three_size: str = "1.25rem"
    supporting_size: str = "0.8125rem"
    supporting_line_height: str = "1.4"


@dataclass(frozen=True, slots=True)
class DesignTokens:
    """Complete visual token set for RetailFlow presentation code."""

    colours: ColourTokens = ColourTokens()
    layout: LayoutTokens = LayoutTokens()
    typography: TypographyTokens = TypographyTokens()


DESIGN_TOKENS = DesignTokens()


def _css_name(name: str) -> str:
    return name.replace("_", "-")


def css_custom_properties(tokens: DesignTokens = DESIGN_TOKENS) -> str:
    """Render typed tokens as one CSS custom-property declaration block."""
    declarations: list[str] = []
    for prefix, token_group in (
        ("color", tokens.colours),
        ("layout", tokens.layout),
        ("type", tokens.typography),
    ):
        declarations.extend(
            f"  --rf-{prefix}-{_css_name(field.name)}: {getattr(token_group, field.name)};"
            for field in fields(token_group)
        )
    return ":root {\n" + "\n".join(declarations) + "\n}"


__all__ = [
    "DESIGN_TOKENS",
    "ColourTokens",
    "DesignTokens",
    "LayoutTokens",
    "TypographyTokens",
    "css_custom_properties",
]
