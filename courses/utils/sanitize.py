# pip install bleach markdown
import bleach
from markdown import markdown

ALLOWED_TAGS = [
    "p","br","ul","ol","li","strong","em","code","pre","blockquote",
    "h1","h2","h3","h4","h5","h6","a"
]
ALLOWED_ATTRS = {
    "a": ["href", "title", "rel", "target"],
}
ALLOWED_PROTOCOLS = ["http","https","mailto"]

def md_to_safe_html(md_text: str) -> str:
    """Render Markdown, then sanitize the resulting HTML."""
    raw_html = markdown(md_text or "", extensions=["fenced_code", "codehilite"])
    clean = bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    # Make links safe; no javascript: etc.
    return bleach.linkify(clean)
