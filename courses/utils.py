def text_chars(payload: str) -> int:
    # normalise fins de ligne et espace
    payload = (payload or "").replace("\r\n", "\n").strip()
    return len(payload)

def text_seconds_equiv(payload: str) -> int:
    """Si tu veux garder une conversion 'seconds' legacy (optionnel)."""
    # 180 mots/min ≈ 3 mots/s => 1 mot ≈ 0.33s
    # mot ~ 5 chars + espace -> ~6 chars/mot :  chars/6 * 0.33s ≈ chars * 0.055
    ch = text_chars(payload)
    return int(ch * 0.055)  # ajuste si besoin
