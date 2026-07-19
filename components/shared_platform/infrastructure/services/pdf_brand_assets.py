"""Default brand assets embedded into generated PDFs.

We inline SVGs as data URIs so the rendered PDF is self-contained — no
external fetches, no race conditions against CDN cache, and the PDF
looks identical whether rendered from a dev laptop or a prod EC2.
"""

from __future__ import annotations

import base64
import logging
from uuid import UUID

logger = logging.getLogger(__name__)


def _soft_tint(hex_color: str, white: float = 0.86) -> str:
    """Mix a hex colour toward white — a near-white brand tint for soft accent
    backgrounds (e.g. the financial report's ``--accent-soft`` chips/pills)."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
        r = round(r + (255 - r) * white)
        g = round(g + (255 - g) * white)
        b = round(b + (255 - b) * white)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


def _deep_shade(hex_color: str, black: float = 0.28) -> str:
    """Darken a hex colour toward black — a deeper brand shade for accents that
    carry more weight (e.g. the financial report's ``--accent-deep``)."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
        r = round(r * (1 - black))
        g = round(g * (1 - black))
        b = round(b * (1 - black))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


# Octopus accent fallbacks — used when a workspace is unthemed or brand
# resolution can't run. Kept equal to the colours the artifacts previously
# hard-coded, so an unthemed workspace renders exactly as before. Font stacks
# mirror workspace domain OCTOPUS_FONTS (literal here — artifact rendering must
# not import another context at module load).
_FALLBACK_BRAND = {
    "primary": "#10b981",  # accent on DARK artifacts (e.g. the receipt PDF)
    "primary_light": "#42B98F",  # accent on LIGHT artifacts
    "primary_soft": _soft_tint("#42B98F"),  # near-white tint for soft accents
    "primary_deep": _deep_shade("#42B98F"),  # deeper shade for weightier accents
    "secondary": "#F5AB5B",
    "font_heading_stack": "'Poppins', 'Helvetica Neue', Arial, sans-serif",
    "font_body_stack": "'Inter', 'Helvetica Neue', Arial, sans-serif",
}


def resolve_brand_colors(workspace_id: str | None) -> dict[str, str]:
    """Resolve a workspace's brand as concrete hex colours for PDF/email artifacts.

    Returns ``{primary, primary_light, secondary}`` as hex strings. ``primary``
    is the DARK-mode brand primary (legible on the dark receipt canvas);
    ``primary_light`` is the LIGHT-mode primary (for light artifacts).

    A brand-colour lookup MUST NEVER break artifact rendering — a receipt is a
    money document that has to generate regardless. So an unthemed workspace, a
    bad id, or any resolution error falls back to the Octopus accent (which is
    what the artifacts hard-coded before), logged but not raised.
    """
    if not workspace_id:
        return dict(_FALLBACK_BRAND)
    try:
        from components.workspace.application.providers.brand_resolution_provider import (
            get_brand_resolution_provider,
        )
        from components.workspace.domain.value_objects.semantic_token_set import (
            BrandOutputShape,
        )

        resolved = get_brand_resolution_provider().port().resolve(UUID(str(workspace_id)), BrandOutputShape.HEX)
        primary_light = resolved["light"].get("primary") or _FALLBACK_BRAND["primary_light"]
        fonts = resolved.get("fonts") or {}
        return {
            "primary": resolved["dark"].get("primary") or _FALLBACK_BRAND["primary"],
            "primary_light": primary_light,
            "primary_soft": _soft_tint(primary_light),
            "primary_deep": _deep_shade(primary_light),
            "secondary": resolved["light"].get("secondary") or _FALLBACK_BRAND["secondary"],
            # Email/PDF can't load webfonts reliably — the fallback stack IS the guarantee.
            "font_heading_stack": (fonts.get("heading") or {}).get("stack")
            or _FALLBACK_BRAND["font_heading_stack"],
            "font_body_stack": (fonts.get("body") or {}).get("stack")
            or _FALLBACK_BRAND["font_body_stack"],
        }
    except Exception:
        # Decorative colour lookup on a money-critical artifact: fall back to
        # the platform accent rather than fail the render. Broad catch is
        # deliberate — DB error, bad UUID, or missing theme all degrade the
        # same safe way.
        logger.exception("resolve_brand_colors failed; using fallback workspace_id=%s", workspace_id)
        return dict(_FALLBACK_BRAND)


# Default brand mark — the Octopus logo used on the floating chat button
# in the frontend (``src/components/Utility/OctopusLogo.js``). Kept in
# sync with that file; if the frontend swaps the mark, update the path
# data here too. Used whenever a workspace has no ``photo_url`` set, so
# every generated PDF carries the platform brand.
DEFAULT_BRAND_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 886 807" preserveAspectRatio="xMidYMid meet">
  <defs>
    <linearGradient id="octoBody" x1="442.856" y1="2" x2="442.856" y2="804.776" gradientUnits="userSpaceOnUse">
      <stop stop-color="#FFAE00"/>
      <stop offset="1" stop-color="#024C1E"/>
    </linearGradient>
    <linearGradient id="octoStroke" x1="442.856" y1="2" x2="442.856" y2="804.776" gradientUnits="userSpaceOnUse">
      <stop stop-color="#FFEE31"/>
      <stop offset="1" stop-color="#05F555"/>
    </linearGradient>
  </defs>
  <path d="M596.071 147C593.504 55.08 510.571 2.00006 454.071 2C432.191 1.99998 398.487 4.43785 378.571 13.5C342.126 30.0834 323.853 46.1244 306.071 82C281.357 131.861 281.701 185.125 310.071 233C326.071 260 330.071 310 306.071 342C282.342 373.639 250.049 386.5 217.071 365C180.472 341.139 216.733 279.607 185.071 249.5C161.705 227.281 140.822 215.061 109.571 223C81.1698 230.216 61.5713 255 61.5713 286C61.5713 308.326 90.5712 317.5 90.5712 317.5C90.5712 317.5 56.0713 277 94.5713 255.5C133.071 234 168.571 262 158.071 320C154.179 341.5 158.643 397.541 192.071 413.5C269.571 450.5 306.071 399.5 306.071 399.5C306.071 399.5 299.203 412.141 289.071 422C259.65 450.629 217.571 452.5 188.571 439C143.662 418.094 99.2514 388.187 54.0712 408.5C12.228 427.313 -4.98591 459.129 4.57119 504C11.045 534.395 37.4945 562.5 68.5713 562.5C99.5713 562.5 117.071 526.5 117.071 526.5C117.071 526.5 77.3458 550.4 58.5712 534.5C32.4056 512.34 31.0713 464 58.5712 452.5C121.701 426.1 140.844 489.464 188.571 497C321.571 518 360.071 427.5 360.071 427.5C360.071 427.5 347.071 486.5 298.571 511.5C233.205 545.194 164.571 537 136.571 612.5C121.201 653.946 122.071 684.5 148.571 719.5C172.443 751.028 210.176 765.637 245.571 748C272.279 734.692 284.071 711 284.071 687C284.071 669.099 257.571 651.5 257.571 651.5C257.571 651.5 283.513 694.323 251.071 715.5C179.071 762.5 142.078 644.434 198.571 610C251.071 578 296.297 590.964 360.571 546.5C433.571 496 425.571 410 449.571 432.5C473.571 455 447.571 517 396.571 569.5C351.812 615.576 331.571 687 360.571 745C381.268 786.393 431.513 818.308 473.571 799C505.648 784.274 525.571 753 516.071 719.5C511.098 701.964 482.571 687 482.571 687C482.571 687 500.837 708.792 499.571 725C497.307 753.991 469.571 784 439.571 766.5C381.202 732.451 392.029 652.421 425.571 619.5C506.571 540 508.071 509.5 508.071 509.5C508.071 509.5 547.643 569.747 604.571 580.5C660.571 591.078 689.747 635.888 683.071 672.5C670.946 739 607.828 743.77 588.571 715.5C565.071 681 600.571 651.5 600.571 651.5C600.571 651.5 589.571 646.5 567.571 667.5C555.75 678.784 555.889 725.265 579.571 745C621.571 780 672.66 772.996 713.071 740C759.673 701.95 756.115 643.362 735.071 587C718.713 543.188 652.071 497 652.071 497C652.071 497 707.969 502.282 764.571 457C787.071 439 846.571 439 841.071 497C836.646 543.663 771.571 543 771.571 543C771.571 543 811.405 566.417 836.071 558.5C858.026 551.453 868.915 537.872 877.571 516.5C888.03 490.676 884.758 471 870.571 445.5C853.786 415.329 824.071 395.5 771.571 404C725.785 411.413 745.071 430.682 663.571 445.5C619.174 453.572 577.071 399.5 577.071 399.5C577.071 399.5 643.071 449 691.571 413.5C744.413 374.822 724.489 342.867 721.071 299C718.071 260.5 761.63 235.128 788.071 253C842.071 289.5 776.534 328.916 800.571 318.5C815.571 312 821.8 305.641 824.071 290.5C827.071 270.5 821.477 254.247 808.571 240.5C785.571 216 760.565 218.091 730.571 228.5C687.674 243.387 680.432 280.702 683.571 326C687.071 376.5 616.417 393.345 590.571 357.5C522.071 262.5 598.571 236.5 596.071 147Z" fill="url(#octoBody)" stroke="url(#octoStroke)" stroke-width="4"/>
  <path d="M345.099 152C352.055 152 359.779 155.883 365.819 161.456C371.885 167.052 375.881 174.001 375.881 179.779C375.881 185.328 372.151 189.426 366.2 192.216C360.256 195.003 352.42 196.297 345.099 196.297C337.899 196.297 331.498 194.284 326.93 190.592C322.395 186.928 319.571 181.54 319.571 174.524C319.571 167.502 322.403 161.914 326.956 158.06C331.534 154.185 337.93 152 345.099 152Z" fill="black" stroke="#2A6D43" stroke-width="3"/>
  <path d="M638.071 513.5C634.429 506.157 623.762 503.629 617.571 509C613.418 512.603 612.171 517.183 613.571 522.5C615.617 530.269 624.817 534.953 632.071 531.5C638.762 528.316 641.364 520.138 638.071 513.5Z" stroke="#FFAE00" stroke-width="4" fill="none"/>
  <path d="M674.571 544.5C674.09 536 665.262 529.178 657.071 531.5C650.909 533.247 647.374 538.102 647.071 544.5C646.699 552.372 652.692 559.357 660.571 559.5C668.583 559.645 675.024 552.5 674.571 544.5Z" stroke="#FFAE00" stroke-width="4" fill="none"/>
  <path d="M705.571 584C711.822 575.191 697.232 558.169 687.571 563C678.664 567.454 678.664 584.046 687.571 588.5C694.052 591.74 701.378 589.909 705.571 584Z" stroke="#FFAE00" stroke-width="4" fill="none"/>
  <path d="M727.571 615C726.946 606.625 718.196 600.375 710.071 602.5C699.638 605.229 701.817 629.197 712.571 630C720.833 630.617 728.188 623.261 727.571 615Z" stroke="#FFAE00" stroke-width="4" fill="none"/>
  <path d="M735.571 659C735.571 650 729.732 641.472 721.571 643C715.122 644.207 712.174 649.967 711.571 656.5C710.835 664.481 715.057 673.397 723.071 673.5C730.547 673.596 735.571 668 735.571 659Z" stroke="#FFAE00" stroke-width="4" fill="none"/>
  <path d="M716.071 712.5C731.071 709.5 729.555 688.798 719.571 686.5C712.182 684.799 704.629 689.992 703.571 697.5C702.507 705.051 701.071 715.5 716.071 712.5Z" stroke="#FFAE00" stroke-width="4" fill="none"/>
  <path d="M684.571 728C688.461 722.631 695.154 721.008 701.071 724C709.997 728.513 694.571 749 685.071 744C675.571 739 680.903 733.062 684.571 728Z" stroke="#FFAE00" stroke-width="4" fill="none"/>
  <path d="M862.071 469C862.066 464.858 858.713 461.504 854.571 461.5C850.289 461.495 846.791 465.227 847.071 469.5C847.343 473.642 850.929 476.781 855.071 476.5C859.068 476.229 862.076 473.006 862.071 469Z" stroke="#FFAE00" stroke-width="4" fill="none"/>
</svg>"""


def _to_data_uri(svg: bytes) -> str:
    b64 = base64.b64encode(svg).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


DEFAULT_BRAND_DATA_URI = _to_data_uri(DEFAULT_BRAND_SVG)
