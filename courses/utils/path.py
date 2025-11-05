import re

def to_wsl_path(p: str) -> str:
    # C:\Users\...  ->  /mnt/c/Users/...
    if p is None:
        return p
    if re.match(r"^[A-Za-z]:\\", p):
        drive = p[0].lower()
        p = p.replace("\\", "/")
        return f"/mnt/{drive}/{p[3:]}"
    return p